const { app, BrowserWindow, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const PORTA = 8765; // fixa: os dados salvos na janela dependem do endereço
const URL = `http://127.0.0.1:${PORTA}`;
const EXE = process.platform === "win32" ? "olfatecario-backend.exe" : "olfatecario-backend";

let backend = null;
let janela = null;

function pastaBackend() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "backend")
    : path.join(__dirname, "backend");
}

function subirBackend() {
  const dados = path.join(app.getPath("userData"), "dados");
  fs.mkdirSync(dados, { recursive: true });
  // dados-iniciais.json (só na versão da Manu) vem embutido e entra na primeira abertura
  const embutido = path.join(pastaBackend(), "dados-iniciais.json");
  const destino = path.join(dados, "dados-iniciais.json");
  if (fs.existsSync(embutido) && !fs.existsSync(destino)) fs.copyFileSync(embutido, destino);

  backend = spawn(path.join(pastaBackend(), EXE), [], {
    cwd: pastaBackend(),
    windowsHide: true,
    env: { ...process.env, OLFA_DATA_DIR: dados, OLFA_SEM_NAVEGADOR: "1" },
  });
  backend.on("exit", (codigo) => {
    backend = null;
    if (!app.isQuitting && codigo) {
      dialog.showErrorBox("Olfatecario", "O programa parou de funcionar. Feche e abra de novo.");
      app.quit();
    }
  });
}

function esperarBackend(tentativas = 60) {
  return new Promise((ok, falhou) => {
    const tentar = (n) => {
      http.get(URL, (r) => { r.resume(); ok(); }).on("error", () => {
        if (n <= 0) falhou(new Error("timeout"));
        else setTimeout(() => tentar(n - 1), 500);
      });
    };
    tentar(tentativas);
  });
}

function abrirJanela() {
  janela = new BrowserWindow({
    width: 1280, height: 860, minWidth: 900, minHeight: 600,
    title: "Olfatecario", autoHideMenuBar: true,
  });
  janela.loadURL(URL);
  // links externos abrem no navegador, não dentro do app
  janela.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(URL)) { shell.openExternal(url); return { action: "deny" }; }
    return { action: "allow" };
  });
  janela.on("closed", () => { janela = null; });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (janela) { if (janela.isMinimized()) janela.restore(); janela.focus(); }
  });
  app.whenReady().then(async () => {
    try {
      subirBackend();
      await esperarBackend();
      abrirJanela();
    } catch (e) {
      dialog.showErrorBox("Olfatecario", "Não consegui iniciar o programa.\n" + e.message);
      app.quit();
    }
  });
  app.on("before-quit", () => {
    app.isQuitting = true;
    if (backend) backend.kill();
  });
  app.on("window-all-closed", () => app.quit());
}
