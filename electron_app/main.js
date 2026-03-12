/**
 * main.js - Electron Main Process
 * 治未病·诊中助手 桌面版（Chrome 插件 Electron 封装）
 *
 * Architecture:
 *   index.html  — minimal shell; loads chrome-shim.js synchronously
 *   background.js — Chrome extension service-worker logic (injected after load)
 *   content.js    — Sidebar UI (injected after background.js)
 *   sidebar.css   — Sidebar styles (inserted after load)
 *
 * Chrome API shim (chrome-shim.js) maps:
 *   chrome.storage.local  →  electronAPI.storage  (IPC to main process)
 *   chrome.runtime.*      →  in-memory message bus (background ↔ content, same renderer)
 *   chrome.tabs.*         →  in-memory bus + openExternal
 */

const {
  app, BrowserWindow, Tray, Menu, nativeImage, shell, ipcMain, protocol, net,
} = require('electron');
const path = require('path');
const fs   = require('fs');

// Register app:// as a secure, standard scheme so Web Speech API works
// Must be called BEFORE app is ready
protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, bypassCSP: false, supportFetchAPI: true, corsEnabled: true } },
]);

// ── Single-instance lock ──────────────────────────────────────────────────────

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) { app.quit(); process.exit(0); }

let mainWindow = null;
let tray       = null;
let isQuiting  = false;

// ── Persistent config (JSON file) ─────────────────────────────────────────────

const STORE_PATH = path.join(app.getPath('userData'), 'config.json');

function readStore() {
  try {
    if (fs.existsSync(STORE_PATH)) return JSON.parse(fs.readFileSync(STORE_PATH, 'utf-8'));
  } catch (_) {}
  return {};
}

function writeStore(data) {
  try { fs.writeFileSync(STORE_PATH, JSON.stringify(data, null, 2), 'utf-8'); } catch (_) {}
}

// ── IPC: storage proxy ────────────────────────────────────────────────────────

ipcMain.handle('store-get', (_e, keys) => {
  const store = readStore();
  if (!keys) return store;
  const result = {};
  const arr = Array.isArray(keys) ? keys : [keys];
  for (const k of arr) result[k] = store[k];
  return result;
});

ipcMain.handle('store-set', (_e, items) => {
  const store = readStore();
  Object.assign(store, items);
  writeStore(store);
  return true;
});

ipcMain.handle('store-remove', (_e, keys) => {
  const store = readStore();
  const arr = Array.isArray(keys) ? keys : [keys];
  for (const k of arr) delete store[k];
  writeStore(store);
  return true;
});

// ── IPC: window controls ──────────────────────────────────────────────────────

ipcMain.on('win-minimize',  ()         => mainWindow?.minimize());
ipcMain.on('win-close',     ()         => { isQuiting = false; mainWindow?.hide(); });
ipcMain.on('win-quit',      ()         => { isQuiting = true;  app.quit(); });
ipcMain.on('win-pin',       (_e, pin)  => mainWindow?.setAlwaysOnTop(pin, 'floating'));
ipcMain.on('open-external', (_e, url)  => shell.openExternal(url));

// ── Resolve Chrome extension file paths ───────────────────────────────────────

/**
 * In dev:        files live in   ../chrome_extension/  (relative to this main.js)
 * In production: files are copied to  process.resourcesPath/  via extraResources
 */
function extFilePath(filename) {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, filename);
  }
  return path.join(__dirname, '..', 'chrome_extension', filename);
}

function readExtFile(filename) {
  const p = extFilePath(filename);
  try {
    return fs.readFileSync(p, 'utf-8');
  } catch (err) {
    console.error(`[main] Cannot read extension file "${filename}" from "${p}":`, err.message);
    return '';
  }
}

// ── Inject Chrome extension into renderer after page load ─────────────────────

