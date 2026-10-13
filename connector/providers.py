"""Independent STT/TTS provider gateways. Own neutral HTTP JSON contract; off by default.
These are NOT claimed compatible with arbitrary vendor URLs. Vendor translation belongs
in a trusted server gateway. No model chat provider lives in this connector.
"""
import base64
import io
import json
import wave
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from contract import Fault

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw): return None

class Gateway:
    def __init__(self, enabled=False, url='', key='', transport=None):
        self.enabled,self.url,self.key,self.transport=enabled,url,key,transport
    def ready(self):
        if not self.enabled or not self.url or not self.key: raise Fault(503,'needs_human_provider_disabled_or_unconfigured')
        p=urlsplit(self.url)
        if p.scheme != 'https' or not p.netloc or p.username or p.fragment:
            raise Fault(503,'provider_requires_trusted_https_url')
    def post(self, body, timeout):
        self.ready()
        if self.transport: return self.transport(body,timeout)
        req=Request(self.url,json.dumps(body).encode(),{'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        try:
            with build_opener(NoRedirect()).open(req,timeout=min(30,max(.01,timeout))) as res: raw=res.read(3000001)
            if len(raw)>3000000: raise ValueError()
            return json.loads(raw)
        except Exception: raise Fault(502,'provider_failed_no_automatic_retry') from None

class STT(Gateway):
    def transcribe(self, raw, timeout):
        result=self.post({'audio':base64.b64encode(raw).decode(),'mime':'audio/wav','sampleRate':16000},timeout)
        text=result.get('text')
        if not isinstance(text,str) or not 1 <= len(text.strip()) <= 2000: raise Fault(502,'invalid_stt_response')
        return text.strip()

class TTS(Gateway):
    def synthesize(self, text, timeout):
        if not 1 <= len(text) <= 4000: raise Fault(413,'tts_character_limit')
        result=self.post({'text':text},timeout)
        try:
            raw=base64.b64decode(result['audio'],validate=True); mime=result['mime']
            if not 0 < len(raw) <= 2000000 or mime not in ('audio/wav','audio/mpeg','audio/ogg'): raise ValueError()
            return raw,mime
        except Exception: raise Fault(502,'invalid_tts_response') from None

class MockSTT:
    """Test fixture: ignores audio; not real transcription."""
    def ready(self): pass
    def transcribe(self,raw,timeout): return 'MOCK STT: synthetic question; speech was not recognized.'
class MockTTS:
    """Test fixture: silent signal, never speech."""
    def ready(self): pass
    def synthesize(self,text,timeout):
        buf=io.BytesIO()
        with wave.open(buf,'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b'\0\0'*1600)
        return buf.getvalue(),'audio/wav'

# Direct vendor adapters: fixed endpoints, no chat/model brain, no automatic retry.
class OpenAIAudio:
    def __init__(self,enabled=False,key='',model='',transport=None):
        self.enabled,self.key,self.model,self.transport=enabled,key,model,transport
    def ready(self):
        if not self.enabled or not self.key or not self.model:raise Fault(503,'needs_human_openai_audio_configuration')
        if '\r' in self.model or '\n' in self.model or len(self.model)>100:raise Fault(503,'invalid_audio_model')
    def send(self,path,raw,mime,timeout,limit):
        self.ready()
        req=Request('https://api.openai.com/v1/audio/'+path,raw,{'Authorization':'Bearer '+self.key,'Content-Type':mime},method='POST')
        try:
            if self.transport:result=self.transport(req,min(30,max(.01,timeout)),limit)
            else:
                with build_opener(NoRedirect()).open(req,timeout=min(30,max(.01,timeout))) as r:result=r.read(limit+1)
            if not isinstance(result,bytes) or not 0<len(result)<=limit:raise ValueError()
            return result
        except Exception:raise Fault(502,'audio_provider_failed_no_automatic_retry') from None

class OpenAISTT(OpenAIAudio):
    def transcribe(self,raw,timeout):
        self.ready()
        import secrets
        boundary='phone-'+secrets.token_hex(16)
        parts=[]
        for name,value in [('model',self.model),('response_format','json')]:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="question.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+raw+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        result=self.send('transcriptions',b''.join(parts),'multipart/form-data; boundary='+boundary,timeout,65536)
        try:
            text=json.loads(result)['text']
            if not isinstance(text,str) or not 1<=len(text.strip())<=2000:raise ValueError()
            return text.strip()
        except Exception:raise Fault(502,'invalid_stt_response') from None

class OpenAITTS(OpenAIAudio):
    def __init__(self,enabled=False,key='',model='',voice='alloy',transport=None):
        super().__init__(enabled,key,model,transport);self.voice=voice
    def ready(self):
        super().ready()
        if self.voice not in ('alloy','ash','coral','echo','fable','onyx','nova','sage','shimmer','ballad','verse','marin','cedar'):raise Fault(503,'invalid_tts_voice')
    def synthesize(self,text,timeout):
        if not isinstance(text,str) or not 1<=len(text)<=4000:raise Fault(413,'tts_character_limit')
        payload=json.dumps({'model':self.model,'voice':self.voice,'input':text,'response_format':'mp3'}).encode()
        return self.send('speech',payload,'application/json',timeout,2000000),'audio/mpeg'
