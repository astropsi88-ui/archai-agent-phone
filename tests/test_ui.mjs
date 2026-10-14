// Real public JS in a synthetic DOM/API/audio VM; no browser/provider/live model.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
const html=readFileSync(new URL('../connector/public/index.html',import.meta.url),'utf8');
const script=html.match(/src="(\/app\.[a-f0-9]+\.js)"/)[1];
const code=readFileSync(new URL('../connector/public'+script,import.meta.url),'utf8');
assert.equal(code,readFileSync(new URL('../connector/public/app.js',import.meta.url),'utf8'));
let checks=0;function check(test){assert.ok(test,'check '+(checks+1));checks++;}
async function fixture(prefs={voice:true,signal:true}){
 const elements=new Map(),requests=[],files=new Map(),messages=[],listeners=new Map();let audioPlays=0,signals=0,turn=null,lostChunk=false,recordProcessor;
 function element(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,checked:false,files:[],handlers:new Map(),addEventListener(t,fn){this.handlers.set(t,fn);},replaceChildren(...v){this.children=v;}});return elements.get(id);}
 class AudioContext {constructor(){this.state='running';this.sampleRate=16000;this.currentTime=0;this.destination={};}async resume(){this.state='running';}async decodeAudioData(){return {};}createBufferSource(){return {connect(){},stop(){},start(){audioPlays++;}};}createOscillator(){return {frequency:{value:0},connect(){},start(){signals++;},stop(){}};}createGain(){return {gain:{value:0},connect(){},disconnect(){}};}createMediaStreamSource(){return {connect(){},disconnect(){}};}createScriptProcessor(){recordProcessor={connect(){},disconnect(){}};return recordProcessor;}}
 const storage=new Map([['phone-audio-preferences',JSON.stringify(prefs)]]);
 const context={console,crypto:webcrypto,setTimeout,clearTimeout,AbortController,URL,Uint8Array,Float32Array,ArrayBuffer,DataView,Blob,btoa:s=>Buffer.from(s,'binary').toString('base64'),localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},document:{hidden:false,getElementById:element,createElement:()=>({}),addEventListener:(t,fn)=>listeners.set(t,fn)},navigator:{onLine:true,mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}},window:{AudioContext,addEventListener:(t,fn)=>listeners.set(t,fn)}};
 context.fetch=async(path,options={})=>{
  const p=options.body?JSON.parse(options.body):null;requests.push({path,method:options.method||'GET',body:p});let status=200,result={};
  if(path==='/api/session')result={agentId:'synthetic-agent',conversationId:'synthetic-conversation',voiceEnabled:true,attachments:true,mockVoice:true};
  else if(path==='/api/history')result={agentId:'synthetic-agent',conversationId:'synthetic-conversation',messages};
  else if(path==='/api/files/begin'){files.set(p.uploadId,{offset:0,status:'uploading'});result={uploadId:p.uploadId,...files.get(p.uploadId)};}
  else if(path==='/api/files/chunk'){files.get(p.uploadId).offset+=Buffer.from(p.base64,'base64').length;result={uploadId:p.uploadId,...files.get(p.uploadId)};if(lostChunk){lostChunk=false;throw Error('lost_after_commit');}}
  else if(path==='/api/files/finish'){const state=files.get(p.uploadId);state.status='ready';result={uploadId:p.uploadId,fileId:p.uploadId,...state,sha256:'a'.repeat(64)};}
  else if(path.startsWith('/api/files/')){const id=path.split('/').pop();if(!files.has(id))status=404;else result={uploadId:id,...files.get(id),fileId:id};}
  else if(path==='/api/turn'){turn={requestId:p.requestId,status:'done',mock:true,...(p.replyVoice?{audioUrl:'/api/turn/'+p.requestId+'/audio'}:{})};messages.push({id:'synthetic-reply-'+messages.length,role:'assistant',content:'synthetic answer'});result={requestId:p.requestId,status:'queued'};}
  else if(path.endsWith('/audio'))return {ok:true,arrayBuffer:async()=>new ArrayBuffer(4)};
  else if(path.startsWith('/api/turn/'))result=turn;
  return {ok:status===200,status,json:async()=>result};
 };
 vm.runInNewContext(code,context);await new Promise(r=>setImmediate(r));
 return {element,requests,files,listeners,storage,context,setLostChunk:()=>lostChunk=true,get audioPlays(){return audioPlays;},get signals(){return signals;},get processor(){return recordProcessor;},async event(id,type='click'){await element(id).handlers.get(type)({preventDefault(){}});},select(text='public fixture',name='file.txt'){const file=new Blob([text]);file.name=name;element('files').files=[file];return this.event('files','change');}};
}
let f=await fixture();await f.select();await f.event('compose','submit');
if(f.audioPlays!==1)console.error({requests:f.requests,status:f.element('status').textContent,phase:f.element('phase').textContent});
let post=f.requests.filter(r=>r.path==='/api/turn');check(post.length===1);check(post[0].body.message==='');check(post[0].body.fileIds.length===1);check(f.audioPlays===1);check(f.signals===1);check(!f.element('phase').textContent.includes(post[0].body.requestId));check(f.element('receipt').textContent.includes(post[0].body.requestId));
await f.event('refresh');await f.event('refresh');check(f.audioPlays===1);check(f.signals===1);check(f.requests.filter(r=>r.path==='/api/turn').length===1);
f=await fixture({voice:false,signal:false});await f.select();f.element('message').value='Summarize this file.';await f.event('compose','submit');post=f.requests.find(r=>r.path==='/api/turn');check(post.body.fileIds.length===1);check(post.body.message==='Summarize this file.');check(post.body.replyVoice===false);check(f.audioPlays===0);check(f.signals===0);
f.element('reply-voice').checked=true;await f.event('reply-voice','change');check(JSON.parse(f.storage.get('phone-audio-preferences')).voice===true);
f=await fixture();await f.select('x'.repeat(2*1024*1024+17));await f.event('compose','submit');const chunks=f.requests.filter(r=>r.path==='/api/files/chunk');check(chunks.length===3);check(chunks.every(r=>Buffer.from(r.body.base64,'base64').length<=1024*1024));check(chunks[1].body.offset===1024*1024);
f=await fixture();await f.select();f.setLostChunk();await f.event('compose','submit');check(f.requests.filter(r=>r.path==='/api/turn').length===0);check(!f.element('send').disabled);const before=f.requests.length;await f.event('refresh');check(f.requests.slice(before).every(r=>r.method==='GET'));await f.event('compose','submit');check(f.requests.filter(r=>r.path==='/api/files/chunk').length===1);check(f.requests.filter(r=>r.path==='/api/turn').length===1);
f=await fixture({voice:false,signal:false});await f.select();await f.event('record');f.processor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(8000)}});check(f.requests.filter(r=>r.path==='/api/turn').length===0);await f.event('stop');post=f.requests.find(r=>r.path==='/api/turn');check(post.body.audio.length>0);check(post.body.fileIds.length===1);check(!('message' in post.body));check(post.body.replyVoice===false);
console.log(JSON.stringify({status:'PASS',checks,scope:'synthetic DOM/API/audio VM; actual public modules',paidCalls:0,realBrowser:false}));
