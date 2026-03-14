const { app, BrowserWindow, Menu, shell, Tray, nativeImage, dialog } = require('electron');
const path = require('path');
const AutoLaunch = require('auto-launch');

// ── CONFIG ──────────────────────────────────────────────────────────────────
// Change this to your GitHub Pages URL
const SENTINEL_URL = 'https://Tsenohebot.github.io/Sentinel/index.html';

// Auto-launch on system startup
const autoLauncher = new AutoLaunch({
  name: 'SENTINEL',
  isHidden: false,
});

let mainWindow = null;
let tray = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 800,
    minHeight: 600,
    title: 'SENTINEL',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    // Frameless with custom titlebar feel
    titleBarStyle: 'hiddenInset', // macOS: traffic lights inset into content
    trafficLightPosition: { x: 12, y: 12 },
    autoHideMenuBar: true,
  });

  // Load the hosted dashboard
  mainWindow.loadURL(SENTINEL_URL);

  // Open external links in default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Handle navigation to external sites
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.includes('github.io') && !url.startsWith('data:')) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── APP MENU ────────────────────────────────────────────────────────────────
function buildMenu() {
  const isMac = process.platform === 'darwin';

  const template = [
    ...(isMac ? [{
      label: 'SENTINEL',
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        {
          label: 'Launch at Login',
          type: 'checkbox',
          checked: false,
          click: async (menuItem) => {
            if (menuItem.checked) {
              await autoLauncher.enable();
            } else {
              await autoLauncher.disable();
            }
          }
        },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    }] : []),
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { type: 'separator' },
        { role: 'toggleDevTools' },
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        ...(isMac ? [
          { type: 'separator' },
          { role: 'front' },
        ] : [
          { role: 'close' }
        ]),
        { type: 'separator' },
        {
          label: 'Always on Top',
          type: 'checkbox',
          checked: false,
          click: (menuItem) => {
            if (mainWindow) mainWindow.setAlwaysOnTop(menuItem.checked);
          }
        }
      ]
    },
    {
      label: 'Settings',
      submenu: [
        {
          label: 'Launch at Login',
          type: 'checkbox',
          checked: false,
          click: async (menuItem) => {
            if (menuItem.checked) {
              await autoLauncher.enable();
            } else {
              await autoLauncher.disable();
            }
          }
        },
        { type: 'separator' },
        {
          label: 'Set Dashboard URL...',
          click: async () => {
            // Simple URL override for power users
            const { response, checkboxChecked } = await dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'Dashboard URL',
              message: `Current URL:\n${SENTINEL_URL}\n\nTo change the URL, edit the SENTINEL_URL variable in main.js`,
              buttons: ['OK'],
            });
          }
        }
      ]
    },
  ];

  // Check auto-launch state and update menu
  autoLauncher.isEnabled().then(isEnabled => {
    template.forEach(menu => {
      if (menu.submenu) {
        menu.submenu.forEach(item => {
          if (item.label === 'Launch at Login') {
            item.checked = isEnabled;
          }
        });
      }
    });
    Menu.setApplicationMenu(Menu.buildFromTemplate(template));
  }).catch(() => {
    Menu.setApplicationMenu(Menu.buildFromTemplate(template));
  });
}

// ── APP LIFECYCLE ───────────────────────────────────────────────────────────
app.whenReady().then(() => {
  createWindow();
  buildMenu();

  app.on('activate', () => {
    // macOS: re-create window when dock icon clicked
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// Set app name for macOS
app.setName('SENTINEL');
