/**
 * preload.js - 安全桥接层
 * 将主进程能力安全暴露给渲染进程
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // ── 持久化存储（替代 chrome.storage.local）──────────────────────────
  storage: {
    get:    (keys)  => ipcRenderer.invoke('store-get', keys),
    set:    (items) => ipcRenderer.invoke('store-set', items),
    remove: (keys)  => ipcRenderer.invoke('store-remove', keys),
  },

  // ── 窗口控制 ──────────────────────────────────────────────────────────
  minimize:     ()    => ipcRenderer.send('win-minimize'),
  hide:         ()    => ipcRenderer.send('win-close'),
  quit:         ()    => ipcRenderer.send('win-quit'),
  setAlwaysOnTop: (v) => ipcRenderer.send('win-pin', v),
  openExternal: (url) => ipcRenderer.send('open-external', url),
});
