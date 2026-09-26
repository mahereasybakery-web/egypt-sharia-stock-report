// EGX Sharia Portal - Advanced PWA Service Worker v8.7
const CACHE_NAME = 'egx-sharia-v8.7';
const STATIC_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './market_data.json',
  './icon-192.png',
  './icon-512.png'
];

// Install Event: Pre-cache core shell assets and skip waiting immediately
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] Pre-caching core PWA shell v7.2');
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

// Fetch Event: Network-First for HTML/Data to ensure immediate updates, Cache-First for static media
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
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
        }
        return networkResponse;
      }).catch(async () => {
        // Fallback to cache only if device is offline
        const cached = await caches.match(event.request);
        return cached || caches.match('./index.html');
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
      return caches.match('./index.html');
    })
  );
});
