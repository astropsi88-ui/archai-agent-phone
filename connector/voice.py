"""Bounded single turns, transport journal only; canonical history stays upstream."""
import base64
import hashlib
import io
import json
import threading
import time
import uuid
import wave
from contract import Fault

MAX_SECONDS=30

def valid_id(value):
    try:
        if str(uuid.UUID(value))!=value: raise ValueError()
        return value
    except (ValueError,TypeError,AttributeError): raise Fault(400,'request_id_required') from None

def decode_wav(encoded):
    try:
        if not isinstance(encoded,str) or len(encoded)>1400000: raise ValueError()
        raw=base64.b64decode(encoded,validate=True)
        if not 44<len(raw)<=1000000: raise ValueError()
        with wave.open(io.BytesIO(raw),'rb') as w:
            if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getframerate()!=16000 or not .25<=w.getnframes()/16000<=30: raise ValueError()
            if len(w.readframes(w.getnframes()))!=w.getnframes()*2: raise ValueError()
        return raw
    except (ValueError,TypeError,wave.Error,EOFError): raise Fault(400,'wav_mono_16khz_025_to_30_seconds_required') from None

class Turns:
    def __init__(self,settings,store,adapter,stt,tts,files=None):
        self.s,self.store,self.adapter,self.stt,self.tts=settings,store,adapter,stt,tts
        self.files=files
        self.lock=store.lock; self.active=None; self.events={}; self.results={}; self.audio={}
        with self.lock:
            store.db.executescript('CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, fingerprint TEXT, status TEXT); CREATE TABLE IF NOT EXISTS budget(day TEXT PRIMARY KEY, count INTEGER);')
            store.db.execute("UPDATE turns SET status='unknown_after_restart' WHERE status IN ('queued','transcribing','thinking','speaking')")
            store.db.commit()
    def row(self,rid): return self.store.db.execute('SELECT * FROM turns WHERE id=?',(rid,)).fetchone()
    def status(self,rid):
        valid_id(rid)
        with self.lock:
            row=self.row(rid)
            if not row: raise Fault(404,'turn_missing')
            return {'requestId':rid,'status':row['status'],**self.results.get(rid,{})}
    def set(self,rid,state,result=None):
        with self.lock:
            row=self.row(rid)
            if row and row['status'] in ('cancelled','timed_out'): return
            self.store.db.execute('UPDATE turns SET status=? WHERE id=?',(state,rid));self.store.db.commit()
            if result is not None:
                while len(self.results)>=6 and rid not in self.results:self.results.pop(next(iter(self.results)))
                self.results[rid]=result
    def pace(self):
        day=time.strftime('%Y-%m-%d',time.gmtime()); now=time.time()
        db=self.store.db
        count=db.execute('SELECT count FROM budget WHERE day=?',(day,)).fetchone()
        if count and count[0]>=self.s.daily_turns: raise Fault(429,'daily_turn_budget')
        if now-self.store.last_turn<self.s.min_interval: raise Fault(429,'turn_rate_limited')
        db.execute('INSERT INTO budget VALUES (?,1) ON CONFLICT(day) DO UPDATE SET count=count+1',(day,));db.commit()
        self.store.last_turn=now
    def submit(self,body):
        rid=valid_id(body.get('requestId'))
        if any(body.get(k)!=self.adapter.identity.get(k) for k in ('agentId','conversationId')): raise Fault(403,'agent_or_conversation_mismatch')
        from files import file_ids
        ids=file_ids(body.get('fileIds',[]))
        speak=body.get('replyVoice','audio' in body)
        if type(speak) is not bool:raise Fault(400,'invalid_reply_voice')
        audio='audio' in body
        if audio and 'message' in body: raise Fault(400,'single_input_required')
        value=decode_wav(body['audio']) if audio else body.get('message')
        if not audio and (not isinstance(value,str) or not (0<=len(value.strip())<=2000 and (value.strip() or ids))): raise Fault(400,'message_length')
        if not audio:value=value.strip()
        fingerprint=hashlib.sha256(((b'audio:'+value) if audio else ('text:'+value).encode())+json.dumps({'fileIds':ids,'replyVoice':speak},sort_keys=True).encode()).hexdigest()
        with self.lock:
            old=self.row(rid)
            if old:
                if old['fingerprint'] not in (fingerprint,'cancelled'):raise Fault(409,'request_id_conflict')
                return self.status(rid)
            if self.active:raise Fault(409,'turn_busy_no_queue')
            if audio:
                if not self.s.voice:raise Fault(503,'voice_disabled')
                self.stt.ready()
            if speak:
                if not self.s.voice:raise Fault(503,'voice_disabled')
                self.tts.ready()
            if ids:
                if not self.files:raise Fault(503,'existing_runtime_attachments_not_configured')
                self.files.validate_ready(ids)
            self.adapter.describe() # Confirm canonical binding before reserving budget.
            self.pace()
            self.store.db.execute('INSERT INTO turns VALUES (?,?,?)',(rid,fingerprint,'queued'));self.store.db.commit()
            cancel=threading.Event();self.events[rid]=cancel;self.active=rid
            deadline=time.monotonic()+self.s.turn_timeout
            timer=threading.Timer(self.s.turn_timeout,lambda:self.cancel(rid,'timed_out'));timer.daemon=True;timer.start()
            threading.Thread(target=self.run,args=(rid,value,audio,cancel,deadline,timer,ids,speak),daemon=True).start()
            return {'requestId':rid,'status':'queued'}
    def cancel(self,rid,state='cancelled'):
        valid_id(rid)
        with self.lock:
            if rid in self.events:self.events[rid].set()
            row=self.row(rid)
            if not row:
                self.pace();self.store.db.execute('INSERT INTO turns VALUES (?,?,?)',(rid,'cancelled',state))
            elif row['status'] not in ('failed','timed_out','cancelled'):
                self.store.db.execute('UPDATE turns SET status=? WHERE id=?',(state,rid))
            self.store.db.commit();self.audio.pop(rid,None);self.results.pop(rid,None)
        return {'requestId':rid,'status':state}
    def run(self,rid,value,is_audio,cancel,deadline,timer,ids,speak):
        result={}
        def remaining():
            if cancel.is_set() or time.monotonic()>=deadline: raise Fault(409,'turn_cancelled_or_timeout')
            return deadline-time.monotonic()
        try:
            remaining()
            if is_audio:
                self.set(rid,'transcribing');text=self.stt.transcribe(value,remaining());value=None
                result['transcript']=text
            else:text=value
            remaining();self.set(rid,'thinking',result)
            reply=self.adapter.turn(text,rid,'phone-voice' if is_audio else 'phone-text',cancel,deadline,ids)
            remaining();result.update(reply)
            if speak:
                self.set(rid,'speaking',result)
                raw,mime=self.tts.synthesize(reply['message']['content'],remaining());remaining()
                with self.lock:
                    if cancel.is_set():return
                    now=time.monotonic();self.audio={k:v for k,v in self.audio.items() if v[0]>now-300}
                    while len(self.audio)>=6:self.audio.pop(next(iter(self.audio)))
                    self.audio[rid]=(now,raw,mime)
                result['audioUrl']='/api/turn/'+rid+'/audio'
            remaining();result['mock']=self.s.mock_voice;self.set(rid,'done',result)
        except Fault as e:
            if not cancel.is_set():
                if time.monotonic() >= deadline:self.cancel(rid,'timed_out')
                else:self.set(rid,'failed',{**result,'error':e.code})
        except Exception:
            if not cancel.is_set():
                if time.monotonic() >= deadline:self.cancel(rid,'timed_out')
                else:self.set(rid,'failed',{**result,'error':'upstream_failed_refresh_history_no_retry'})
        finally:
            timer.cancel()
            with self.lock:
                self.events.pop(rid,None)
                if self.active==rid:self.active=None
    def get_audio(self,rid):
        valid_id(rid)
        with self.lock:
            item=self.audio.get(rid)
            if not item or item[0]<=time.monotonic()-300:raise Fault(410,'audio_expired_no_paid_regeneration')
            return item[1:]
