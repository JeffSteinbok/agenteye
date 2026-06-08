const { app, BrowserWindow, Tray, Menu, nativeImage, shell } = require("electron");
const { createServer } = require("net");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

app.setName("Copilot Dashboard");

// Parse CLI flags (e.g., --minimized for autostart mode)
const startMinimized = process.argv.includes("--minimized");

// ---------------------------------------------------------------------------
// Single-instance lock
// ---------------------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let serverPort = null;
let isQuitting = false;

// ---------------------------------------------------------------------------
// Port finder
// ---------------------------------------------------------------------------

function findAvailablePort(start = 5111) {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.listen(start, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
    server.on("error", () => {
      findAvailablePort(start + 1).then(resolve, reject);
    });
  });
}

// ---------------------------------------------------------------------------
// Python backend
// ---------------------------------------------------------------------------

function getProjectRoot() {
  if (app.isPackaged) {
    return process.resourcesPath;
  }
  // Dev: electron/ -> project root
  return path.resolve(__dirname, "..");
}

function isPython311Plus(cmd) {
  try {
    const { execFileSync } = require("child_process");
    const version = execFileSync(cmd, ["--version"], {
      encoding: "utf-8",
      timeout: 5000,
    }).trim();
    const match = version.match(/Python (\d+)\.(\d+)/);
    if (match) {
      const [, major, minor] = match.map(Number);
      return major >= 3 && minor >= 11;
    }
  } catch {
    // Not found
  }
  return false;
}

function findPython() {
  const projectRoot = getProjectRoot();

  // 1. Check for a venv inside the project (has all deps installed)
  const venvPaths =
    process.platform === "win32"
      ? [
          path.join(projectRoot, ".venv", "Scripts", "python.exe"),
          path.join(projectRoot, "venv", "Scripts", "python.exe"),
        ]
      : [
          path.join(projectRoot, ".venv", "bin", "python"),
          path.join(projectRoot, "venv", "bin", "python"),
          path.join(projectRoot, ".venv", "bin", "python3"),
          path.join(projectRoot, "venv", "bin", "python3"),
        ];

  for (const venvPy of venvPaths) {
    if (fs.existsSync(venvPy) && isPython311Plus(venvPy)) {
      console.log(`Using venv Python: ${venvPy}`);
      return venvPy;
    }
  }

  // 2. Fall back to system Python
  const candidates =
    process.platform === "win32"
      ? ["python", "python3", "py"]
      : ["python3", "python"];

  for (const cmd of candidates) {
    if (isPython311Plus(cmd)) return cmd;
  }

  return null;
}

function startPythonServer(port) {
  return new Promise((resolve, reject) => {
    const python = findPython();
    if (!python) {
      reject(new Error("Could not find Python 3.11+. Please install it."));
      return;
    }

    const projectRoot = getProjectRoot();
    const args = ["-m", "src.session_dashboard", "_serve", "--port", String(port)];

    pythonProcess = spawn(python, args, {
      cwd: projectRoot,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    });

    // Log Python stderr for debugging
    pythonProcess.stderr.on("data", (data) => {
      console.error(`[python] ${data.toString().trim()}`);
    });

    pythonProcess.on("error", (err) => {
      reject(new Error(`Failed to start Python server: ${err.message}`));
    });

    pythonProcess.on("exit", (code) => {
      if (!isQuitting) {
        console.error(`Python server exited unexpectedly (code ${code})`);
      }
      pythonProcess = null;
    });

    // Wait for the server to be ready
    const maxAttempts = 30;
    let attempts = 0;
    const poll = setInterval(() => {
      attempts++;
      const req = http.get(`http://127.0.0.1:${port}/api/server-info`, (res) => {
        if (res.statusCode === 200 || res.statusCode === 401) {
          clearInterval(poll);
          resolve();
        }
        res.resume();
      });
      req.on("error", () => {
        if (attempts >= maxAttempts) {
          clearInterval(poll);
          reject(new Error("Python server did not start in time"));
        }
      });
      req.setTimeout(1000, () => req.destroy());
    }, 500);
  });
}

