/**
 * preload.js - Secure bridge layer
 * Exposes safe main-process capabilities to the renderer.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {

  // ── Persistent storage (replaces chrome.storage.local) ─────────────────────
  storage: {
    get:    (keys)  => ipcRenderer.invoke('store-get', keys),
    // items must be a plain object { key: value, ... }
    set:    (items) => ipcRenderer.invoke('store-set', items),
    remove: (keys)  => ipcRenderer.invoke('store-remove', keys),
  },

  // ── Window controls ─────────────────────────────────────────────────────────
  minimize:       ()    => ipcRenderer.send('win-minimize'),
  hide:           ()    => ipcRenderer.send('win-close'),
  quit:           ()    => ipcRenderer.send('win-quit'),
  setAlwaysOnTop: (v)   => ipcRenderer.send('win-pin', v),
  openExternal:   (url) => ipcRenderer.send('open-external', url),

  // ── Environment flags ───────────────────────────────────────────────────────
  isElectron: true,
  platform:   process.platform,   // 'win32' | 'darwin' | 'linux'
});
