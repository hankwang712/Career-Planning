import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");

const runtimeFiles = [
  path.join(rootDir, "static", "dist", ".vite", "manifest.json"),
  path.join(rootDir, "static", "vendor", "chart.umd.js"),
  path.join(rootDir, "static", "vendor", "fuse.min.js")
];

const checkOnly = process.argv.includes("--check");

async function fileExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch (_) {
    return false;
  }
}

function runCommand(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: rootDir,
      stdio: "inherit",
      shell: false
    });

    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} ${args.join(" ")} exited with code ${code}`));
    });
  });
}

async function ensureRuntimeAssets() {
  const missing = [];
  for (const filePath of runtimeFiles) {
    if (!(await fileExists(filePath))) {
      missing.push(path.relative(rootDir, filePath));
    }
  }

  if (!missing.length) {
    console.log("runtime assets ready");
    return;
  }

  console.log(`missing runtime assets: ${missing.join(", ")}`);
  const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm";
  await runCommand(npmCmd, ["run", "build"]);
}

async function main() {
  await ensureRuntimeAssets();

  if (checkOnly) {
    return;
  }

  const host = (process.env.HOST || "0.0.0.0").trim() || "0.0.0.0";
  const port = (process.env.PORT || "8080").trim() || "8080";
  const pythonCmd = process.platform === "win32" ? "python" : "python3";
  const child = spawn(pythonCmd, ["-m", "flask", "--app", "server", "run", "--host", host, "--port", port], {
    cwd: rootDir,
    stdio: "inherit",
    shell: false,
    env: {
      ...process.env,
      FLASK_DEBUG: "0"
    }
  });

  child.on("error", (error) => {
    console.error("failed to start Flask server", error);
    process.exit(1);
  });

  child.on("exit", (code) => {
    process.exit(code ?? 0);
  });
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
