/* Public shell only; credentials, history, audio and API NEVER enter CacheStorage. */
const CACHE='existing-agent-phone-shell-v3';
const SHELL=['/','/app.js','/app.007dec0ba9ecd8f8.js','/style.css','/manifest.webmanifest','/icon-192.png','/icon-512.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>(k.startsWith('existing-agent-phone-shell-')||k.startsWith('learning-agent-shell-'))&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==self.location.origin||u.search||!SHELL.includes(u.pathname))return;e.respondWith(fetch(e.request).catch(()=>caches.match(u.pathname)));});
