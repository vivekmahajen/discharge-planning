/**
 * Discharge Planning AI — Service Worker
 * Strategy:
 *   - App shell (HTML/CSS/JS) : cache-first, 24 h TTL
 *   - Patient API (/api/patients) : network-first, 8 h TTL, LRU cap 50
 *   - Directory (/api/directory) : cache-first, 24 h TTL
 *   - Auth (/api/auth/) : network-only (never cache)
 *   - SSE streams : network-only (never cache)
 *   - Everything else : network-first, stale-if-error
 *
 * PHI safety:
 *   - On logout the SW receives CLEAR_PATIENT_CACHES and wipes all PHI caches
 *   - Cache TTLs match session TTL (8 h) for patient data
 *   - Never cache 401/403 responses
 *   - Never log raw patient data
 */
"use strict";

const VERSION = "dp-sw-v7";

// Named caches
const CACHE_SHELL   = "dp-shell-v7";
const CACHE_DIR     = "dp-directory-v1";
const CACHE_PATIENT = "dp-patient-";   // prefix — one cache per patient id

const SHELL_TTL_MS   = 24 * 60 * 60 * 1000;
const DIR_TTL_MS     = 24 * 60 * 60 * 1000;
const PATIENT_TTL_MS =  8 * 60 * 60 * 1000;
const MAX_PATIENTS   = 50;

// App-shell assets to precache on install
const SHELL_URLS = [
  "/offline",
  "/static/pwa.js",
  "/static/mobile.css",
  "/static/icons/icon-192x192.png",
  "/static/icons/icon-512x512.png",
];

// IndexedDB for sync queue
const IDB_NAME    = "dp-sync-queue";
const IDB_VERSION = 1;
const IDB_STORE   = "mutations";

// ─────────────────────────── Install ───────────────────────────

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_SHELL).then((cache) =>
      cache.addAll(SHELL_URLS)
    ).then(() => self.skipWaiting())
  );
});

// ─────────────────────────── Activate ──────────────────────────

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      const deletions = keys
        .filter((k) => k !== CACHE_SHELL && k !== CACHE_DIR && !k.startsWith(CACHE_PATIENT))
        .map((k) => caches.delete(k));
      return Promise.all(deletions);
    }).then(() => self.clients.claim())
  );
});

// ─────────────────────────── Fetch ─────────────────────────────

self.addEventListener("fetch", (e) => {
  const { request } = e;
  const url = new URL(request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  // Never intercept auth or stream endpoints
  if (url.pathname.startsWith("/api/auth/")) return;
  if (url.pathname.startsWith("/api/plan/stream")) return;
  if (request.headers.get("Accept") === "text/event-stream") return;

  // Only handle GET (mutations go through sync queue)
  if (request.method !== "GET") return;

  if (url.pathname.startsWith("/api/patients")) {
    e.respondWith(networkFirstPatient(request));
    return;
  }

  if (url.pathname.startsWith("/api/directory")) {
    e.respondWith(cacheFirstDir(request));
    return;
  }

  if (url.pathname.startsWith("/api/milestones/catalog")) {
    e.respondWith(cacheFirstDir(request));
    return;
  }

  if (isShellAsset(url.pathname)) {
    e.respondWith(cacheFirstShell(request));
    return;
  }

  // Default: network-first, stale-if-error
  e.respondWith(networkFirstGeneric(request));
});

// ─────────────────────────── Strategies ────────────────────────

function isShellAsset(pathname) {
  return (
    pathname.startsWith("/static/") ||
    pathname === "/offline" ||
    pathname === "/manifest.json"
  );
}

async function networkFirstPatient(request) {
  const url = new URL(request.url);
  // Extract patient id from path like /api/patients/123 or /api/patients/123/milestones
  const m = url.pathname.match(/\/api\/patients\/(\d+)/);
  const patientId = m ? m[1] : "list";
  const cacheName = CACHE_PATIENT + patientId;

  try {
    const networkResp = await fetchWithTimeout(request.clone(), 10000);
    if (networkResp.ok) {
      const cache = await caches.open(cacheName);
      const stamped = await stampResponse(networkResp.clone(), PATIENT_TTL_MS);
      await cache.put(request, stamped);
      await evictOldestPatientCaches(patientId);
    }
    return networkResp;
  } catch (_) {
    const cached = await getIfFresh(cacheName, request);
    if (cached) return withOfflineHeader(cached);
    return offlineFallback();
  }
}

async function cacheFirstDir(request) {
  const cached = await getIfFresh(CACHE_DIR, request);
  if (cached) return cached;
  try {
    const networkResp = await fetchWithTimeout(request.clone(), 10000);
    if (networkResp.ok) {
      const cache = await caches.open(CACHE_DIR);
      const stamped = await stampResponse(networkResp.clone(), DIR_TTL_MS);
      await cache.put(request, stamped);
    }
    return networkResp;
  } catch (_) {
    return offlineFallback();
  }
}

async function cacheFirstShell(request) {
  const cached = await getIfFresh(CACHE_SHELL, request);
  if (cached) return cached;
  try {
    const networkResp = await fetchWithTimeout(request.clone(), 10000);
    if (networkResp.ok) {
      const cache = await caches.open(CACHE_SHELL);
      const stamped = await stampResponse(networkResp.clone(), SHELL_TTL_MS);
      await cache.put(request, stamped);
    }
    return networkResp;
  } catch (_) {
    const stale = await caches.match(request);
    if (stale) return stale;
    return offlineFallback();
  }
}

async function networkFirstGeneric(request) {
  try {
    return await fetchWithTimeout(request.clone(), 10000);
  } catch (_) {
    const stale = await caches.match(request);
    if (stale) return withOfflineHeader(stale);
    return offlineFallback();
  }
}

// ─────────────────────────── Helpers ───────────────────────────

async function fetchWithTimeout(request, ms) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), ms);
  try {
    const resp = await fetch(request, { signal: controller.signal });
    // Never cache 401/403
    if (resp.status === 401 || resp.status === 403) return resp;
    return resp;
  } finally {
    clearTimeout(tid);
  }
}

