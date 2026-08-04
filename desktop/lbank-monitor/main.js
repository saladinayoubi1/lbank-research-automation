const { app, BrowserWindow, shell } = require('electron');
const path = require('path');

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 980,
    minHeight: 680,
    show: false,
    backgroundColor: '#06101d',
    autoHideMenuBar: true,
    title: 'LBank Market Monitor',
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#081524',
      symbolColor: '#eef5ff',
      height: 46
    },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      devTools: false
    }
  });

  const appRoot = app.isPackaged
    ? path.join(process.resourcesPath, 'app')
    : path.join(__dirname, 'app');

  window.loadFile(path.join(appRoot, 'index.html'));
  window.once('ready-to-show', () => window.show());

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  window.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) event.preventDefault();
  });
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
