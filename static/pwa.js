/**
 * Discharge Planning AI — PWA utilities (loaded by every page)
 * Responsibilities:
 *   - Register service worker
 *   - Show offline/online banners
 *   - Handle install prompt (30 s Android, 45 s iOS hint)
 *   - Show SW update banner
 *   - Export helpers: prefetchPatientForOffline, isOfflineResponse, getCachedAt
 */
"use strict";

(function () {
  // ─────────────────── Service Worker Registration ───────────────────

  let _swReg = null;

  async function _registerSW() {
    if (!("serviceWorker" in navigator)) return;
    try {
      _swReg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });

      _swReg.addEventListener("updatefound", () => {
        const incoming = _swReg.installing;
        if (!incoming) return;
        incoming.addEventListener("statechange", () => {
          if (incoming.state === "installed" && navigator.serviceWorker.controller) {
            _showUpdateBanner();
          }
        });
      });
    } catch (err) {
      console.warn("[pwa] SW registration failed:", err.message);
    }
  }

  // Reserve / release space at the bottom of the page so a fixed bottom banner
  // never overlaps page content (e.g. action buttons at the end of a report).
  function _reserveBottomSpace(el) {
    try { document.body.style.paddingBottom = ((el && el.offsetHeight) || 56) + "px"; } catch (_) {}
  }
  function _releaseBottomSpace() {
    try { document.body.style.paddingBottom = ""; } catch (_) {}
  }

  // ─────────────────── Online / Offline Banners ──────────────────────

  function _createBanner(id, html, bgColor) {
    const existing = document.getElementById(id);
    if (existing) return existing;
    const div = document.createElement("div");
    div.id = id;
    div.innerHTML = html;
    Object.assign(div.style, {
      position: "fixed",
      top: "0",
      left: "0",
      right: "0",
      zIndex: "99999",
      background: bgColor,
      color: "#fff",
      padding: "10px 16px",
      textAlign: "center",
      fontSize: "14px",
      fontFamily: "system-ui, sans-serif",
      boxShadow: "0 2px 8px rgba(0,0,0,.3)",
      display: "none",
    });
    document.body.prepend(div);
    return div;
  }

  function _initNetworkBanners() {
    const offlineBanner = _createBanner(
      "pwa-offline-banner",
      "&#x1F4F5; You are offline &mdash; showing cached data. Some actions require a connection.",
      "#b34000"
    );
    const onlineBanner = _createBanner(
      "pwa-online-banner",
      "&#x2705; Connection restored.",
      "#1a7a40"
    );

    function showOffline() {
      offlineBanner.style.display = "block";
      onlineBanner.style.display = "none";
    }
    function showOnline() {
      onlineBanner.style.display = "block";
      offlineBanner.style.display = "none";
      setTimeout(() => { onlineBanner.style.display = "none"; }, 4000);
    }

    window.addEventListener("offline", showOffline);
    window.addEventListener("online", () => {
      showOnline();
      // Trigger background sync
      if (_swReg && _swReg.sync) {
        _swReg.sync.register("dp-mutation-sync").catch(() => {});
      }
    });

    if (!navigator.onLine) showOffline();
  }

  // ─────────────────── Disable network-required buttons ─────────────

  function _initOfflineButtons() {
    function _update() {
      document.querySelectorAll("[data-requires-network]").forEach((el) => {
        if (!navigator.onLine) {
          el.setAttribute("disabled", "true");
          if (!el.dataset.offlineTip) {
            const tip = document.createElement("span");
            tip.className = "offline-tip";
            tip.style.cssText = "margin-left:8px;color:#b34000;font-size:12px;";
            tip.textContent = "(unavailable offline)";
            el.dataset.offlineTip = "1";
            el.insertAdjacentElement("afterend", tip);
          }
        } else {
          el.removeAttribute("disabled");
          const tip = el.nextElementSibling;
          if (tip && tip.classList.contains("offline-tip")) tip.remove();
          delete el.dataset.offlineTip;
        }
      });
    }
    window.addEventListener("offline", _update);
    window.addEventListener("online", _update);
    // Wait for DOM to be ready before scanning
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", _update);
    } else {
      _update();
    }
  }

  // ─────────────────── Install Prompt ───────────────────────────────

  let _deferredPrompt = null;

  function _initInstallPrompt() {
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      _deferredPrompt = e;
      setTimeout(_showInstallPrompt, 30000);
    });

    // iOS Safari install hint (no beforeinstallprompt support)
    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const isStandalone = window.matchMedia("(display-mode: standalone)").matches
      || window.navigator.standalone === true;
    if (isIos && !isStandalone && !_hasSeenIosHint()) {
      setTimeout(_showIosHint, 45000);
    }
  }

  function _showInstallPrompt() {
    if (!_deferredPrompt) return;
    if (_hasSeenInstallPrompt()) return;

    const banner = document.createElement("div");
    banner.id = "pwa-install-banner";
    banner.innerHTML = `
      <span>&#x1F3E5; Install <strong>Discharge Planning AI</strong> on your device for offline access.</span>
      <button id="pwa-install-btn" style="margin-left:16px;padding:6px 14px;background:#fff;color:#00529B;border:none;border-radius:4px;font-weight:bold;cursor:pointer;">Install</button>
      <button id="pwa-install-dismiss" style="margin-left:8px;padding:6px 10px;background:transparent;color:#fff;border:1px solid rgba(255,255,255,.6);border-radius:4px;cursor:pointer;">Not now</button>
    `;
    Object.assign(banner.style, {
      position: "fixed",
      bottom: "0",
      left: "0",
      right: "0",
      zIndex: "99998",
      background: "#00529B",
      color: "#fff",
      padding: "14px 20px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexWrap: "wrap",
      gap: "8px",
      fontFamily: "system-ui, sans-serif",
      fontSize: "14px",
      boxShadow: "0 -2px 12px rgba(0,0,0,.3)",
    });
    document.body.appendChild(banner);
    _reserveBottomSpace(banner);

    document.getElementById("pwa-install-btn").addEventListener("click", async () => {
      _deferredPrompt.prompt();
      const { outcome } = await _deferredPrompt.userChoice;
      _markInstallPromptSeen();
      banner.remove();
      _releaseBottomSpace();
      _deferredPrompt = null;
    });
    document.getElementById("pwa-install-dismiss").addEventListener("click", () => {
      _markInstallPromptSeen();
      banner.remove();
      _releaseBottomSpace();
    });
  }

  function _showIosHint() {
    if (_hasSeenIosHint()) return;
    const banner = document.createElement("div");
    banner.id = "pwa-ios-hint";
    banner.innerHTML = `
      <span>&#x1F4F2; Install this app: tap <strong>&#x1F4E4; Share</strong> then <strong>Add to Home Screen</strong></span>
      <button id="pwa-ios-dismiss" style="margin-left:12px;padding:4px 10px;background:transparent;color:#fff;border:1px solid rgba(255,255,255,.6);border-radius:4px;cursor:pointer;">&#x2715;</button>
    `;
    Object.assign(banner.style, {
      position: "fixed",
      bottom: "0",
      left: "0",
      right: "0",
      zIndex: "99998",
      background: "#00529B",
      color: "#fff",
      padding: "14px 20px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: "8px",
      fontFamily: "system-ui, sans-serif",
      fontSize: "14px",
      boxShadow: "0 -2px 12px rgba(0,0,0,.3)",
    });
    document.body.appendChild(banner);
    _reserveBottomSpace(banner);

    document.getElementById("pwa-ios-dismiss").addEventListener("click", () => {
      _markIosHintSeen();
      banner.remove();
      _releaseBottomSpace();
    });
  }

  // ─────────────────── Update Banner ────────────────────────────────

  function _showUpdateBanner() {
    const banner = document.createElement("div");
    banner.id = "pwa-update-banner";
    banner.innerHTML = `
      <span>&#x1F504; A new version of Discharge Planning AI is available.</span>
      <button id="pwa-update-btn" style="margin-left:16px;padding:6px 14px;background:#fff;color:#1a7a40;border:none;border-radius:4px;font-weight:bold;cursor:pointer;">Refresh</button>
    `;
    Object.assign(banner.style, {
      position: "fixed",
      top: "0",
      left: "0",
      right: "0",
      zIndex: "99997",
      background: "#1a7a40",
      color: "#fff",
      padding: "10px 20px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: "8px",
      fontFamily: "system-ui, sans-serif",
      fontSize: "14px",
      boxShadow: "0 2px 8px rgba(0,0,0,.3)",
    });
    document.body.appendChild(banner);

    document.getElementById("pwa-update-btn").addEventListener("click", () => {
      if (_swReg && _swReg.waiting) {
        _swReg.waiting.postMessage({ type: "SKIP_WAITING" });
      }
      window.location.reload();
    });
  }

  // ─────────────────── Public helpers ───────────────────────────────

  /**
   * Ask the SW to cache a patient record for offline use.
   * @param {string|number} patientId
   */
  function prefetchPatientForOffline(patientId) {
    if (!navigator.serviceWorker.controller) return;
    navigator.serviceWorker.controller.postMessage({
      type: "PREFETCH_PATIENT",
      payload: { patientId: String(patientId) },
    });
  }

  /**
   * Returns true if the fetch Response came from the offline SW cache.
   * @param {Response} response
   */
  function isOfflineResponse(response) {
    return response.headers.get("x-sw-offline") === "1";
  }

  /**
   * Returns Date of when this response was cached, or null.
   * @param {Response} response
   */
  function getCachedAt(response) {
    const ts = response.headers.get("x-sw-cached-at");
    return ts ? new Date(parseInt(ts, 10)) : null;
  }

  /**
   * Queue a mutation for background sync (used when offline).
   * @param {string} url
   * @param {string} method  POST|PATCH|DELETE
   * @param {object} body
   */
  async function queueMutation(url, method, body) {
    const db = await _openIdb();
    const tx = db.transaction("mutations", "readwrite");
    tx.objectStore("mutations").add({
      url,
      method,
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      queuedAt: Date.now(),
    });
    await new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
    // Register background sync if supported
    if (_swReg && _swReg.sync) {
      await _swReg.sync.register("dp-mutation-sync").catch(() => {});
    }
  }

  /** Clear all patient PHI caches on logout. */
  async function clearPatientCaches() {
    const ctrl = navigator.serviceWorker.controller;
    if (!ctrl) return;
    return new Promise((resolve) => {
      const { port1, port2 } = new MessageChannel();
      port1.onmessage = resolve;
      ctrl.postMessage({ type: "CLEAR_PATIENT_CACHES" }, [port2]);
      setTimeout(resolve, 2000); // safety timeout
    });
  }

  // Expose on window so pages can call them
  window.PwaUtils = { prefetchPatientForOffline, isOfflineResponse, getCachedAt, queueMutation, clearPatientCaches };

  // ─────────────────── localStorage helpers ─────────────────────────

  function _hasSeenInstallPrompt() { return localStorage.getItem("pwa-install-seen") === "1"; }
  function _markInstallPromptSeen() { localStorage.setItem("pwa-install-seen", "1"); }
  function _hasSeenIosHint() { return localStorage.getItem("pwa-ios-hint-seen") === "1"; }
  function _markIosHintSeen() { localStorage.setItem("pwa-ios-hint-seen", "1"); }

  // ─────────────────── IndexedDB ────────────────────────────────────

  function _openIdb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open("dp-sync-queue", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("mutations", { keyPath: "id", autoIncrement: true });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  // ─────────────────── Logout cache wipe ────────────────────────────

  function _initLogoutHandler() {
    document.addEventListener("click", async (e) => {
      const link = e.target.closest("a[href]");
      if (!link) return;
      if (!link.href.includes("/api/auth/logout")) return;
      e.preventDefault();
      try {
        await clearPatientCaches();
      } finally {
        window.location.href = link.href;
      }
    });
  }

  // ─────────────────── Init ─────────────────────────────────────────

  function _init() {
    _registerSW();
    _initNetworkBanners();
    _initOfflineButtons();
    _initInstallPrompt();
    _initLogoutHandler();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _init);
  } else {
    _init();
  }
})();
