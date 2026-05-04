import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const isWin = process.platform === "win32";
const pythonCmd = isWin ? "python" : "python3";
const viteBin = path.resolve(repoRoot, "node_modules", "vite", "bin", "vite.js");
const explicitViteOrigin = (process.env.VITE_DEV_SERVER_URL || "").trim().replace(/\/+$/, "");
const useViteDevServer =
  Boolean(explicitViteOrigin) ||
  ["1", "true", "yes"].includes(String(process.env.USE_VITE_DEV_SERVER || "").toLowerCase());
const viteOrigin = explicitViteOrigin || "http://127.0.0.1:5173";

const host = process.env.HOST || "0.0.0.0"; 
const port = process.env.PORT || "8080";

// 强制 Node.js 标准流使用 UTF-8，避免 Windows 控制台中文乱码
process.stdout.setDefaultEncoding("utf8");
process.stderr.setDefaultEncoding("utf8");

function log(line) {
  process.stdout.write(`${line}\n`);
}

function fail(line, code = 1) {
  process.stderr.write(`${line}\n`);
  process.exit(code);
}

function runCheck(command, args) {
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    env: process.env,
    stdio: "pipe",
    encoding: "utf8"
  });
  return result;
}

function ensureAvailable() {
  const pythonCheck = runCheck(pythonCmd, ["--version"]);
  if (pythonCheck.error || pythonCheck.status !== 0) {
    fail("Python 不可用，无法启动 Flask 服务。");
  }
  if (useViteDevServer) {
    const viteCheck = runCheck(process.execPath, [viteBin, "--version"]);
    if (viteCheck.error || viteCheck.status !== 0) {
      fail("Vite 不可用，请先执行 npm install。");
    }
  }
}

function prefixStream(child, label) {
  child.stdout?.setEncoding("utf8");
  child.stdout?.on("data", (chunk) => {
    process.stdout.write(`[${label}] ${chunk}`);
  });
  child.stderr?.setEncoding("utf8");
  child.stderr?.on("data", (chunk) => {
    process.stderr.write(`[${label}] ${chunk}`);
  });
}

function spawnTagged(command, args, label, extraEnv = {}) {
  const child = spawn(command, args, {
    cwd: repoRoot,
    env: { ...process.env, ...extraEnv },
    stdio: ["inherit", "pipe", "pipe"]
  });
  prefixStream(child, label);
  child.on("error", (error) => {
    process.stderr.write(`[${label}] ${error.message}\n`);
  });
  return child;
}

if (process.argv.includes("--check")) {
  ensureAvailable();
  const pyCompile = runCheck(pythonCmd, ["-m", "py_compile", "server.py"]);
  if (pyCompile.status !== 0) {
    fail(pyCompile.stderr || pyCompile.stdout || "server.py 语法检查失败。", pyCompile.status || 1);
  }
  log("start-server check passed");
  process.exit(0);
}

ensureAvailable();

// Windows 控制台默认 GBK，强制切换为 UTF-8 以正确显示中文日志
if (isWin) {
  try {
    spawnSync(process.env.ComSpec || "cmd.exe", ["/c", "chcp", "65001"], { stdio: "ignore" });
  } catch (_) { /* ignore */ }
}

log(`Starting Flask on http://${host}:${port}`);
if (useViteDevServer) {
  log(`Starting Vite on ${viteOrigin}`);
} else {
  log("Using built frontend assets from static/dist");
}

const pythonProc = spawnTagged(
  pythonCmd,
  ["server.py"],
  "flask",
  {
    HOST: host,
    PORT: port,
    VITE_DEV_SERVER_URL: useViteDevServer ? viteOrigin : "",
    PYTHONIOENCODING: "utf-8"
  }
);

const viteProc = useViteDevServer
  ? spawnTagged(
      process.execPath,
      [viteBin, "--host", "0.0.0.0", "--port", "5173"],
      "vite"
    )
  : null;

let shuttingDown = false;

function shutdown(reasonCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const proc of [pythonProc, viteProc].filter(Boolean)) {
    if (proc && !proc.killed) {
      proc.kill("SIGTERM");
    }
  }
  setTimeout(() => process.exit(reasonCode), 200);
}

pythonProc.on("exit", (code) => {
  if (!shuttingDown) {
    process.stderr.write(`[flask] exited with code ${code ?? 0}\n`);
    shutdown(code ?? 0);
  }
});

if (viteProc) {
  viteProc.on("exit", (code) => {
    if (!shuttingDown) {
      process.stderr.write(`[vite] exited with code ${code ?? 0}\n`);
      shutdown(code ?? 0);
    }
  });
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => shutdown(0));
}
