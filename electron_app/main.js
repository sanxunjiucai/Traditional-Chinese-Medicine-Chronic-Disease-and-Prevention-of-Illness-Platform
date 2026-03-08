/**
 * main.js - Electron 主进程
 * 治未病·诊中助手 桌面版
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');

// 单实例锁：防止多开
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
}

let mainWindow = null;
let tray = null;
let isQuiting = false;

// ─── 持久化存储（JSON文件）───────────────────────────────────────────────────

const STORE_PATH = path.join(app.getPath('userData'), 'config.json');

function readStore() {
  try {
    if (fs.existsSync(STORE_PATH)) {
      return JSON.parse(fs.readFileSync(STORE_PATH, 'utf-8'));
    }
  } catch (_) {}
  return {};
}

function writeStore(data) {
  try {
    fs.writeFileSync(STORE_PATH, JSON.stringify(data, null, 2), 'utf-8');
  } catch (_) {}
}

// ─── IPC：存储代理 ──────────────────────────────────────────────────────────

ipcMain.handle('store-get', (_event, keys) => {
  const store = readStore();
  if (!keys) return store;
  const result = {};
  const arr = Array.isArray(keys) ? keys : [keys];
  for (const k of arr) result[k] = store[k];
  return result;
});

ipcMain.handle('store-set', (_event, items) => {
  const store = readStore();
  Object.assign(store, items);
  writeStore(store);
  return true;
});

ipcMain.handle('store-remove', (_event, keys) => {
  const store = readStore();
  const arr = Array.isArray(keys) ? keys : [keys];
  for (const k of arr) delete store[k];
  writeStore(store);
  return true;
});

// ─── IPC：窗口控制 ──────────────────────────────────────────────────────────

ipcMain.on('win-minimize',  () => mainWindow?.minimize());
ipcMain.on('win-close',     () => { isQuiting = false; mainWindow?.hide(); });
ipcMain.on('win-quit',      () => { isQuiting = true;  app.quit(); });
ipcMain.on('win-pin',       (_e, pin) => mainWindow?.setAlwaysOnTop(pin, 'floating'));
ipcMain.on('open-external', (_e, url) => shell.openExternal(url));

// ─── 窗口创建 ─────────────────────────────────────────────────────────────

function createWindow() {
  const store = readStore();

  mainWindow = new BrowserWindow({
    width:  store.winWidth  || 420,
    height: store.winHeight || 780,
    x: store.winX,
    y: store.winY,
    minWidth:  380,
    minHeight: 500,
    frame: false,           // 自定义标题栏
    transparent: false,
    resizable: true,
    skipTaskbar: false,
    alwaysOnTop: store.alwaysOnTop || false,
    backgroundColor: '#F7F5F0',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    title: '治未病·诊中助手',
  });

  mainWindow.loadFile(path.join(__dirname, 'src', 'index.html'));

  // 保存窗口位置/尺寸
  function saveWinState() {
    if (!mainWindow || mainWindow.isMinimized()) return;
    const [w, h] = mainWindow.getSize();
    const [x, y] = mainWindow.getPosition();
    const s = readStore();
    writeStore({ ...s, winWidth: w, winHeight: h, winX: x, winY: y });
  }

  mainWindow.on('resize',   saveWinState);
  mainWindow.on('moved',    saveWinState);
  mainWindow.on('close', (e) => {
    if (!isQuiting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  // 开发调试
  if (process.env.NODE_ENV === 'dev') {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

// ─── 托盘图标 ─────────────────────────────────────────────────────────────

function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'icon.ico');
  const icon = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath)
    : nativeImage.createEmpty();

  tray = new Tray(icon);
  tray.setToolTip('治未病·诊中助手');

  const menu = Menu.buildFromTemplate([
    { label: '显示窗口',   click: () => { mainWindow?.show(); mainWindow?.focus(); } },
    { type: 'separator' },
    { label: '退出程序',   click: () => { isQuiting = true; app.quit(); } },
  ]);

  tray.setContextMenu(menu);
  tray.on('click', () => {
    if (mainWindow?.isVisible()) {
      mainWindow.focus();
    } else {
      mainWindow?.show();
    }
  });
}

// ─── 应用生命周期 ────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  createWindow();
  createTray();
});

// 第二个实例启动时，聚焦已有窗口
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

app.on('before-quit', () => { isQuiting = true; });
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
