// SW installation/fetch against a synthetic cache/network; not a real warmed phone.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
const dir=new URL('../connector/public/',import.meta.url),html=fs.readFileSync(new URL('index.html',dir),'utf8');
const asset=html.match(/src="(\/app\.[a-f0-9]+\.js)"/)[1];let checks=0;
assert.equal(crypto.createHash('sha256').update(fs.readFileSync(new URL(asset.slice(1),dir))).digest('hex').slice(0,16),asset.match(/app\.([a-f0-9]+)/)[1]);checks++;
const code=fs.readFileSync(new URL('sw.js',dir),'utf8');
async function runtime(missing=false){
 const handlers={},cached=new Map(),deleted=[],stores=new Map([['unrelated-cache',{}],['existing-agent-phone-shell-v2',{}]]);let waiting=false,claimed=false;
 const ctx={URL,self:{location:{origin:'https://synthetic.invalid'},addEventListener:(name,fn)=>handlers[name]=fn,skipWaiting:()=>{waiting=true;},clients:{claim:()=>{claimed=true;}}},fetch:async req=>{const path=typeof req==='string'?req:new URL(req.url).pathname;if(missing&&path===asset)throw Error('missing asset');return 'network:'+path;},caches:{open:async name=>{stores.set(name,{});return {addAll:async paths=>{const values=await Promise.all(paths.map(p=>ctx.fetch(p)));paths.forEach((p,i)=>cached.set(p,values[i]));}};},keys:async()=>[...stores.keys()],delete:async key=>{deleted.push(key);stores.delete(key);},match:async path=>cached.get(path)}};
 vm.runInNewContext(code,ctx);
 return {ctx,handlers,cached,deleted,get waiting(){return waiting;},get claimed(){return claimed;},async event(name){let promise;handlers[name]({waitUntil:p=>promise=p});return promise;}};
}
let r=await runtime();await r.event('install');assert.ok(r.waiting);checks++;assert.ok(r.cached.has(asset));checks++;await r.event('activate');assert.ok(r.claimed);checks++;assert.deepEqual(r.deleted,['existing-agent-phone-shell-v2']);checks++;
r.ctx.fetch=async()=>{throw Error('offline');};let promise;r.handlers.fetch({request:{url:'https://synthetic.invalid'+asset,method:'GET'},respondWith:p=>promise=p});assert.equal(await promise,'network:'+asset);checks++;
for(const [path,method] of [['/api/history','GET'],['/api/turn','POST'],['/api/turn/id/audio','GET'],['/app.js?private=1','GET']]){let intercepted=false;r.handlers.fetch({request:{url:'https://synthetic.invalid'+path,method},respondWith:()=>intercepted=true});assert.equal(intercepted,false);checks++;}
r=await runtime(true);await assert.rejects(r.event('install'));assert.equal(r.waiting,false);checks++;assert.equal(r.cached.size,0);checks++;
console.log(JSON.stringify({status:'PASS',checks,scope:'synthetic SW/cache network and coherent actual hashed module graph',realWarmedBrowser:false}));