async function injectExtension(win) {
  const wc = win.webContents;

  // 1. Load extension CSS and inject
  const sidebarCss = readExtFile('sidebar.css');
  if (sidebarCss) {
    await wc.insertCSS(sidebarCss).catch(e => console.warn('[main] insertCSS error:', e));
  }

  // 2. Electron-specific CSS overrides (appended after sidebar.css)
  //    - Expand sidebar to fill the window
  //    - Make .tcm-header draggable
  await wc.insertCSS(`
    /* ── Electron window overrides ── */
    #tcm-assistant-sidebar {
      position: fixed !important;
      inset: 0 !important;
      width:  100% !important;
      height: 100% !important;
      max-width: none !important;
      min-width: unset !important;
      transform: translateX(0) !important;
      border-radius: 0 !important;
      border-left:   none !important;
      box-shadow:    none !important;
    }
    #tcm-assistant-sidebar.tcm-collapsed {
      transform: none !important;
      width: 100% !important;
    }
    .tcm-resize-handle, .tcm-collapsed-tab { display: none !important; }
    .tcm-header {
      -webkit-app-region: drag !important;
      min-height: 44px !important;
      cursor: default !important;
    }
    .tcm-header button,
    .tcm-header input,
    .tcm-header a,
    .tcm-header-right,
    .tcm-header-patient-name { -webkit-app-region: no-drag !important; }
  `).catch(e => console.warn('[main] insertCSS (overrides) error:', e));

  // 3. Mark Electron context before loading extension scripts
  await wc.executeJavaScript('window.__ELECTRON__ = true;').catch(() => {});

  // 4. Load background.js (registers chrome.runtime.onMessage handlers)
  const bgCode = readExtFile('background.js');
  if (bgCode) {
    await wc.executeJavaScript(bgCode).catch(e =>
      console.error('[main] background.js execution error:', e.message)
    );
  }

  // 5. Load content.js (creates sidebar DOM and appends to body)
  const contentCode = readExtFile('content.js');
  if (contentCode) {
    await wc.executeJavaScript(contentCode).catch(e =>
      console.error('[main] content.js execution error:', e.message)
    );
  }

  // 6. Electron-specific wiring: wire sidebar buttons to window controls
  //    Runs after content.js has had a chance to create the DOM.
  await wc.executeJavaScript(`
    (function() {
      // Small delay to let content.js finish its async initialization
      setTimeout(function() {
        // Hide loading indicator
        var loading = document.getElementById('tcm-loading');
        if (loading) loading.style.display = 'none';

        // Collapse button → minimize window; replace icon with standard minimize bar
        var collapseBtn = document.getElementById('tcm-collapse-btn');
        if (collapseBtn) {
          collapseBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="width:14px;height:14px;display:block"><line x1="5" y1="18" x2="19" y2="18"/></svg>';
          collapseBtn.title = '最小化';
          var newBtn = collapseBtn.cloneNode(true);
          collapseBtn.parentNode.replaceChild(newBtn, collapseBtn);
          newBtn.addEventListener('click', function() {
            window.electronAPI.minimize();
          });
        }

        // Dock-toggle button → hide in Electron (no dock/float concept in a dedicated window)
        var dockBtn = document.getElementById('tcm-dock-toggle-btn');
        if (dockBtn) dockBtn.style.display = 'none';

        // Force-expand sidebar: remove collapsed class AND all inline styles that
        // override the Electron full-window CSS (width/top/height/transform set by content.js)
        var sidebar = document.getElementById('tcm-assistant-sidebar');
        if (sidebar) {
          sidebar.classList.remove('tcm-collapsed');
          sidebar.style.removeProperty('top');
          sidebar.style.removeProperty('height');
          sidebar.style.removeProperty('transform');
          sidebar.style.removeProperty('width');
          sidebar.style.removeProperty('right');
          sidebar.style.removeProperty('left');
        }
      }, 300);
    })();
  `).catch(e => console.warn('[main] wiring script error:', e));
}

// ── Create window ─────────────────────────────────────────────────────────────

function createWindow() {
  const store = readStore();

  mainWindow = new BrowserWindow({
    width:  store.winWidth  || 420,
    height: store.winHeight || 820,
    x: store.winX,
    y: store.winY,
    minWidth:  380,
    minHeight: 500,
    frame: false,           // Frameless: .tcm-header acts as drag region
    transparent: false,
    resizable: true,
    skipTaskbar: false,
    alwaysOnTop: store.alwaysOnTop || false,
    backgroundColor: '#F5F2EC',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
    },
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    title: '治未病·诊中助手',
  });

  // Pre-approve microphone for Web Speech API (no OS prompt in Electron)
  mainWindow.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowed = ['media', 'microphone', 'audioCapture'];
    callback(allowed.includes(permission));
  });
  mainWindow.webContents.session.setPermissionCheckHandler((webContents, permission) => {
    const allowed = ['media', 'microphone', 'audioCapture'];
    return allowed.includes(permission);
  });

  // Load via app:// (secure context → Web Speech API works)
  mainWindow.loadURL('app://./index.html');

  // Inject extension files once the page DOM is ready
  mainWindow.webContents.on('did-finish-load', () => {
    injectExtension(mainWindow);
  });

  // Save window position/size on move/resize
  function saveWinState() {
    if (!mainWindow || mainWindow.isMinimized()) return;
    const [w, h] = mainWindow.getSize();
    const [x, y] = mainWindow.getPosition();
    writeStore({ ...readStore(), winWidth: w, winHeight: h, winX: x, winY: y });
  }
  mainWindow.on('resize', saveWinState);
  mainWindow.on('moved',  saveWinState);

  // Close → hide to tray (unless quiting)
  mainWindow.on('close', (e) => {
    if (!isQuiting) { e.preventDefault(); mainWindow.hide(); }
  });

  // Dev tools in development mode
  if (process.env.NODE_ENV === 'dev') {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

// ── System tray ───────────────────────────────────────────────────────────────

function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'icon.ico');
  const icon = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath)
    : nativeImage.createEmpty();

  tray = new Tray(icon);
  tray.setToolTip('治未病·诊中助手');

  const menu = Menu.buildFromTemplate([
    { label: '显示窗口', click: () => { mainWindow?.show(); mainWindow?.focus(); } },
    { type: 'separator' },
    { label: '退出程序', click: () => { isQuiting = true; app.quit(); } },
  ]);

  tray.setContextMenu(menu);
  tray.on('click', () => {
    if (mainWindow?.isVisible()) mainWindow.focus();
    else mainWindow?.show();
  });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  // Serve index.html via app:// so Web Speech API treats it as a secure context
  protocol.handle('app', (req) => {
    const url = new URL(req.url);
    const filePath = path.join(__dirname, 'src', url.pathname === '/' ? 'index.html' : url.pathname);
    return net.fetch('file://' + filePath);
  });

  createWindow();
  createTray();
});

// Bring existing window to front when a second instance is launched
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

app.on('before-quit',       () => { isQuiting = true; });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