async function stampResponse(response, ttlMs) {
  const body = await response.arrayBuffer();
  const headers = new Headers(response.headers);
  headers.set("x-sw-cached-at", Date.now().toString());
  headers.set("x-sw-ttl-ms", ttlMs.toString());
  return new Response(body, { status: response.status, statusText: response.statusText, headers });
}

async function getIfFresh(cacheName, request) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (!cached) return null;
  const cachedAt = parseInt(cached.headers.get("x-sw-cached-at") || "0", 10);
  const ttl = parseInt(cached.headers.get("x-sw-ttl-ms") || "0", 10);
  if (Date.now() - cachedAt > ttl) {
    await cache.delete(request);
    return null;
  }
  return cached;
}

function withOfflineHeader(response) {
  const headers = new Headers(response.headers);
  headers.set("x-sw-offline", "1");
  return response.clone().arrayBuffer().then(
    (body) => new Response(body, { status: response.status, statusText: response.statusText, headers })
  );
}

function offlineFallback() {
  return caches.match("/offline").then(
    (r) => r || new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json", "x-sw-offline": "1" }
    })
  );
}

// LRU eviction: keep only MAX_PATIENTS patient caches
async function evictOldestPatientCaches(currentPatientId) {
  const all = await caches.keys();
  const patientCaches = all.filter((k) => k.startsWith(CACHE_PATIENT));
  if (patientCaches.length <= MAX_PATIENTS) return;

  // Sort by approximate recency using the cache name (newest = current)
  const others = patientCaches.filter((k) => k !== CACHE_PATIENT + currentPatientId);
  // We can't inspect timestamps without opening each cache; delete oldest by position
  const toDelete = others.slice(0, patientCaches.length - MAX_PATIENTS);
  await Promise.all(toDelete.map((k) => caches.delete(k)));
}

// ─────────────────────────── Background Sync ───────────────────

self.addEventListener("sync", (e) => {
  if (e.tag === "dp-mutation-sync") {
    e.waitUntil(replayMutations());
  }
});

async function replayMutations() {
  const db = await openIdb();
  const tx = db.transaction(IDB_STORE, "readwrite");
  const store = tx.objectStore(IDB_STORE);
  const all = await idbGetAll(store);

  for (const item of all) {
    try {
      const resp = await fetch(item.url, {
        method: item.method,
        headers: item.headers || { "Content-Type": "application/json" },
        body: item.body,
        credentials: "same-origin",
      });
      if (resp.ok || resp.status === 409) {
        // 409 Conflict = already applied; either way remove from queue
        await idbDelete(store, item.id);
      }
      // Non-2xx keeps the item for retry
    } catch (_) {
      // Network still offline; leave item queued
    }
  }

  await new Promise((res, rej) => {
    tx.oncomplete = res;
    tx.onerror = () => rej(tx.error);
  });
}

// ─────────────────────────── Message Handler ───────────────────

self.addEventListener("message", (e) => {
  const { type, payload } = e.data || {};
  switch (type) {
    case "SKIP_WAITING":
      self.skipWaiting();
      break;
    case "GET_VERSION":
      e.ports[0]?.postMessage({ version: VERSION });
      break;
    case "CLEAR_PATIENT_CACHES": {
      // Called on logout — wipe all PHI caches
      caches.keys().then((keys) => {
        const phi = keys.filter(
          (k) => k.startsWith(CACHE_PATIENT) || k === CACHE_DIR
        );
        return Promise.all(phi.map((k) => caches.delete(k)));
      }).then(() => e.ports[0]?.postMessage({ ok: true }));
      break;
    }
    case "PREFETCH_PATIENT": {
      const { patientId } = payload || {};
      if (!patientId) break;
      const req = new Request(`/api/patients/${patientId}`, { credentials: "same-origin" });
      networkFirstPatient(req).catch(() => {});
      break;
    }
  }
});

// ─────────────────────────── IndexedDB helpers ─────────────────

function openIdb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, IDB_VERSION);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(IDB_STORE, { keyPath: "id", autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbGetAll(store) {
  return new Promise((resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbDelete(store, id) {
  return new Promise((resolve, reject) => {
    const req = store.delete(id);
    req.onsuccess = resolve;
    req.onerror = () => reject(req.error);
  });
}
