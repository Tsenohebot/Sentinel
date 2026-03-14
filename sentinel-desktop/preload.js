// Preload script — runs before the web page loads
// Provides a safe bridge between Node.js and the renderer

const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('sentinel', {
  platform: process.platform,
  isDesktopApp: true,
});
