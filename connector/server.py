"""Phone edge for an existing agent; loopback, standard library, no model brain."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from contract import Fault, HTTPAdapter, Unconfigured
from providers import STT,TTS,MockSTT,MockTTS,OpenAISTT,OpenAITTS
from voice import Turns
from files import Files, LIMITS, CHUNK
ROOT=Path(__file__).resolve().parent
PUBLIC=ROOT/'public'
STATIC = {'/app.007dec0ba9ecd8f8.js': ('app.007dec0ba9ecd8f8.js', 'text/javascript; charset=utf-8'), '/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/draft.js': ('draft.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/sw.js': ('sw.js', 'text/javascript; charset=utf-8'),
          '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json'),
          '/icon-192.png': ('icon-192.png', 'image/png'),
          '/icon-512.png': ('icon-512.png', 'image/png')}

def password_hash(phrase, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(phrase.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt:{salt}:{digest}'


def password_valid(phrase, stored):
    try:
        algorithm, salt, digest = stored.split(':')
        return algorithm == 'scrypt' and hmac.compare_digest(password_hash(phrase, salt), stored)
    except (ValueError, TypeError):
        return False


def digest_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Settings:
    def __init__(self,data=None,port=8765):
        self.data=Path(data or os.environ.get('DATA_DIR',ROOT/'data')).resolve();self.port=port
        self.origin=os.environ.get('APP_ORIGIN',f'http://127.0.0.1:{port}').rstrip('/')
        p=urlsplit(self.origin)
        if p.scheme not in ('http','https') or not p.netloc or p.path or p.query or p.fragment or p.username:raise ValueError('APP_ORIGIN must be an origin')
        if p.scheme=='http' and p.hostname not in ('127.0.0.1','localhost'):raise ValueError('Public app requires HTTPS')
        self.secure=p.scheme=='https';self.voice=os.environ.get('VOICE_ENABLED','0')=='1'
        self.mock_voice=os.environ.get('MOCK_VOICE','0')=='1'
        if self.mock_voice and p.hostname not in ('127.0.0.1','localhost'):raise ValueError('Mock voice is local test only')
        self.daily_turns=int(os.environ.get('MAX_DAILY_TURNS','20'));self.min_interval=float(os.environ.get('MIN_TURN_INTERVAL','2'))
        self.turn_timeout=float(os.environ.get('TURN_TIMEOUT_SECONDS','60'))
        if not 1<=self.daily_turns<=200 or not 0<=self.min_interval<=60 or not .05<=self.turn_timeout<=120:raise ValueError('Invalid guard limits')
        self.agent_url=os.environ.get('EXISTING_AGENT_URL','');self.agent_token=os.environ.get('EXISTING_AGENT_TOKEN','')
        self.agent_id=os.environ.get('EXISTING_AGENT_ID','');self.conversation_id=os.environ.get('EXISTING_CONVERSATION_ID','');self.owner_id=os.environ.get('EXISTING_OWNER_ID','')
        self.stt=STT(os.environ.get('ALLOW_STT_API','0')=='1',os.environ.get('STT_GATEWAY_URL',''),os.environ.get('STT_API_KEY',''))
        self.tts=TTS(os.environ.get('ALLOW_TTS_API','0')=='1',os.environ.get('TTS_GATEWAY_URL',''),os.environ.get('TTS_API_KEY',''))
        stt_kind=os.environ.get('STT_PROVIDER','off');tts_kind=os.environ.get('TTS_PROVIDER','off')
        if stt_kind not in ('off','gateway','openai') or tts_kind not in ('off','gateway','openai'):raise ValueError('Unknown audio provider')
        if stt_kind=='off':self.stt=STT()
        elif stt_kind=='openai':self.stt=OpenAISTT(os.environ.get('ALLOW_STT_API','0')=='1',os.environ.get('STT_API_KEY',''),os.environ.get('STT_MODEL',''))
        if tts_kind=='off':self.tts=TTS()
        elif tts_kind=='openai':self.tts=OpenAITTS(os.environ.get('ALLOW_TTS_API','0')=='1',os.environ.get('TTS_API_KEY',''),os.environ.get('TTS_MODEL',''),os.environ.get('TTS_VOICE','alloy'))

class Store:
    def __init__(self,data,identity):
        data.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.RLock();self.last_turn=0
        self.db=sqlite3.connect(data/'edge.sqlite3',check_same_thread=False);self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,expires INTEGER); CREATE TABLE IF NOT EXISTS binding(value TEXT);')
        binding=json.dumps(identity,sort_keys=True)
        old=self.db.execute('SELECT value FROM binding').fetchone()
        if old and old[0]!=binding:
            self.db.close()
            raise ValueError('Binding changed: needs_human verified rebind, never create a second conversation')
        if not old:self.db.execute('INSERT INTO binding VALUES (?)',(binding,))
        self.db.commit();os.chmod(data/'edge.sqlite3',0o600)
    def session(self,token):
        with self.lock:return bool(self.db.execute('SELECT 1 FROM sessions WHERE hash=? AND expires>?',(digest_token(token),int(time.time()))).fetchone())
    def new_session(self):
        token=secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute('DELETE FROM sessions WHERE expires<=?',(int(time.time()),))
            self.db.execute('INSERT INTO sessions VALUES (?,?)',(digest_token(token),int(time.time())+86400));self.db.commit()
        return token

def make_server(settings,adapter=None,stt=None,tts=None):
    if adapter is None:
        adapter=HTTPAdapter(settings.agent_url,settings.agent_token,settings.agent_id,settings.conversation_id,settings.owner_id) if settings.agent_url else Unconfigured()
    store=Store(settings.data,adapter.identity)
    stt=stt or (MockSTT() if settings.mock_voice else settings.stt);tts=tts or (MockTTS() if settings.mock_voice else settings.tts)
    files=Files(adapter)
    turns=Turns(settings,store,adapter,stt,tts,files);attempts=[];auth_lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        server_version='ExistingAgentPhone'
        def log_message(self,*args):pass
        def respond(self,status,data,mime='application/json',cookie=None):
            if mime=='application/json':data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Permissions-Policy','microphone=(self), camera=(), geolocation=()')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:self.send_header('Set-Cookie',cookie)
            self.end_headers();self.wfile.write(data)
        def cookie(self,token='',clear=False):
            return 'agent_session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age='+('0' if clear else '86400')+('; Secure' if settings.secure else '')
        def token(self):
            c=SimpleCookie()
            try:
                c.load(self.headers.get('Cookie',''));return c['agent_session'].value if 'agent_session' in c else ''
            except Exception:return ''
        def dispatch(self):
            try:self.route()
            except (BrokenPipeError,ConnectionResetError):pass
            except Fault as e:self.respond(e.status,{'error':e.code})
            except Exception:self.respond(500,{'error':'internal_error'})
        do_GET=do_POST=dispatch
        def route(self):
            self.connection.settimeout(10);u=urlsplit(self.path);path=u.path
            if self.headers.get('Host')!=urlsplit(settings.origin).netloc:raise Fault(403,'host_mismatch')
            if u.query or u.fragment:raise Fault(404,'not_found')
            if self.command=='GET' and path in STATIC:
                f,m=STATIC[path];return self.respond(200,(PUBLIC/f).read_bytes(),m)
            if path=='/health' and self.command=='GET':return self.respond(200,{'status':'ok','connector':True,'mockVoice':settings.mock_voice})
            if not path.startswith('/api/'):raise Fault(404,'not_found')
            origin=self.headers.get('Origin')
            if (self.command=='POST' and origin!=settings.origin) or (origin and origin!=settings.origin):raise Fault(403,'origin_mismatch')
            if self.headers.get('Sec-Fetch-Site')=='cross-site':raise Fault(403,'cross_site')
            body={}
            if self.command=='POST':
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise Fault(415,'json_required')
                try:length=int(self.headers.get('Content-Length','0'))
                except ValueError:raise Fault(400,'invalid_length') from None
                if self.headers.get('Transfer-Encoding') or not 0<length<=(1500000 if path in ('/api/turn','/api/files/chunk') else 16384):raise Fault(413,'body_size')
                try:
                    body=json.loads(self.rfile.read(length))
                    if not isinstance(body,dict):raise ValueError()
                except (ValueError,UnicodeError):raise Fault(400,'invalid_json') from None
            if self.command=='POST' and path=='/api/login':
                with auth_lock:
                    now=time.time();attempts[:]=[t for t in attempts if t>now-60]
                    if len(attempts)>=8:raise Fault(429,'login_rate_limited')
                    attempts.append(now)
                f=settings.data/'owner-password.hash'
                if not f.is_file():raise Fault(503,'needs_human_owner_setup')
                phrase=body.get('phrase')
                if not isinstance(phrase,str) or not 12<=len(phrase)<=256 or not password_valid(phrase,f.read_text().strip()):raise Fault(401,'invalid_login')
                return self.respond(200,{'ownerAuthenticated':True},cookie=self.cookie(store.new_session()))
            token=self.token()
            if not store.session(token):raise Fault(401,'owner_session_required')
            if path=='/api/session' and self.command=='GET':
                binding=adapter.describe()
                return self.respond(200,{**binding,'ownerAuthenticated':True,'voiceEnabled':settings.voice,'mockVoice':settings.mock_voice,'maxSeconds':30,'fileLimits':LIMITS,'chunkBytes':CHUNK})
            if path=='/api/history' and self.command=='GET':return self.respond(200,adapter.history())
            if path in ('/api/files/begin','/api/files/chunk','/api/files/finish') and self.command=='POST':
                return self.respond(200,files.call(path.rsplit('/',1)[1],body))
            if path.startswith('/api/files/') and self.command=='GET':
                return self.respond(200,files.call('status',{'uploadId':path.rsplit('/',1)[1]}))
            if path=='/api/turn' and self.command=='POST':return self.respond(202,turns.submit(body))
            if path=='/api/turn/cancel' and self.command=='POST':return self.respond(200,turns.cancel(body.get('requestId')))
            if path.startswith('/api/turn/') and self.command=='GET':
                parts=path.split('/')
                if len(parts)==4:return self.respond(200,turns.status(parts[3]))
                if len(parts)==5 and parts[4]=='audio':
                    raw,mime=turns.get_audio(parts[3]);return self.respond(200,raw,mime)
            if path=='/api/logout' and self.command=='POST':
                if turns.active:turns.cancel(turns.active)
                with store.lock:
                    turns.audio.clear();turns.results.clear();store.db.execute('DELETE FROM sessions WHERE hash=?',(digest_token(token),));store.db.commit()
                return self.respond(200,{'ok':True},cookie=self.cookie(clear=True))
            raise Fault(404,'not_found')
    http=ThreadingHTTPServer(('127.0.0.1',settings.port),Handler);http.daemon_threads=True
    http.store,http.adapter,http.turns=store,adapter,turns
    return http

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--data-dir');a=p.parse_args();os.umask(0o077)
    s=Settings(a.data_dir,a.port)
    if not (s.data/'owner-password.hash').is_file():raise SystemExit('needs_human: initialize local owner login with setup_owner.py')
    http=make_server(s)
    try:http.serve_forever()
    except KeyboardInterrupt:pass
    finally:http.server_close();http.store.db.close()
if __name__=='__main__':main()
