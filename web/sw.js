// Security Site Designer — offline app shell for static hosting (created by Brad Hall).
// Works under any sub-path (e.g. GitHub Pages /repo/). Pages: network first, cached copy when offline.
const CACHE = 'ssd-static-v3';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icon.svg', './icon-192.png', './icon-512.png'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('ssd-static') && k !== CACHE && k !== CACHE + '-libs').map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  if (e.request.method === 'GET' && /^(cdnjs\.cloudflare\.com|cdn\.jsdelivr\.net|unpkg\.com)$/.test(new URL(e.request.url).hostname)) { e.respondWith(caches.open(CACHE + '-libs').then(c => c.match(e.request).then(m => m || fetch(e.request).then(r => { if (r.ok || r.type === 'opaque') c.put(e.request, r.clone()); return r; })))); return; } // PDF/Excel/3D libraries: kept after first use so exports work offline on site
  const u = new URL(e.request.url); if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  const scope = new URL(self.registration.scope);
  if (e.request.mode === 'navigate') { e.respondWith(fetch(e.request).then(r => { if (r.ok) { const c = r.clone(); caches.open(CACHE).then(cc => cc.put(scope.href, c)); } return r; }).catch(() => caches.match(scope.href).then(m => m || caches.match(new URL('index.html', scope).href)))); return; }
  e.respondWith(caches.match(e.request).then(m => m || fetch(e.request)));
});
