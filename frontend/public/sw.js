/**
 * MyGarage Service Worker
 * Provides offline capabilities and caching for PWA functionality
 */

const CACHE_NAME = 'mygarage-v2';
const RUNTIME_CACHE = 'mygarage-runtime-v1';
const OFFLINE_URL = '/offline.html';
const PREFETCH_URLS = [
  '/api/vehicles?limit=25',
  '/api/dashboard',
];

// Assets to cache on install
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  OFFLINE_URL,
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const staticCache = await caches.open(CACHE_NAME);
      await staticCache.addAll(STATIC_ASSETS);

      const runtimeCache = await caches.open(RUNTIME_CACHE);
      await Promise.all(
        PREFETCH_URLS.map(async (url) => {
          try {
            const response = await fetch(url);
            if (response && response.ok) {
              await runtimeCache.put(url, response.clone());
            }
          } catch (error) {
            console.warn('[PWA] Prefetch skipped:', url, error);
          }
        })
      );
    })()
  );
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME && name !== RUNTIME_CACHE)
          .map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Navigation requests - provide offline fallback
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => {
        const cache = await caches.open(CACHE_NAME);
        const offlinePage = await cache.match(OFFLINE_URL);
        return offlinePage || caches.match('/index.html');
      })
    );
    return;
  }

  // API requests - network first, cache fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Clone response to cache it
          const responseClone = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => {
            cache.put(request, responseClone);
          });
          return response;
        })
        .catch(() => {
          // Return cached version if offline
          return caches.match(request).then((cached) => {
            if (cached) {
              return cached;
            }
            // Return offline fallback for API
            return new Response(
              JSON.stringify({ error: 'Offline - data unavailable' }),
              {
                headers: { 'Content-Type': 'application/json' },
                status: 503,
              }
            );
          });
        })
    );
    return;
  }

  // Static assets - cache first, network fallback
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached;
      }

      return fetch(request)
        .then((response) => {
          // Don't cache non-successful responses
          if (!response || response.status !== 200 || response.type !== 'basic') {
            return response;
          }

          // Clone and cache the response
          const responseClone = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => {
            cache.put(request, responseClone);
          });

          return response;
        })
        .catch(() => {
          return new Response('Offline', { status: 503 });
        });
    })
  );
});

// Listen for messages from the app
self.addEventListener('message', (event) => {
  // SECURITY: Validate message origin to prevent XSS and message spoofing (CWE-20291)
  // Only accept messages from same origin (the app itself)
  if (event.origin !== self.location.origin) {
    console.warn('[PWA Security] Rejected postMessage from unauthorized origin:', event.origin);
    return;
  }

  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
