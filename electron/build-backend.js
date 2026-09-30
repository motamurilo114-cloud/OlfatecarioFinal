// Empacota o servidor Python (../servidor) numa pasta backend/ para o Electron levar junto.
// Rode no sistema de destino (Windows gera para Windows, Mac gera para Mac).
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const srv = path.join(__dirname, "..", "servidor");
const win = process.platform === "win32";
const sep = win ? ";" : ":";
const py = process.env.PYTHON || (win ? "python" : "python3");
const run = (cmd, args) => execFileSync(cmd, args, { cwd: srv, stdio: "inherit" });

run(py, ["-m", "pip", "install", "-q", "-r", "requirements.txt", "pyinstaller"]);
const args = ["-m", "PyInstaller", "--noconfirm", "--onedir", "--name", "olfatecario-backend",
  "--distpath", path.join(__dirname, "backend-tmp"), "--workpath", path.join(srv, "build-electron"),
  "--specpath", path.join(srv, "build-electron"), "--add-data", `${path.join(srv, "static")}${sep}static`];
const iniciais = path.join(srv, "dados-iniciais.json");
if (fs.existsSync(iniciais) && !process.env.SEM_DADOS_INICIAIS) args.push("--add-data", `${iniciais}${sep}.`);
args.push("iniciar_exe.py");
run(py, args);

fs.rmSync(path.join(__dirname, "backend"), { recursive: true, force: true });
fs.renameSync(path.join(__dirname, "backend-tmp", "olfatecario-backend"), path.join(__dirname, "backend"));
fs.rmSync(path.join(__dirname, "backend-tmp"), { recursive: true, force: true });
// o PyInstaller põe os dados em _internal/; o Electron procura ao lado do executável
const interno = path.join(__dirname, "backend", "_internal", "dados-iniciais.json");
if (fs.existsSync(interno)) fs.copyFileSync(interno, path.join(__dirname, "backend", "dados-iniciais.json"));
console.log("Backend pronto em electron/backend");
