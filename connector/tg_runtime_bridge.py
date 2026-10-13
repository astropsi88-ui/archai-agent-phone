"""Example to mount INSIDE an existing TG runtime. No polling bot, no shell.
Prerequisite: facade methods describe/history/turn reuse existing owner mapping,
canonical conversation, memory, history, durable idempotency and cancellation.
Do not import a bot module that starts a second process. See docs/02_CONNECTOR.md.
"""
import hmac
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from contract import CallableAdapter,Fault

def make_bridge(existing_service, *, agent_id, conversation_id, owner_id, token, port=8766):
    if not token or len(token)<24:raise ValueError('Private connector token required')
    adapter=CallableAdapter(existing_service,agent_id,conversation_id,owner_id)
    adapter.describe()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            status=200
            self.connection.settimeout(10)
            try:
                if self.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}'):raise Fault(403,'host_mismatch')
                if self.headers.get('Origin'):raise Fault(403,'server_to_server_only')
                if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):raise Fault(401,'connector_auth_required')
                if self.headers.get('Content-Type')!='application/json':raise Fault(415,'json_required')
                n=int(self.headers.get('Content-Length','0'))
                if self.headers.get('Transfer-Encoding') or not 0<n<=16384:raise Fault(413,'body_size')
                p=json.loads(self.rfile.read(n))
                if not isinstance(p,dict):raise Fault(400,'invalid_body')
                if any(p.get(k)!=v for k,v in adapter.identity.items()):raise Fault(403,'binding_mismatch')
                op=self.path.removeprefix('/connector/')
                if self.path!='/connector/'+op or op not in ('describe','history','turn'):raise Fault(404,'not_found')
                if op=='turn':
                    import threading,time
                    from voice import valid_id
                    valid_id(p.get('requestId'))
                    if not isinstance(p.get('message'),str) or not 1<=len(p['message'])<=2000 or p.get('channel') not in ('phone-voice','phone-text'):raise Fault(400,'invalid_turn')
                    cancel=threading.Event();timer=threading.Timer(15,cancel.set);timer.daemon=True;timer.start()
                    try:result=adapter.turn(p['message'],p['requestId'],p['channel'],cancel,time.monotonic()+15)
                    finally:timer.cancel()
                else:result=getattr(adapter,op)()
                # Return only allowed public fields plus server binding; never raw runtime internals.
                result={**result,'ownerId':owner_id}
            except Fault as e:status,result=e.status,{'error':e.code}
            except Exception:status,result=500,{'error':'runtime_bridge_failed'}
            raw=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
    http=ThreadingHTTPServer(('127.0.0.1',port),Handler);http.daemon_threads=True
    return http

# In the EXISTING process, AFTER runtime initialization (owner supplies real facade):
# bridge = make_bridge(existing_service, agent_id=EXISTING_ID,
#     conversation_id=EXISTING_CONVERSATION, owner_id=VERIFIED_OWNER, token=PRIVATE_TOKEN)
# threading.Thread(target=bridge.serve_forever, daemon=True).start()
# Async TG runtime: facade schedules onto its existing event loop with a bounded wait.
# Never block that event loop; never call asyncio.run() on a new runtime.
