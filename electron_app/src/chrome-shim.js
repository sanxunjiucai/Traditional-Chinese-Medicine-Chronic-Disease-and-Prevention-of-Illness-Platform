/**
 * chrome-shim.js — Chrome Extension API Polyfill for Electron
 *
 * Maps chrome.* APIs used by background.js and content.js to:
 *   - window.electronAPI.storage  (persistent config via main-process IPC)
 *   - An in-memory message bus    (replaces chrome.runtime / chrome.tabs messaging)
 *
 * Load ORDER matters:
 *   1. chrome-shim.js   (this file, via <script> in index.html)
 *   2. background.js    (injected by main.js after did-finish-load)
 *   3. content.js       (injected by main.js after background.js)
 */

(function () {
  'use strict';

  // ── In-process message bus ──────────────────────────────────────────────────
  //
  // Both background.js and content.js are loaded into the SAME renderer window.
  // chrome.runtime.sendMessage / onMessage / tabs.sendMessage all route through
  // this shared listener array instead of the real Chrome message passing infra.

  const _listeners = [];

  /**
   * Dispatch a message to all registered onMessage listeners.
   * Returns a Promise that resolves with the first sendResponse() value.
   */
  function _dispatch(message, sender) {
    return new Promise((resolve) => {
      let settled = false;
      let asyncPending = 0;

      function sendResponse(result) {
        if (!settled) { settled = true; resolve(result); }
      }

      for (const fn of [..._listeners]) {
        let ret;
        try { ret = fn(message, sender || { tab: { id: 0 } }, sendResponse); }
        catch (e) { console.warn('[chrome-shim] listener threw:', e); continue; }
        // Return value === true means the listener will call sendResponse async
        if (ret === true) asyncPending++;
      }

      // No listener claimed async response → resolve immediately
      if (!settled && asyncPending === 0) resolve(undefined);
    });
  }

  // ── chrome.storage.local ────────────────────────────────────────────────────

  const _storageLocal = {
    /**
     * keys: string | string[] | object (with defaults) | null (= get all)
     * cb:   function(result)
     */
    get(keys, cb) {
      let keyList;
      let defaults = {};

      if (keys == null) {
        // Return the full store
        window.electronAPI.storage.get(null)
          .then(r => cb && cb(r || {}))
          .catch(() => cb && cb({}));
        return;
      }

      if (typeof keys === 'string')        { keyList = [keys]; }
      else if (Array.isArray(keys))        { keyList = keys; }
      else if (typeof keys === 'object')   { keyList = Object.keys(keys); defaults = { ...keys }; }
      else                                 { keyList = []; }

      window.electronAPI.storage.get(keyList)
        .then(result => {
          const out = { ...defaults };
          if (result) {
            for (const k of keyList) {
              if (result[k] !== undefined) out[k] = result[k];
            }
          }
          cb && cb(out);
        })
        .catch(() => cb && cb({ ...defaults }));
    },

    /** items: { key: value, ... } */
    set(items, cb) {
      window.electronAPI.storage.set(items)
        .then(() => cb && cb())
        .catch(() => cb && cb());
    },

    /** keys: string | string[] */
    remove(keys, cb) {
      const ks = Array.isArray(keys) ? keys : [keys];
      window.electronAPI.storage.remove(ks)
        .then(() => cb && cb())
        .catch(() => cb && cb());
    },
  };

  // ── chrome.runtime ──────────────────────────────────────────────────────────

  const _runtime = {
    lastError: null,
    id: 'electron-tcm-shim',

    sendMessage(message, cb) {
      _dispatch(message, null).then(result => cb && cb(result));
    },

    onMessage: {
      addListener(fn)    { _listeners.push(fn); },
      removeListener(fn) { const i = _listeners.indexOf(fn); if (i >= 0) _listeners.splice(i, 1); },
      hasListeners()     { return _listeners.length > 0; },
    },
  };

  // ── chrome.tabs ─────────────────────────────────────────────────────────────

  const _tabs = {
    /** Simulate one active "tab" (the Electron window itself) */
    query(_opts, cb) {
      if (cb) cb([{ id: 0, url: window.location.href, active: true }]);
    },

    /**
     * In Chrome: sends to a content script in the given tab.
     * In Electron: same process → route through the in-memory bus so that
     * content.js onMessage listeners (e.g. agentProgress) receive it.
     */
    sendMessage(_tabId, message, cb) {
      _dispatch(message, { tab: { id: 0 } }).then(r => cb && cb(r));
    },

    /** Open external URLs (e.g. for links opened from the sidebar) */
    create(props) {
      if (props?.url) window.electronAPI.openExternal(props.url);
    },
  };

  // ── chrome.scripting ────────────────────────────────────────────────────────

  const _scripting = {
    executeScript: () => Promise.resolve([]),
  };

  // ── Publish as window.chrome ─────────────────────────────────────────────────

  window.chrome = {
    storage:   { local: _storageLocal },
    runtime:   _runtime,
    tabs:      _tabs,
    scripting: _scripting,
  };

  console.log('[chrome-shim] Chrome API polyfill ready (Electron mode)');
})();