function stopPythonServer() {
  if (pythonProcess) {
    pythonProcess.kill("SIGTERM");
    // Force kill after 3 seconds if still alive
    setTimeout(() => {
      if (pythonProcess) {
        try {
          pythonProcess.kill("SIGKILL");
        } catch {
          // Already dead
        }
      }
    }, 3000);
  }
}

// ---------------------------------------------------------------------------
// Tray icon
// ---------------------------------------------------------------------------

function showWindow() {
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
    if (process.platform === "darwin" && app.dock) {
      app.dock.show();
    }
  }
}

function createTray() {
  const iconPath = path.join(__dirname, "assets", "icon.png");
  let icon;

  if (fs.existsSync(iconPath)) {
    icon = nativeImage.createFromPath(iconPath);
    // Resize for tray (16x16 on most platforms, macOS uses 22x22)
    if (process.platform === "darwin") {
      icon = icon.resize({ width: 22, height: 22 });
    } else {
      icon = icon.resize({ width: 16, height: 16 });
    }
    icon.setTemplateImage(process.platform === "darwin");
  } else {
    // Fallback: create a simple colored square
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip("Copilot Dashboard");

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Open Dashboard",
      click: () => showWindow(),
    },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);

  tray.on("click", () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.focus();
      } else {
        showWindow();
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Main window
// ---------------------------------------------------------------------------

function createWindow() {
  const iconPath = path.join(__dirname, "assets", "icon.png");
  const icon = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath)
    : undefined;

  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: "Copilot Dashboard",
    icon,
    backgroundColor: "#0d1117",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Show loading page immediately
  const loadingPage = path.join(__dirname, "assets", "loading.html");
  if (fs.existsSync(loadingPage)) {
    win.loadFile(loadingPage);
  }
  if (!startMinimized) {
    win.show();
  }

  // Open external links in default browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // Minimize to tray instead of closing
  win.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      win.hide();
      // On macOS, also hide the dock icon when window is hidden
      if (process.platform === "darwin" && app.dock) {
        app.dock.hide();
      }
    }
  });

  return win;
}

function navigateToApp(win, port) {
  win.webContents.on("will-navigate", (event, url) => {
    if (
      !url.startsWith(`http://127.0.0.1:${port}`) &&
      !url.startsWith(`http://localhost:${port}`)
    ) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  win.loadURL(`http://127.0.0.1:${port}`);
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

async function main() {
  // Set dock icon on macOS
  const dockIconPath = path.join(__dirname, "assets", "icon.png");
  if (process.platform === "darwin" && app.dock && fs.existsSync(dockIconPath)) {
    app.dock.setIcon(nativeImage.createFromPath(dockIconPath));
    // Hide dock icon when starting minimized (tray-only mode)
    if (startMinimized) {
      app.dock.hide();
    }
  }

  // Create tray icon first (visible even in minimized mode)
  createTray();

  // Create window (hidden if --minimized)
  mainWindow = createWindow();
  Menu.setApplicationMenu(null);

  // Find available port and start Python backend
  try {
    serverPort = await findAvailablePort(5111);
    console.log(`Starting Python server on port ${serverPort}...`);
    await startPythonServer(serverPort);
    console.log("Python server ready");

    // Navigate to the real app
    if (mainWindow) {
      navigateToApp(mainWindow, serverPort);
    }
  } catch (err) {
    console.error("Failed to start:", err.message);
    const { dialog } = require("electron");
    await dialog.showErrorBox(
      "Copilot Dashboard - Startup Error",
      `${err.message}\n\nMake sure Python 3.11+ is installed and the copilot-dashboard package is available.`
    );
    isQuitting = true;
    app.quit();
  }
}

app.on("second-instance", () => {
  showWindow();
  if (mainWindow && mainWindow.isMinimized()) mainWindow.restore();
});

app.on("window-all-closed", () => {
  // Don't quit — keep running in tray
});

app.on("activate", () => {
  // macOS: clicking dock icon should show the window
  showWindow();
});

app.on("before-quit", () => {
  isQuitting = true;
  stopPythonServer();
});

app.whenReady().then(main).catch((err) => {
  console.error("Failed to start Copilot Dashboard:", err);
  app.quit();
});
