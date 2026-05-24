/**
 * MyGarage Service Worker
 * Provides offline capabilities and caching for PWA functionality
 *
 * Cache invalidation: the registering page passes ?v=<app_version> when calling
 * register('/sw.js?v=...'). We read that here so every release gets its own
 * cache buckets, and the `activate` handler deletes stale ones. Without this,
 * a hardcoded cache name silently retains stale shells across deploys, which
 * produces the "white screen on restart" symptom when chunk hashes change.
 */

const SW_URL = new URL(self.location.href);
const SW_VERSION = SW_URL.searchParams.get('v') || 'dev';
const CACHE_NAME = `mygarage-static-${SW_VERSION}`;
const RUNTIME_CACHE = `mygarage-runtime-${SW_VERSION}`;
const OFFLINE_URL = '/offline.html';
const PREFETCH_URLS = [
  '/api/vehicles?limit=25',
  '/api/dashboard',
];

// Precache only immutable shell pieces. Do NOT precache `/` or `/index.html`:
// those are mutable on each deploy and the navigation handler already serves
// them network-first with a cache fallback.
const STATIC_ASSETS = [
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

  // Translation files - network first (same as API) to pick up new versions
  if (url.pathname.startsWith('/locales/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const responseClone = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => {
            cache.put(request, responseClone);
          });
          return response;
        })
        .catch(() => {
          return caches.match(request).then((cached) => {
            if (cached) {
              return cached;
            }
            return new Response(
              JSON.stringify({}),
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

  // API requests - network first, cache fallback.
  //
  // We deliberately do NOT cache:
  //   - Photos/attachments/documents/backup downloads: large binary bodies.
  //     `response.clone()` tees the underlying stream, so the response to
  //     the browser cannot drain faster than the slowest reader — once we
  //     dispatch a cache.put() of a multi-MB blob, the user's image fetch
  //     stalls behind the CacheStorage write. Browser caches these fine
  //     on its own.
  //   - Realtime polling endpoints (livelink/mqtt status): each response is
  //     stale within seconds, so caching just thrashes IndexedDB.
  if (url.pathname.startsWith('/api/')) {
    const shouldCache = !(
      url.pathname.includes('/photos/') ||
      url.pathname.includes('/attachments/') ||
      url.pathname.includes('/documents/') ||
      url.pathname.startsWith('/api/backup/download/') ||
      url.pathname.endsWith('/livelink/status') ||
      url.pathname.endsWith('/mqtt/status')
    );

    event.respondWith(
      fetch(request)
        .then((response) => {
          if (shouldCache && response.ok) {
            const responseClone = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => {
              cache.put(request, responseClone);
            });
          }
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

  // Static assets - cache first, network with retry on failure.
  //
  // The retry is important: if a deploy ships new chunk hashes, the cache
  // is empty for those chunks, and a single network request can fail during
  // the backend's 5-10s cold-start window. Without retry, we'd silently
  // return a 503 — the SPA can't mount and the user sees a white screen
  // with no diagnostic. Three attempts with exponential backoff cover a
  // normal restart; after that, we let the real network error surface so
  // the browser shows it in DevTools instead of swallowing it.
  event.respondWith(
    caches.match(request).then(async (cached) => {
      if (cached) {
        return cached;
      }

      const delays = [0, 500, 1500];
      let lastError;
      for (const delay of delays) {
        if (delay > 0) {
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
        try {
          const response = await fetch(request);
          if (response && response.status === 200 && response.type === 'basic') {
            const responseClone = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        } catch (err) {
          lastError = err;
        }
      }
      throw lastError;
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

  // Proactively cache all translation files for a language
  if (event.data && event.data.type === 'CACHE_LANGUAGE') {
    const lang = event.data.lang;
    if (!lang || lang === 'en') return; // English is bundled inline

    const namespaces = ['common', 'nav', 'settings', 'vehicles', 'forms', 'analytics'];
    const version = event.data.version || '0';

    event.waitUntil(
      caches.open(RUNTIME_CACHE).then((cache) => {
        return Promise.all(
          namespaces.map(async (ns) => {
            const url = `/locales/${lang}/${ns}.json?v=${version}`;
            try {
              const response = await fetch(url);
              if (response && response.ok) {
                await cache.put(url, response.clone());
              }
            } catch (err) {
              // Silently skip — file may not exist yet for this namespace
            }
          })
        );
      })
    );
  }
});
