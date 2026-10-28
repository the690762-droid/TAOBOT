// Vỏ Electron: khởi chạy backend Python rồi mở giao diện. Chạy được trên Windows và Linux.
const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const http = require("node:http");

const ROOT = path.resolve(__dirname, "..");
const PORT = Number(process.env.RYAN_API_PORT || 8765);
const PYTHON = process.env.RYAN_PYTHON || (process.platform === "win32" ? "python" : "python3");
let backend = null;

function waitForBackend(timeoutMs = 15000) {
  const end = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      http.get({ host: "127.0.0.1", port: PORT, path: "/" }, (res) => {
        res.resume();
        resolve();
      }).on("error", () => {
        if (Date.now() > end) return reject(new Error("backend không phản hồi"));
        setTimeout(tryOnce, 300);
      });
    };
    tryOnce();
  });
}

function startBackend() {
  backend = spawn(PYTHON, ["main.py"], {
    cwd: ROOT,
    env: { ...process.env, RYAN_API_PORT: String(PORT) },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  backend.stdout.on("data", (d) => process.stdout.write(d));
  backend.stderr.on("data", (d) => process.stderr.write(d));
  backend.on("exit", (code) => { backend = null; if (code !== null && code !== 0) console.error("backend thoát:", code); });
}

async function createWindow() {
  startBackend();
  const win = new BrowserWindow({ width: 1200, height: 800, minWidth: 480, minHeight: 500, title: "Ryan AI Command Center" });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  try {
    await waitForBackend();
    await win.loadURL(`http://127.0.0.1:${PORT}/`);
  } catch (e) {
    await win.loadURL("data:text/html;charset=utf-8,<p>Không khởi động được backend. Kiểm tra Python và log.</p>");
  }
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => app.quit());
app.on("will-quit", () => { if (backend) backend.kill(); });
