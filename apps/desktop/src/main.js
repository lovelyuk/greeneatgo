// 그린잇 관리자 — Windows desktop shell around https://greeneatgo.vercel.app/
// The app is a thin, locked-down browser window: all screens, logins and data come
// from the live admin web, so web deploys reach the desktop app with no reinstall.
const { app, BrowserWindow, Menu, shell, session, dialog } = require('electron');
const path = require('node:path');
const { APP_ORIGIN, APP_URL, isAppUrl, popupAction } = require('./navigation');

// Payment chime on the dashboard must play without a click first.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

if (!app.requestSingleInstanceLock()) {
  app.quit();
}

let mainWindow = null;

const secureWebPreferences = {
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  spellcheck: false,
};

function offlinePage(reason) {
  const html = `<!doctype html><html lang="ko"><meta charset="utf-8"><title>그린잇 관리자</title>
  <body style="margin:0;height:100vh;display:grid;place-items:center;background:#FAFAFA;font-family:'Malgun Gothic',sans-serif;color:#111827">
  <div style="text-align:center;max-width:420px;padding:24px">
  <h1 style="font-size:20px;margin:0 0 10px">관리자 화면에 연결하지 못했어요</h1>
  <p style="color:#6B7280;font-size:14px;line-height:1.6;margin:0 0 20px">인터넷 연결을 확인한 뒤 다시 시도해 주세요.<br><small>${String(reason).replace(/[<>&]/g, '')}</small></p>
  <a href="${APP_URL}" style="display:inline-block;padding:10px 20px;border-radius:8px;background:#2FA76A;color:#fff;text-decoration:none;font-size:14px">다시 시도</a>
  </div></body></html>`;
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
}

function isBlank(url) {
  return !url || url === 'about:blank';
}

function wireNavigation(win, { child = false } = {}) {
  win.webContents.setWindowOpenHandler(({ url }) => {
    const action = popupAction(url);
    if (action === 'external') { shell.openExternal(url); return { action: 'deny' }; }
    if (action === 'window') {
      return { action: 'allow', overrideBrowserWindowOptions: { width: 1100, height: 860, autoHideMenuBar: true, icon: iconPath(), webPreferences: secureWebPreferences } };
    }
    return { action: 'deny' };
  });
  win.webContents.on('did-create-window', (created) => wireNavigation(created, { child: true }));
  const guard = (event, url) => {
    if (isAppUrl(url) || url.startsWith('data:text/html') || (child && popupAction(url) === 'window')) return;
    event.preventDefault();
    if (popupAction(url) === 'external') shell.openExternal(url);
    // A blank popup the admin web opened for an outside document (e.g. 세금계산서 보기)
    // would stay empty: close it, the document is now in the browser.
    if (child && isBlank(win.webContents.getURL())) setImmediate(() => { if (!win.isDestroyed()) win.close(); });
  };
  win.webContents.on('will-navigate', guard);
  win.webContents.on('will-redirect', guard);
}

function iconPath() {
  return path.join(__dirname, '..', 'build', 'icon.ico');
}

function buildMenu() {
  const template = [
    { label: '화면', submenu: [
      { label: '새로고침', accelerator: 'F5', click: () => mainWindow?.webContents.reload() },
      { label: '처음 화면으로', click: () => mainWindow?.loadURL(APP_URL) },
      { type: 'separator' },
      { label: '크게', accelerator: 'CmdOrCtrl+=', role: 'zoomIn' },
      { label: '작게', accelerator: 'CmdOrCtrl+-', role: 'zoomOut' },
      { label: '원래 크기', accelerator: 'CmdOrCtrl+0', role: 'resetZoom' },
      { label: '전체 화면', accelerator: 'F11', role: 'togglefullscreen' },
      { type: 'separator' },
      { label: '종료', role: 'quit' },
    ] },
    { label: '도움말', submenu: [
      { label: '웹 브라우저로 열기', click: () => shell.openExternal(mainWindow?.webContents.getURL().startsWith(APP_ORIGIN) ? mainWindow.webContents.getURL() : APP_URL) },
      { label: '버전 정보', click: () => dialog.showMessageBox(mainWindow, { type: 'info', title: '그린잇 관리자', message: `그린잇 관리자 ${app.getVersion()}`, detail: `화면은 ${APP_ORIGIN} 에서 바로 불러와요.\n웹이 업데이트되면 앱도 자동으로 최신 화면이 보여요.` }) },
    ] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1024, minHeight: 680,
    title: '그린잇 관리자', icon: iconPath(), backgroundColor: '#FAFAFA', show: false,
    autoHideMenuBar: true,
    webPreferences: secureWebPreferences,
  });
  wireNavigation(mainWindow);
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (isMainFrame && code !== -3 && !url.startsWith('data:')) mainWindow.loadURL(offlinePage(`${description} (${code})`));
  });
  mainWindow.on('page-title-updated', (event) => { event.preventDefault(); mainWindow.setTitle('그린잇 관리자'); });
  mainWindow.loadURL(APP_URL);
}

app.on('second-instance', () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.focus();
});

app.whenReady().then(() => {
  // No camera/mic/location/etc. for the admin web; notifications and clipboard are fine.
  session.defaultSession.setPermissionRequestHandler((wc, permission, callback) => {
    const allowed = ['clipboard-sanitized-write', 'notifications', 'fullscreen'];
    callback(isAppUrl(wc.getURL()) && allowed.includes(permission));
  });
  buildMenu();
  createWindow();
});

app.on('window-all-closed', () => app.quit());
