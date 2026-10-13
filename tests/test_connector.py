import base64
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
import wave
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1];CODE=(BASE/'kit'/'connector') if (BASE/'kit'/'connector').is_dir() else (BASE/'connector');sys.path.insert(0,str(CODE))
import server,setup_owner,backup
from contract import CallableAdapter,HTTPAdapter,Fault
from providers import STT,TTS,MockSTT,MockTTS,OpenAISTT,OpenAITTS
from tg_runtime_bridge import make_bridge
from fake_existing import FakeExisting,IDENTITY
PHRASE='synthetic-owner-test-phrase'

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def wav():
    b=io.BytesIO()
    with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*8000)
    return base64.b64encode(b.getvalue()).decode()

class ConnectorTests(unittest.TestCase):
    def setUp(self):
        platform_env={name:os.environ[name] for name in ('SystemRoot','SYSTEMROOT','WINDIR') if name in os.environ}
        self.env=patch.dict(os.environ,platform_env,clear=True);self.env.start();self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'edge';setup_owner.initialize(self.data,PHRASE)
        self.fake=FakeExisting();self.adapter=CallableAdapter(self.fake,*IDENTITY);self.port=free_port();self.origin=f'http://127.0.0.1:{self.port}'
        self.settings=server.Settings(self.data,self.port);self.settings.min_interval=0;self.settings.mock_voice=True;self.settings.voice=True;self.start()
    def start(self):
        self.http=server.make_server(self.settings,self.adapter,MockSTT(),MockTTS());self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def stop(self):
        if self.http.turns.active:self.http.turns.cancel(self.http.turns.active)
        self.http.shutdown();self.thread.join(3);self.http.server_close()
        end=time.time()+2
        while self.http.turns.active and time.time()<end:time.sleep(.01)
        self.http.store.db.close()
    def tearDown(self):self.stop();self.env.stop();self.temp.cleanup()
    def request(self,path,body=None,cookie=None,origin=True,host=None,raw=None,ctype='application/json'):
        h={};method='POST' if body is not None or raw is not None else 'GET'
        if cookie:h['Cookie']=cookie
        if host:h['Host']=host
        if method=='POST':
            h['Content-Type']=ctype
            if origin is True:h['Origin']=self.origin
            elif origin:h['Origin']=origin
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        c.request(method,path,raw if raw is not None else (json.dumps(body) if body is not None else None),h);r=c.getresponse();data=r.read();headers=dict(r.getheaders());status=r.status;c.close()
        return status,json.loads(data) if headers.get('Content-Type')=='application/json' else data,headers
    def login(self):
        status,data,h=self.request('/api/login',{'phrase':PHRASE});self.assertEqual(status,200);self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie']);return h['Set-Cookie'].split(';')[0]
    def body(self,voice=False):return dict(agentId=IDENTITY[0],conversationId=IDENTITY[1],requestId=str(uuid.uuid4()),**({'audio':wav()} if voice else {'message':'phone text'}))
    def terminal(self,cookie,rid):
        end=time.time()+3
        while time.time()<end:
            status,result,_=self.request('/api/turn/'+rid,cookie=cookie);self.assertEqual(status,200)
            if result['status'] in ('done','failed','cancelled','timed_out','unknown_after_restart'):return result
            time.sleep(.01)
        self.fail('Turn never reached terminal state')
    def test_tg_phone_tg_same_agent_history_memory(self):
        self.fake.telegram('before phone');cookie=self.login();body=self.body(True)
        self.assertEqual(self.request('/api/turn',body,cookie)[0],202);r=self.terminal(cookie,body['requestId']);self.assertEqual(r['status'],'done');self.assertEqual(r['agentId'],IDENTITY[0]);self.assertEqual(r['conversationId'],IDENTITY[1]);self.assertIn('synthetic-tea',r['message']['content']);self.assertTrue(r['mock'])
        status,audio,h=self.request(r['audioUrl'],cookie=cookie);self.assertEqual(status,200);self.assertEqual(h['Cache-Control'],'no-store')
        with wave.open(io.BytesIO(audio)) as w:self.assertEqual(w.readframes(1600),b'\0\0'*1600)
        self.fake.telegram('after phone');history=self.request('/api/history',cookie=cookie)[1]
        self.assertEqual(history['messages'],self.fake.messages);self.assertEqual(len(history['messages']),6);self.assertEqual(self.fake.calls,['telegram','phone-voice','telegram']);self.assertNotIn('privateInternal',history)
        self.assertEqual(set(p.name for p in self.data.iterdir()),{'edge.sqlite3','owner-password.hash'})
        db=self.http.store.db;tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};self.assertNotIn('messages',tables);self.assertNotIn('synthetic-tea',(self.data/'edge.sqlite3').read_bytes().decode('latin1'))
    def test_auth_origin_host_private_routes(self):
        for p in ['/api/history','/api/session','/api/turn/'+str(uuid.uuid4())]:self.assertEqual(self.request(p)[0],401)
        self.assertEqual(self.request('/api/login',{'phrase':'wrong-password-phrase'})[0],401)
        for origin in [False,'https://foreign.invalid']:self.assertEqual(self.request('/api/login',{'phrase':PHRASE},origin=origin)[0],403)
        self.assertEqual(self.request('/health',host='foreign.invalid')[0],403)
        cookie=self.login();body=self.body()
        self.assertEqual(self.request('/api/turn',body,cookie,origin=False)[0],403);self.assertEqual(self.request('/api/turn',body,cookie,ctype='text/plain')[0],415)
        for raw in [b'[]',b'{']:self.assertEqual(self.request('/api/turn',cookie=cookie,raw=raw)[0],400)
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=2)
        c.putrequest('POST','/api/turn');c.putheader('Origin',self.origin);c.putheader('Cookie',cookie);c.putheader('Content-Type','application/json');c.putheader('Content-Length','1500001');c.endheaders();r=c.getresponse();self.assertEqual(r.status,413);r.read();c.close()
        for p in ['/data/edge.sqlite3','/owner-password.hash','/AGENTS.md','/memory.md','/../server.py','/app.js?private=q']:self.assertEqual(self.request(p)[0],404)
        token=cookie.split('=',1)[1];self.assertNotIn(token,(self.data/'edge.sqlite3').read_bytes().decode('latin1'))
        self.http.store.db.execute('UPDATE sessions SET expires=1');self.http.store.db.commit();self.assertEqual(self.request('/api/history',cookie=cookie)[0],401)
        cookie=self.login();self.assertEqual(self.request('/api/logout',{},cookie)[0],200);self.assertEqual(self.request('/api/history',cookie=cookie)[0],401)
    def test_identity_and_owner_mapping_rejected(self):
        cookie=self.login();body=self.body()
        for k in ['agentId','conversationId']:self.assertEqual(self.request('/api/turn',dict(body,**{k:'another'}),cookie)[0],403)
        with self.assertRaises(Fault):self.fake.history({**self.fake.binding,'ownerId':'other'})
        old=self.fake.describe;self.fake.describe=lambda p:{**old(p),'agentId':'wrong'}
        self.assertEqual(self.request('/api/session',cookie=cookie)[0],502);self.assertEqual(self.fake.calls,[])
    def test_replay_conflict_and_restart_no_second_call(self):
        cookie=self.login();body=self.body();self.request('/api/turn',body,cookie);self.assertEqual(self.terminal(cookie,body['requestId'])['status'],'done')
        self.assertEqual(self.request('/api/turn',body,cookie)[1]['status'],'done');self.assertEqual(self.request('/api/turn',dict(body,message='changed'),cookie)[0],409);self.assertEqual(len(self.fake.calls),1)
        self.stop();self.start();self.assertEqual(self.request('/api/turn',body,cookie)[1]['status'],'done');self.assertEqual(len(self.fake.calls),1);self.assertEqual(len(self.request('/api/history',cookie=cookie)[1]['messages']),2)
        # Canonical idempotency is also enforced by runtime, including channels.
        replay=self.fake.turn({**self.fake.binding,'requestId':body['requestId'],'message':body['message'],'channel':'telegram'});self.assertTrue(replay['replayed']);self.assertEqual(len(self.fake.messages),2)
    def test_default_off_no_external_transport(self):
        s=server.Settings(self.data,self.port);self.assertFalse(s.voice);self.assertFalse(s.mock_voice);self.assertFalse(s.stt.enabled);self.assertFalse(s.tts.enabled)
        for p in [STT(),TTS()]:
            with self.assertRaises(Fault) as e:p.post({},1)
            self.assertEqual(e.exception.status,503)
        self.settings.voice=False;cookie=self.login();self.assertEqual(self.request('/api/turn',self.body(True),cookie)[0],503);self.assertEqual(self.fake.calls,[])
    def test_provider_adapters_injected_no_paid_io(self):
        calls=[]
        def transport(body,timeout):calls.append(body);return {'text':'synthetic recognition'}
        s=STT(True,'https://synthetic.invalid/stt','synthetic-never-sent',transport);self.assertEqual(s.transcribe(b'wav',1),'synthetic recognition');self.assertEqual(calls[0]['mime'],'audio/wav')
        t=TTS(True,'https://synthetic.invalid/tts','synthetic-never-sent',lambda b,t:{'audio':base64.b64encode(b'synthetic-sound').decode(),'mime':'audio/wav'})
        self.assertEqual(t.synthesize('text',1),(b'synthetic-sound','audio/wav'))
        with self.assertRaises(Fault):t.synthesize('x'*4001,1)
        with self.assertRaises(Fault):STT(True,'http://synthetic.invalid','x',transport).transcribe(b'a',1)
    def test_direct_openai_audio_off_and_injected_wire_format(self):
        calls=[]
        def transport(req,timeout,limit):
            calls.append(req)
            if req.full_url.endswith('/transcriptions'):return b'{"text":"synthetic direct STT"}'
            return b'synthetic-mp3'
        for provider in [OpenAISTT(),OpenAITTS()]:
            with self.assertRaises(Fault):provider.ready()
        stt=OpenAISTT(True,'synthetic-not-live','synthetic-stt-model',transport);self.assertEqual(stt.transcribe(b'synthetic-wav',1),'synthetic direct STT');self.assertIn(b'name="file"',calls[0].data);self.assertIn(b'synthetic-wav',calls[0].data)
        tts=OpenAITTS(True,'synthetic-not-live','synthetic-tts-model','alloy',transport);self.assertEqual(tts.synthesize('synthetic reply',1),(b'synthetic-mp3','audio/mpeg'));self.assertEqual(json.loads(calls[1].data)['input'],'synthetic reply');self.assertEqual(json.loads(calls[1].data)['response_format'],'mp3');self.assertEqual(len(calls),2)
        with patch.dict(os.environ,{'STT_PROVIDER':'openai','TTS_PROVIDER':'openai'}):
            s=server.Settings(self.data,self.port);self.assertFalse(s.stt.enabled);self.assertFalse(s.tts.enabled)
    def test_cancel_before_submit_tombstone(self):
        cookie=self.login();body=self.body(True);self.assertEqual(self.request('/api/turn/cancel',{'requestId':body['requestId']},cookie)[0],200)
        self.assertEqual(self.request('/api/turn',body,cookie)[1]['status'],'cancelled');self.assertEqual(self.fake.calls,[])
    def test_interrupt_busy_and_timeout_no_commit(self):
        cookie=self.login();self.fake.gate=threading.Event();body=self.body();self.request('/api/turn',body,cookie);self.assertTrue(self.fake.entered.wait(1))
        self.assertEqual(self.request('/api/turn',self.body(),cookie)[0],409)
        self.request('/api/turn/cancel',{'requestId':body['requestId']},cookie);self.assertEqual(self.terminal(cookie,body['requestId'])['status'],'cancelled')
        end=time.time()+1
        while self.http.turns.active and time.time()<end:time.sleep(.01)
        self.assertEqual(self.fake.messages,[])
        self.settings.turn_timeout=.08;body=self.body();self.request('/api/turn',body,cookie);self.assertEqual(self.terminal(cookie,body['requestId'])['status'],'timed_out');self.assertEqual(self.fake.messages,[])
    def test_ambiguous_commit_not_retried(self):
        cookie=self.login();self.fake.fail_after_commit=True;body=self.body();self.request('/api/turn',body,cookie);self.assertEqual(self.terminal(cookie,body['requestId'])['status'],'failed')
        self.request('/api/turn',body,cookie);self.assertEqual(len(self.fake.calls),1);self.assertEqual(len(self.request('/api/history',cookie=cookie)[1]['messages']),2)
    def test_cancel_during_tts_retains_existing_history(self):
        class BlockTTS:
            def __init__(self):self.entered=threading.Event();self.release=threading.Event();self.calls=0
            def ready(self):pass
            def synthesize(self,text,timeout):self.calls+=1;self.entered.set();self.release.wait(1);return b'test','audio/wav'
        p=BlockTTS();self.http.turns.tts=p;cookie=self.login();b=self.body(True);self.request('/api/turn',b,cookie);self.assertTrue(p.entered.wait(1));self.request('/api/turn/cancel',{'requestId':b['requestId']},cookie);p.release.set()
        self.assertEqual(self.terminal(cookie,b['requestId'])['status'],'cancelled');self.assertEqual(self.request('/api/turn/'+b['requestId']+'/audio',cookie=cookie)[0],410);self.assertEqual(len(self.fake.messages),2);self.assertEqual(p.calls,1)
    def test_cancel_during_stt_and_failed_provider_no_agent_call(self):
        class BlockSTT:
            def __init__(self):self.entered=threading.Event();self.release=threading.Event();self.calls=0
            def ready(self):pass
            def transcribe(self,raw,timeout):self.calls+=1;self.entered.set();self.release.wait(1);return 'synthetic stt'
        p=BlockSTT();self.http.turns.stt=p;cookie=self.login();b=self.body(True);self.request('/api/turn',b,cookie);self.assertTrue(p.entered.wait(1));self.request('/api/turn/cancel',{'requestId':b['requestId']},cookie);p.release.set()
        self.assertEqual(self.terminal(cookie,b['requestId'])['status'],'cancelled')
        end=time.time()+1
        while self.http.turns.active and time.time()<end:time.sleep(.01)
        self.assertEqual(self.fake.messages,[]);self.request('/api/turn',b,cookie);self.assertEqual(p.calls,1)
        class FailedSTT:
            def ready(self):pass
            def transcribe(self,*a):raise Fault(502,'synthetic_stt_failure')
        self.http.turns.stt=FailedSTT();b=self.body(True);self.request('/api/turn',b,cookie);self.assertEqual(self.terminal(cookie,b['requestId'])['status'],'failed');self.assertEqual(self.fake.calls,[])
    def test_audio_replay_expiry_and_no_tts_retry(self):
        class CountTTS(MockTTS):
            calls=0
            def synthesize(self,*a):self.calls+=1;return super().synthesize(*a)
        p=CountTTS();self.http.turns.tts=p;cookie=self.login();b=self.body(True);self.request('/api/turn',b,cookie);r=self.terminal(cookie,b['requestId']);self.assertEqual(r['status'],'done')
        self.request('/api/turn',b,cookie)
        for _ in range(2):self.assertEqual(self.request(r['audioUrl'],cookie=cookie)[0],200)
        self.assertEqual(p.calls,1)
        item=self.http.turns.audio[b['requestId']];self.http.turns.audio[b['requestId']]=(time.monotonic()-301,*item[1:])
        self.assertEqual(self.request(r['audioUrl'],cookie=cookie)[0],410);self.assertEqual(p.calls,1)
    def test_process_restart_preserves_binding_history_and_journal(self):
        import subprocess
        bridge_port=free_port();child_port=free_port();token='synthetic-connector-token-process-only'
        bridge=make_bridge(self.fake,agent_id=IDENTITY[0],conversation_id=IDENTITY[1],owner_id=IDENTITY[2],token=token,port=bridge_port)
        thread=threading.Thread(target=bridge.serve_forever,daemon=True);thread.start()
        env={**{name:os.environ[name] for name in ('SystemRoot','SYSTEMROOT','WINDIR') if name in os.environ},'PATH':os.defpath,'PYTHONDONTWRITEBYTECODE':'1','EXISTING_AGENT_URL':f'http://127.0.0.1:{bridge_port}','EXISTING_AGENT_TOKEN':token,'EXISTING_AGENT_ID':IDENTITY[0],'EXISTING_CONVERSATION_ID':IDENTITY[1],'EXISTING_OWNER_ID':IDENTITY[2]}
        child_data=Path(self.temp.name)/'child';setup_owner.initialize(child_data,PHRASE)
        def req(path,body=None,cookie=None):
            c=http.client.HTTPConnection('127.0.0.1',child_port,timeout=2);h={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{child_port}'}
            if cookie:h['Cookie']=cookie
            c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),h);r=c.getresponse();data=json.loads(r.read());cookie_out=r.getheader('Set-Cookie');status=r.status;c.close();return status,data,cookie_out
        def launch():
            child=subprocess.Popen([sys.executable,str(CODE/'server.py'),'--port',str(child_port),'--data-dir',str(child_data)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(100):
                try:
                    if req('/health')[0]==200:return child
                except OSError:pass
                time.sleep(.02)
            child.terminate();child.wait(3);self.fail('Connector process did not start')
        child=None
        try:
            self.fake.telegram('before process');child=launch();status,_,cookie=req('/api/login',{'phrase':PHRASE});self.assertEqual(status,200);cookie=cookie.split(';')[0]
            b=self.body();self.assertEqual(req('/api/turn',b,cookie)[0],202)
            for _ in range(100):
                if req('/api/turn/'+b['requestId'],cookie=cookie)[1]['status']=='done':break
                time.sleep(.02)
            else:self.fail('Child turn incomplete')
            child.terminate();child.wait(3);child=launch()
            self.assertEqual(req('/api/history',cookie=cookie)[1]['messages'],self.fake.messages);self.assertEqual(req('/api/turn',b,cookie)[1]['status'],'done');self.assertEqual(self.fake.calls,['telegram','phone-text'])
        finally:
            if child:child.terminate();child.wait(3)
            bridge.shutdown();thread.join();bridge.server_close()
    def test_budget_survives_restart_and_failed_attempt(self):
        self.settings.daily_turns=1;cookie=self.login();b=self.body();self.request('/api/turn',b,cookie);self.terminal(cookie,b['requestId']);self.stop();self.start();self.assertEqual(self.request('/api/turn',self.body(),cookie)[0],429)
    def test_deadline_expiry_without_timer_callback_is_timeout(self):
        class DelayedTimer:
            def __init__(self,*args,**kwargs):pass
            def start(self):pass
            def cancel(self):pass
        self.fake.gate=threading.Event();self.settings.turn_timeout=.05
        cookie=self.login();body=self.body()
        with patch('threading.Timer',DelayedTimer):
            self.assertEqual(self.request('/api/turn',body,cookie)[0],202)
            result=self.terminal(cookie,body['requestId'])
        self.assertEqual(result['status'],'timed_out')
        self.assertEqual(self.fake.messages,[])
    def test_backup_restore_and_no_agent_data(self):
        cookie=self.login();b=self.body();self.request('/api/turn',b,cookie);self.terminal(cookie,b['requestId'])
        out=Path(self.temp.name)/'rollback';backup.backup(self.data,out);self.assertTrue(backup.verify(out));self.assertEqual(set(json.loads((out/'receipt.json').read_text())),{'owner-password.hash','edge.sqlite3'})
        restored=server.Store(out,self.adapter.identity);self.assertTrue(restored.session(cookie.split('=',1)[1]));self.assertEqual(restored.db.execute('SELECT status FROM turns').fetchone()[0],'done');restored.db.close()
        with self.assertRaises(FileExistsError):backup.backup(self.data,out)
        (out/'edge.sqlite3').write_bytes(b'tamper')
        with self.assertRaises(ValueError):backup.verify(out)
    def test_restart_marks_unfinished_unknown_and_rebind_refused(self):
        rid=str(uuid.uuid4());self.http.store.db.execute('INSERT INTO turns VALUES (?,?,?)',(rid,'test','thinking'));self.http.store.db.commit();self.stop();self.start();self.assertEqual(self.http.turns.status(rid)['status'],'unknown_after_restart')
        with self.assertRaises(ValueError):server.Store(self.data,dict(self.adapter.identity,agentId='new'))
    def test_http_adapter_tg_callable_bridge(self):
        port=free_port();token='synthetic-connector-token-for-test-only';bridge=make_bridge(self.fake,agent_id=IDENTITY[0],conversation_id=IDENTITY[1],owner_id=IDENTITY[2],token=token,port=port)
        thread=threading.Thread(target=bridge.serve_forever,daemon=True);thread.start()
        try:
            remote=HTTPAdapter(f'http://127.0.0.1:{port}',token,*IDENTITY);self.fake.telegram('before HTTP');self.assertEqual(len(remote.history()['messages']),2)
            r=remote.turn('HTTP phone',str(uuid.uuid4()),'phone-text',threading.Event(),time.monotonic()+2);self.assertEqual(r['agentId'],IDENTITY[0]);self.assertEqual(len(remote.history()['messages']),4)
            with self.assertRaises(Fault):HTTPAdapter(f'http://127.0.0.1:{port}','wrong-token',*IDENTITY).history()
        finally:bridge.shutdown();thread.join();bridge.server_close()
    def test_wav_limits_login_throttle_secure_settings(self):
        cookie=self.login()
        for audio in ['',base64.b64encode(b'not WAV').decode()]:self.assertEqual(self.request('/api/turn',dict(self.body(True),audio=audio),cookie)[0],400)
        for _ in range(7):self.assertEqual(self.request('/api/login',{'phrase':'wrong-password-phrase'})[0],401)
        self.assertEqual(self.request('/api/login',{'phrase':PHRASE})[0],429)
        with patch.dict(os.environ,{'APP_ORIGIN':'http://public.invalid'}):
            with self.assertRaises(ValueError):server.Settings(self.data,self.port)
        with patch.dict(os.environ,{'APP_ORIGIN':'https://app.example.invalid'}):self.assertTrue(server.Settings(self.data,self.port).secure)

if __name__=='__main__':unittest.main(verbosity=2)
