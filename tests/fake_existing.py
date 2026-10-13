"""Synthetic existing runtime fixture with no production credentials or conversations."""
import threading
import time
import uuid
from contract import Fault

IDENTITY=('existing-agent-fixture','existing-tg-conversation','synthetic-owner')
class FakeExisting:
    def __init__(self):
        self.binding=dict(zip(('agentId','conversationId','ownerId'),IDENTITY));self.messages=[];self.requests={};self.memory={'favorite':'synthetic-tea'};self.calls=[];self.lock=threading.RLock()
        self.gate=None;self.entered=threading.Event();self.fail_after_commit=False
    def check(self,p):
        if any(p.get(k)!=v for k,v in self.binding.items()):raise Fault(403,'existing_owner_binding_rejected')
    def describe(self,p):self.check(p);return dict(self.binding)
    def history(self,p):self.check(p);return {**self.binding,'messages':self.messages[-100:],'privateInternal':'SYNTHETIC_PRIVATE_NEVER_EXPORT'}
    def turn(self,p,cancel=None,deadline=None):
        self.check(p);self.entered.set()
        if self.gate:
            while not self.gate.wait(.01):
                if (cancel and cancel.is_set()) or (deadline and time.monotonic()>deadline):raise Fault(409,'cancelled_before_commit')
        with self.lock:
            rid=p['requestId'];text=p['message']
            if rid in self.requests:
                old_text,result=self.requests[rid]
                if old_text!=text:raise Fault(409,'canonical_request_conflict')
                return {**result,'replayed':True}
            if cancel and cancel.is_set():raise Fault(409,'cancelled_before_commit')
            self.calls.append(p['channel'])
            self.messages.append(dict(id=str(uuid.uuid4()),role='user',content=text))
            response='EXISTING memory='+self.memory['favorite']+'; '+text
            msg=dict(id=str(uuid.uuid4()),role='assistant',content=response)
            self.messages.append(msg);result={**self.binding,'message':msg,'replayed':False}
            self.requests[rid]=(text,result)
            if self.fail_after_commit:raise Fault(502,'ambiguous_committed')
            return result
    def telegram(self,text):return self.turn({**self.binding,'requestId':str(uuid.uuid4()),'message':text,'channel':'telegram'})
