// EGX Sharia Portal - Advanced PWA Service Worker v18.0 (Audited Indices & Instant Mobile Portfolio)
const CACHE_NAME = 'egx-sharia-v18.1';
const STATIC_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './market_data.json',
  './thndr_verified_capture.jpg',
  './icon-192.png',
  './icon-512.png'
];

// Install Event: Pre-cache core shell assets and skip waiting immediately
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] Pre-caching core PWA shell v13.9');
      return cache.addAll(STATIC_ASSETS);
    })
  );
});

// Activate Event: Delete ALL older caches and claim clients immediately
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keyList) => {
      return Promise.all(
        keyList.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[ServiceWorker] Removing legacy cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Event: Network-First for HTML/Data, Cache-First for static media
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Exclude non-GET and cross-origin external API calls
  if (event.request.method !== 'GET') return;

  // 1. Network-First for HTML and market data (Bypasses stale cache immediately)
  if (url.pathname.endsWith('index.html') || url.pathname.endsWith('/') || url.pathname === '' || url.pathname.endsWith('market_data.json')) {
    event.respondWith(
      fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const resClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            if (url.pathname.endsWith('market_data.json')) {
              cache.put('./market_data.json', resClone);
            } else {
              cache.put(event.request, resClone);
            }
          });
        }
        return networkResponse;
      }).catch(async () => {
        if (url.pathname.endsWith('market_data.json')) {
          const cachedData = await caches.match('./market_data.json');
          if (cachedData) return cachedData;
          return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        const cached = await caches.match(event.request, { ignoreSearch: true });
        if (cached) return cached;
        if (event.request.mode === 'navigate' || (event.request.headers.get('accept') && event.request.headers.get('accept').includes('text/html'))) {
          return caches.match('./index.html');
        }
        return new Response('Network error', { status: 408, headers: { 'Content-Type': 'text/plain' } });
      })
    );
    return;
  }

  // 2. Cache-First strategy for images, icons, fonts
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((response) => {
        if (!response || response.status !== 200 || response.type !== 'basic') {
          return response;
        }
        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseToCache);
        });
        return response;
      });
    }).catch(() => {
      if (event.request.mode === 'navigate' || (event.request.headers.get('accept') && event.request.headers.get('accept').includes('text/html'))) {
        return caches.match('./index.html');
      }
      return new Response('Offline resource not found', { status: 404, headers: { 'Content-Type': 'text/plain' } });
    })
  );
});
