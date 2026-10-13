"""Neutral facade to an EXISTING runtime. No model, personality or history store."""
import json
import threading
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

class Fault(Exception):
    def __init__(self, status, code): self.status, self.code = status, code

class BoundAdapter:
    def __init__(self, agent_id, conversation_id, owner_id):
        if not all(isinstance(v, str) and 0 < len(v) <= 200 for v in (agent_id, conversation_id, owner_id)):
            raise ValueError('needs_human: configure existing agent/conversation/owner mapping')
        self.identity = dict(agentId=agent_id, conversationId=conversation_id, ownerId=owner_id)

    def payload(self, **extra): return {**extra, **self.identity}

    def validate(self, result):
        if not isinstance(result, dict) or any(result.get(k) != v for k,v in self.identity.items()):
            raise Fault(502, 'existing_agent_identity_mismatch')
        return result

    def public(self, result):
        self.validate(result)
        out = {k: result[k] for k in ('agentId', 'conversationId')}
        if 'messages' in result:
            if not isinstance(result['messages'], list) or len(result['messages']) > 100: raise Fault(502, 'history_limit')
            out['messages'] = [self.message(m) for m in result['messages']]
        if 'message' in result: out['message'] = self.message(result['message'])
        if 'replayed' in result: out['replayed'] = bool(result['replayed'])
        return out

    @staticmethod
    def message(m):
        if (not isinstance(m,dict) or not isinstance(m.get('id'),str) or not 1 <= len(m['id']) <= 200
            or m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str)
            or len(m['content']) > 12000): raise Fault(502, 'invalid_existing_message')
        return {k:m[k] for k in ('id','role','content')}

    def describe(self): return self.public(self.call('describe', self.payload()))
    def history(self): return self.public(self.call('history', self.payload(limit=100)))
    def turn(self, text, request_id, channel, cancel, deadline):
        if cancel.is_set(): raise Fault(409, 'turn_cancelled')
        result = self.call('turn', self.payload(message=text, requestId=request_id, channel=channel), cancel, deadline)
        return self.public(result)

class CallableAdapter(BoundAdapter):
    """service is a facade of the already running agent, never a new agent factory.
    Methods accept payload; turn additionally receives cancel Event/deadline monotonic.
    Existing runtime MUST enforce mapping, durable deduplication and canonical commit.
    """
    def __init__(self, service, *identity): super().__init__(*identity); self.service = service
    def call(self, operation, payload, cancel=None, deadline=None):
        fn = getattr(self.service, operation)
        result = fn(payload, cancel=cancel, deadline=deadline) if operation == 'turn' else fn(payload)
        return self.validate(result)

class HTTPAdapter(BoundAdapter):
    def __init__(self, url, token, *identity, timeout=15):
        super().__init__(*identity)
        p=urlsplit(url)
        if p.scheme not in ('http','https') or not p.netloc or p.username or p.query or p.fragment or p.path not in ('','/'):
            raise ValueError('Agent URL must be a trusted origin')
        if p.scheme=='http' and p.hostname not in ('localhost','127.0.0.1'): raise ValueError('Agent requires TLS or loopback')
        if not token: raise ValueError('needs_human: configure server-side connector token')
        self.url,self.token,self.timeout=url.rstrip('/'),token,timeout

    def call(self, operation, payload, cancel=None, deadline=None):
        import time
        timeout=self.timeout if deadline is None else min(self.timeout,max(.01,deadline-time.monotonic()))
        req=Request(self.url+'/connector/'+operation,json.dumps(payload).encode(),
            {'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method='POST')
        try:
            # No redirects: avoid forwarding bearer credentials to a different endpoint.
            from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs): return None
            handlers = [NoRedirect()]
            if urlsplit(self.url).hostname in ('localhost', '127.0.0.1'):
                handlers.append(ProxyHandler({}))
            with build_opener(*handlers).open(req,timeout=timeout) as res: raw=res.read(262145)
            if len(raw)>262144: raise ValueError()
            return self.validate(json.loads(raw))
        except Fault: raise
        except Exception: raise Fault(502,'existing_agent_unavailable_refresh_history_no_auto_retry') from None

class Unconfigured(BoundAdapter):
    def __init__(self): self.identity={}
    def call(self,*args,**kwargs): raise Fault(503,'needs_human_existing_agent_adapter')
