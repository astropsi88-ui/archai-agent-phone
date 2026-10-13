/* No credential/provider key, no local history, no background POST queue. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let auth=false, binding=null, busy=false, voiceEnabled=false, currentId=null, generation=0;
  let ctx=null, stream=null, input=null, processor=null, silent=null, chunks=[], capture=false, timer=null;
  let source=null, pendingAudio=null, controller=null, pollTimer=null;
  const polling=new Set();
  const note=t=>{$('status').textContent=t;};
  const phase=t=>{$('phase').textContent=t;};
  const controls=()=>{
    $('send').disabled=busy||!auth; $('call').disabled=busy||!auth||!voiceEnabled;
    $('record').disabled=busy||!auth||!voiceEnabled; $('stop').disabled=!capture;
    $('enter').disabled=busy; $('refresh').disabled=!auth; $('logout').disabled=!auth;
  };
  function gate(value){auth=value;$('login').hidden=value;$('room').hidden=!value;if(!value){$('history').replaceChildren();binding=null;$('phone').hidden=true;}controls();}
  async function api(path,body,signal){
    const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal});
    if(!response.ok){const e=new Error('request_failed');e.status=response.status;throw e;}
    return response.json();
  }
  async function refresh(){
    const session=await api('session');binding={agentId:session.agentId,conversationId:session.conversationId};voiceEnabled=session.voiceEnabled;
    $('identity').textContent='Разговор существующего агента подключён';
    $('voice-note').textContent=session.mockVoice?'MOCK: проверка связки. Речь не распознаётся, звук — тихий тестовый сигнал.':'Одна запись — одна реплика вашему агенту. Ответ — синтезированный AI-голос; запросы могут оплачиваться провайдеру.';
    const history=await api('history');
    if(history.agentId!==binding.agentId||history.conversationId!==binding.conversationId)throw new Error('identity_changed');
    $('history').replaceChildren(...history.messages.map(m=>{const li=document.createElement('li');li.className=m.role;li.textContent=m.content;return li;}));gate(true);
  }
  async function connect(){try{await refresh();note('Подключён к вашему агенту.');}catch(e){if(e.status===401){gate(false);note('Войдите своей личной фразой.');}else{gate(false);note('Подключение ещё не настроено или сервер недоступен. Нужна проверка server adapter.');}}}
  // Must be invoked directly on user gesture BEFORE awaiting mic/network.
  function unlock(){if(!ctx)ctx=new (window.AudioContext||window.webkitAudioContext)();return ctx.resume();}
  function stopSound(){if(source){try{source.stop();}catch{}source=null;}pendingAudio=null;$('play').hidden=true;}
  function releaseCapture(){
    clearTimeout(timer);timer=null;capture=false;
    if(processor){processor.onaudioprocess=null;processor.disconnect();processor=null;}
    if(input){input.disconnect();input=null;}if(silent){silent.disconnect();silent=null;}
    if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}
  }
  function encodeWav(samples,rate){
    const length=Math.floor(samples.length*16000/rate),buffer=new ArrayBuffer(44+length*2),v=new DataView(buffer);
    const ascii=(o,s)=>{for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i));};
    ascii(0,'RIFF');v.setUint32(4,36+length*2,true);ascii(8,'WAVE');ascii(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);ascii(36,'data');v.setUint32(40,length*2,true);
    for(let i=0;i<length;i++){
      let sum=0,count=0;const start=Math.floor(i*rate/16000),end=Math.max(start+1,Math.floor((i+1)*rate/16000));
      for(let j=start;j<Math.min(end,samples.length);j++){sum+=samples[j];count++;}
      const s=Math.max(-1,Math.min(1,sum/Math.max(1,count)));v.setInt16(44+i*2,s<0?s*32768:s*32767,true);
    }
    const bytes=new Uint8Array(buffer);let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(binary);
  }
  function wait(ms){return new Promise(resolve=>{pollTimer=setTimeout(resolve,ms);});}
  async function playPending(){
    if(!pendingAudio)return;await unlock();stopSourceOnly();source=ctx.createBufferSource();source.buffer=pendingAudio;source.connect(ctx.destination);source.onended=()=>{source=null;phase('Ответ прозвучал. Можно записать следующую реплику.');};source.start();$('play').hidden=true;
  }
  function stopSourceOnly(){if(source){try{source.stop();}catch{}source=null;}}
  async function checkTurn(id,g){
    if(polling.has(id))return;polling.add(id);
    try {
    const started=Date.now();
    while(g===generation&&id===currentId){
      if(Date.now()-started>125000){await interrupt('Ожидание закончилось. Обновите историю перед новой попыткой.');return;}
      const turn=await api('turn/'+id,undefined,controller?.signal);
      if(g!==generation)return;
      const labels={queued:'Принял реплику',transcribing:'Слушаю запись…',thinking:'Агент думает…',speaking:'Готовлю голос…'};phase(labels[turn.status]||turn.status);
      if(turn.status==='done'){
        await refresh();if(g!==generation)return;
        if(turn.audioUrl){
          const res=await fetch(turn.audioUrl,{credentials:'same-origin',cache:'no-store',signal:controller?.signal});
          if(!res.ok)throw new Error('audio_expired');const buf=await res.arrayBuffer();const decoded=await ctx.decodeAudioData(buf);
          if(g!==generation||document.hidden)return;pendingAudio=decoded;
          if(ctx.state==='running')await playPending();else{$('play').hidden=false;phase('Ответ готов. Нажмите «Послушать».');}
        }
        currentId=null;busy=false;controls();note(turn.mock?'MOCK связка выполнена; настоящая речь не проверялась.':'Ответ получен.');return;
      }
      if(['failed','cancelled','timed_out','unknown_after_restart'].includes(turn.status)){
        currentId=null;busy=false;controls();await refresh();note('Ответ прерван или не подтверждён. История обновлена. Повтор — только новым действием, он может стоить денег.');return;
      }
      await wait(350);
    }
    } finally { polling.delete(id); }
  }
  async function sendTurn(payload){
    const g=generation;busy=true;controller=new AbortController();controls();
    try{
      await api('turn',{...binding,requestId:currentId,...payload},controller.signal);
      if(g!==generation)return;await checkTurn(currentId,g);
    }catch(e){if(g!==generation)return;busy=true;controls();note('Связь потеряна: отправка могла дойти. Нажмите «Проверить ответ» или прервите. Автоповтора нет.');}
  }
  async function interrupt(message='Разговор прерван. Историю можно обновить.'){
    generation++;releaseCapture();chunks=[];stopSound();if(controller)controller.abort();
    const id=currentId;currentId=null;busy=false;controls();phase('Готов к записи');note(message);
    if(id){try{await api('turn/cancel',{requestId:id});}catch{note('Прерывание на сервере не подтверждено. Обновите историю: реплика могла сохраниться.');}}
  }
  async function stopRecord(){
    if(!capture)return; // Recording stop is the ONLY path to submit captured audio, once.
    const count=chunks.reduce((n,c)=>n+c.length,0),samples=new Float32Array(count);let offset=0;
    for(const c of chunks){samples.set(c,offset);offset+=c.length;}chunks=[];const rate=ctx.sampleRate;releaseCapture();controls();
    if(count/rate<.25){currentId=null;busy=false;controls();phase('Запись слишком короткая. Попробуйте ещё раз.');return;}
    await sendTurn({audio:encodeWav(samples.subarray(0,Math.floor(rate*30)),rate)});
  }
  $('login').addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;busy=true;controls();
    try{await api('login',{phrase:$('phrase').value});$('phrase').value='';await refresh();note('На связи.');}catch{note('Вход или подключение не подтверждены. Проверьте фразу и настройки сервера.');}finally{busy=false;controls();}
  });
  $('compose').addEventListener('submit',async e=>{
    e.preventDefault();if(busy||!auth||!$('message').value.trim())return;
    if(!navigator.onLine){note('Нет сети. Сообщение останется на экране и не отправится автоматически.');return;}
    stopSound();generation++;currentId=crypto.randomUUID();const text=$('message').value;$('message').value='';await sendTurn({message:text});
  });
  $('call').addEventListener('click',()=>{if(!auth||busy)return;try{unlock().catch(()=>note('Нажмите запись, чтобы разрешить звук.'));$('phone').hidden=false;stopSound();phase('Готов к записи');}catch{note('Браузер не поддерживает AudioContext.');}});
  $('record').addEventListener('click',async()=>{
    if(busy||!auth||!voiceEnabled)return;generation++;const g=generation;stopSound();currentId=crypto.randomUUID();busy=true;controls();
    try{
      await unlock();const acquired=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
      if(g!==generation||document.hidden){acquired.getTracks().forEach(t=>t.stop());return;}
      stream=acquired;chunks=[];capture=true;input=ctx.createMediaStreamSource(stream);processor=ctx.createScriptProcessor(4096,1,1);silent=ctx.createGain();silent.gain.value=0;
      processor.onaudioprocess=e=>{if(capture){chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));if(chunks.reduce((n,c)=>n+c.length,0)>=ctx.sampleRate*30)stopRecord();}};
      input.connect(processor);processor.connect(silent);silent.connect(ctx.destination);timer=setTimeout(stopRecord,30000);phase('Записываю… не больше 30 секунд');controls();
    }catch{if(g!==generation)return;releaseCapture();currentId=null;busy=false;controls();phase('Нужен микрофон и HTTPS. Проверьте разрешение браузера.');}
  });
  $('stop').addEventListener('click',stopRecord);
  $('interrupt').addEventListener('click',async()=>{await interrupt();$('phone').hidden=true;});
  $('play').addEventListener('click',()=>{playPending().catch(()=>note('Не удалось воспроизвести. Обновите ответ без новой отправки.'));});
  $('refresh').addEventListener('click',async()=>{
    try{await refresh();if(currentId&&!capture){controller=new AbortController();await checkTurn(currentId,generation);}else note('История обновлена.');}catch{note('Пока нет связи. Запрос повторно не отправлял.');}
  });
  $('logout').addEventListener('click',async()=>{await interrupt();try{await api('logout',{});$('message').value='';gate(false);note('Вы вышли.');}catch{note('Выход сервером не подтверждён. Повторите, когда вернётся связь.');}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)interrupt('Приложение ушло в фон: запись и звук остановлены.');});
  window.addEventListener('pagehide',()=>{interrupt();});
  window.addEventListener('offline',()=>{interrupt('Нет сети. История и результат потребуют проверки после подключения.');});
  window.addEventListener('online',()=>{if(!busy)connect();}); // GET only
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
  controls();connect();
})();
