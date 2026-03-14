# SENTINEL Desktop App

Native Mac/Linux desktop wrapper for the SENTINEL dashboard. Opens your GitHub Pages site in a dedicated app window with auto-launch on startup.

## Quick Setup

### 1. Install Node.js
Download from [nodejs.org](https://nodejs.org/) (v18+)

### 2. Set your URL
Open `main.js` and change this line to your GitHub Pages URL:

```js
const SENTINEL_URL = 'https://Tsenohebot.github.io/Sentinel/index.html';
```

### 3. Install dependencies
```bash
cd sentinel-desktop
npm install
```

### 4. Run it
```bash
npm start
```

## Build a standalone app

### Mac (.dmg)
```bash
npm run build:mac
```
Output: `dist/SENTINEL-1.0.0.dmg`

### Linux (.AppImage / .deb)
```bash
npm run build:linux
```
Output: `dist/SENTINEL-1.0.0.AppImage` or `dist/sentinel_1.0.0_amd64.deb`

### Both
```bash
npm run build:all
```

## Features

- **Auto-launch at login** — toggle from the app menu (SENTINEL → Launch at Login)
- **Always on Top** — pin the window above other apps (Window → Always on Top)
- **Full keyboard support** — Cmd+R to reload, Cmd+F for fullscreen, Cmd+Plus/Minus to zoom
- **External links** — news article links etc open in your default browser, not inside the app
- **Dark titlebar** — matches the SENTINEL dark theme
- **macOS traffic lights** — inset into the content area for a clean frameless look

## Custom App Icon

Replace `icon.png` with your own 512x512 PNG icon. For Mac, a 1024x1024 is ideal.

## Folder Structure

```
sentinel-desktop/
├── .github/
│   └── workflows/
│       └── build-desktop.yml  # CI build + release
├── main.js          # Electron main process
├── preload.js       # Security bridge
├── package.json     # Dependencies + build config
├── icon.png         # App icon (add your own)
└── README.md
```

## Releasing via GitHub

The repo includes a GitHub Actions workflow that builds for Mac + Linux and publishes a GitHub Release automatically.

### How to release

1. Push the `sentinel-desktop/` folder to your repo
2. Go to **Actions** → **Build SENTINEL Desktop** → **Run workflow**
3. Enter a version number (e.g. `1.0.0`)
4. Wait ~10 minutes for it to build
5. A new **Release** appears under your repo's Releases tab with downloadable `.dmg`, `.AppImage`, and `.deb` files

Users just download and run — no Node.js or terminal needed.

### What gets built

| Platform | File | How to install |
|----------|------|----------------|
| Mac (Intel + Apple Silicon) | `SENTINEL-1.0.0.dmg` | Open, drag to Applications |
| Mac (portable) | `SENTINEL-1.0.0-mac.zip` | Unzip and run |
| Linux (universal) | `SENTINEL-1.0.0.AppImage` | `chmod +x` and run |
| Linux (Debian/Ubuntu) | `sentinel_1.0.0_amd64.deb` | `sudo dpkg -i sentinel_*.deb` |

## Notes

- The app loads your hosted dashboard — it doesn't bundle the HTML. This means you always get the latest version when the page loads.
- No data is stored locally except the auto-launch preference.
- Works offline only if your browser has the page cached.
