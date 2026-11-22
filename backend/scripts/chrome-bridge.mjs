import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const HOST = "127.0.0.1";
const PORT = Number(process.env.CHROME_BRIDGE_PORT || "3456");
const CONNECT_TIMEOUT_MS = 10000;
const COMMAND_TIMEOUT_MS = 15000;
const MAX_BODY_BYTES = 1024 * 1024;

function candidateDevToolsFiles() {
  const files = [];
  if (process.env.CHROME_USER_DATA_DIR) {
    files.push(path.join(process.env.CHROME_USER_DATA_DIR, "DevToolsActivePort"));
  }
  const home = os.homedir();
  if (process.platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA || path.join(home, "AppData", "Local");
    files.push(
      path.join(localAppData, "Google", "Chrome", "User Data", "DevToolsActivePort"),
      path.join(localAppData, "Google", "Chrome Beta", "User Data", "DevToolsActivePort"),
      path.join(localAppData, "Chromium", "User Data", "DevToolsActivePort"),
      path.join(localAppData, "Microsoft", "Edge", "User Data", "DevToolsActivePort")
    );
  } else if (process.platform === "darwin") {
    const appSupport = path.join(home, "Library", "Application Support");
    files.push(
      path.join(appSupport, "Google", "Chrome", "DevToolsActivePort"),
      path.join(appSupport, "Chromium", "DevToolsActivePort"),
      path.join(appSupport, "Microsoft Edge", "DevToolsActivePort")
    );
  } else {
    const configDir = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
    files.push(
      path.join(configDir, "google-chrome", "DevToolsActivePort"),
      path.join(configDir, "chromium", "DevToolsActivePort"),
      path.join(configDir, "microsoft-edge", "DevToolsActivePort")
    );
  }
  return files;
}

async function resolveBrowserWsUrls() {
  const urls = [];
  for (const file of candidateDevToolsFiles()) {
    try {
      const content = fs.readFileSync(file, "utf8").trim();
      const lines = content.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (lines.length >= 2 && /^\d+$/.test(lines[0]) && lines[1].startsWith("/")) {
        const wsUrl = `ws://127.0.0.1:${lines[0]}${lines[1]}`;
        if (!urls.includes(wsUrl)) urls.push(wsUrl);
      }
    } catch {
      // Ignore missing or unreadable DevToolsActivePort files.
    }
  }

  const debugPort = process.env.CHROME_REMOTE_DEBUGGING_PORT || "9222";
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    try {
      const response = await fetch(`http://127.0.0.1:${debugPort}/json/version`, {
        signal: controller.signal
      });
      if (response.ok) {
        const data = await response.json();
        if (typeof data.webSocketDebuggerUrl === "string" && !urls.includes(data.webSocketDebuggerUrl)) {
          urls.push(data.webSocketDebuggerUrl);
        }
      }
    } finally {
      clearTimeout(timer);
    }
  } catch {
    // Fallback port not available.
  }

  return urls;
}

class CDPBridge {
  constructor() {
    this.ws = null;
    this.connecting = null;
    this.nextId = 1;
    this.pending = new Map();
    this.sessions = new Map();
  }

  get connected() {
    return Boolean(this.ws && this.ws.readyState === WebSocket.OPEN);
  }

  _reset(reason) {
    const err = reason instanceof Error ? reason : new Error(String(reason || "Chrome connection closed"));
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(err);
    }
    this.pending.clear();
    this.sessions.clear();
    this.ws = null;
  }

  _openSocket(wsUrl) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const ws = new WebSocket(wsUrl);
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try {
          ws.close();
        } catch {
          // Ignore close errors.
        }
        reject(new Error(`Timed out connecting to Chrome at ${wsUrl}`));
      }, CONNECT_TIMEOUT_MS);

      ws.addEventListener("open", () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.ws = ws;
        ws.addEventListener("message", (event) => this._onMessage(event.data));
        ws.addEventListener("close", () => {
          if (this.ws === ws) this._reset("Chrome WebSocket closed");
        });
        ws.addEventListener("error", () => {
          if (this.ws === ws) this._reset("Chrome WebSocket error");
        });
        resolve();
      });

      ws.addEventListener("error", () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(new Error(`Failed to connect to Chrome at ${wsUrl}`));
      });

      ws.addEventListener("close", () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(new Error(`Chrome rejected connection at ${wsUrl}`));
      });
    });
  }

  async ensureConnected() {
    if (this.connected) return;
    if (this.connecting) return this.connecting;

    this.connecting = (async () => {
      const urls = await resolveBrowserWsUrls();
      if (urls.length === 0) {
        throw new Error("Chrome remote debugging is not enabled (DevToolsActivePort not found)");
      }
      let lastError = null;
      for (const wsUrl of urls) {
        try {
          await this._openSocket(wsUrl);
          return;
        } catch (error) {
          lastError = error;
        }
      }
      throw lastError || new Error("Could not connect to Chrome remote debugging");
    })().finally(() => {
      this.connecting = null;
    });

    return this.connecting;
  }

  _onMessage(raw) {
    let message;
    try {
      message = JSON.parse(typeof raw === "string" ? raw : Buffer.from(raw).toString("utf8"));
    } catch {
      return;
    }
    if (typeof message.id === "number") {
      const entry = this.pending.get(message.id);
      if (!entry) return;
      this.pending.delete(message.id);
      clearTimeout(entry.timer);
      if (message.error) {
        entry.reject(new Error(message.error.message || JSON.stringify(message.error)));
      } else {
        entry.resolve(message.result || {});
      }
      return;
    }
    if (message.method === "Target.detachedFromTarget" && message.params?.targetId) {
      this.sessions.delete(message.params.targetId);
    }
  }

  async send(method, params = {}, sessionId = undefined, timeoutMs = COMMAND_TIMEOUT_MS) {
    await this.ensureConnected();
    if (!this.connected) {
      throw new Error("Chrome connection is not open");
    }
    const id = this.nextId++;
    const payload = sessionId ? { id, method, params, sessionId } : { id, method, params };
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command ${method} timed out`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.ws.send(JSON.stringify(payload));
      } catch (error) {
        this.pending.delete(id);
        clearTimeout(timer);
        reject(error);
      }
    });
  }

  async ensureSession(targetId) {
    if (this.sessions.has(targetId)) {
      return this.sessions.get(targetId);
    }
    const result = await this.send("Target.attachToTarget", { targetId, flatten: true });
    if (!result.sessionId) {
      throw new Error(`Could not attach to target ${targetId}`);
    }
    this.sessions.set(targetId, result.sessionId);
    return result.sessionId;
  }

  async createTab(url) {
    const result = await this.send("Target.createTarget", {
      url: url || "about:blank",
      background: true
    });
    return result.targetId;
  }

  async navigate(targetId, url) {
    const sessionId = await this.ensureSession(targetId);
    try {
      return await this.send("Page.navigate", { url }, sessionId, 20000);
    } catch (error) {
      this.sessions.delete(targetId);
      throw error;
    }
  }

  async evaluate(targetId, expression) {
    const sessionId = await this.ensureSession(targetId);
    let result;
    try {
      result = await this.send(
        "Runtime.evaluate",
        { expression, returnByValue: true, awaitPromise: true },
        sessionId
      );
    } catch (error) {
      this.sessions.delete(targetId);
      throw error;
    }
    if (result.exceptionDetails) {
      const text = result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Evaluation error";
      const error = new Error(text);
      error.statusCode = 400;
      throw error;
    }
    return result.result && "value" in result.result ? result.result.value : null;
  }

  async closeTab(targetId) {
    this.sessions.delete(targetId);
    await this.send("Target.closeTarget", { targetId });
  }

  async listTargets() {
    const result = await this.send("Target.getTargets");
    return result.targetInfos || [];
  }

  close() {
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // Ignore close errors.
      }
      this._reset("Bridge shutting down");
    }
  }
}

function sendJson(res, statusCode, body) {
  const payload = JSON.stringify(body);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload)
  });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    req.on("data", (chunk) => {
      total += chunk.length;
      if (total > MAX_BODY_BYTES) {
        const error = new Error("Request body too large");
        error.statusCode = 413;
        reject(error);
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

const bridge = new CDPBridge();

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${HOST}:${PORT}`);
  const pathname = url.pathname;

  try {
    if (req.method === "GET" && pathname === "/health") {
      sendJson(res, 200, { ok: true, connected: bridge.connected });
      return;
    }

    if (req.method === "GET" && pathname === "/targets") {
      const targets = await bridge.listTargets();
      sendJson(res, 200, { targets });
      return;
    }

    if (req.method === "GET" && pathname === "/new") {
      const targetUrl = url.searchParams.get("url") || "about:blank";
      const targetId = await bridge.createTab(targetUrl);
      sendJson(res, 200, { targetId });
      return;
    }

    if (req.method === "GET" && pathname === "/navigate") {
      const targetId = url.searchParams.get("target") || "";
      const targetUrl = url.searchParams.get("url") || "";
      if (!targetId || !targetUrl) {
        sendJson(res, 400, { error: "Missing target or url parameter" });
        return;
      }
      const result = await bridge.navigate(targetId, targetUrl);
      sendJson(res, 200, { ok: true, frameId: result.frameId || "" });
      return;
    }

    if (req.method === "POST" && pathname === "/eval") {
      const targetId = url.searchParams.get("target") || "";
      if (!targetId) {
        sendJson(res, 400, { error: "Missing target parameter" });
        return;
      }
      const expression = await readBody(req);
      const value = await bridge.evaluate(targetId, expression);
      sendJson(res, 200, { value });
      return;
    }

    if (req.method === "GET" && pathname === "/close") {
      const targetId = url.searchParams.get("target") || "";
      if (!targetId) {
        sendJson(res, 400, { error: "Missing target parameter" });
        return;
      }
      await bridge.closeTab(targetId);
      sendJson(res, 200, { success: true });
      return;
    }

    sendJson(res, 404, { error: "Not found" });
  } catch (error) {
    const statusCode = Number.isInteger(error?.statusCode) ? error.statusCode : 500;
    sendJson(res, statusCode, { error: error?.message || "Bridge error" });
  }
});

server.on("error", (error) => {
  if (error && error.code === "EADDRINUSE") {
    process.stdout.write(`Port ${PORT} is already in use; reusing existing Chrome bridge.\n`);
    process.exit(0);
  }
  process.stderr.write(`Chrome bridge failed: ${error?.message || error}\n`);
  process.exit(1);
});

server.listen(PORT, HOST, () => {
  process.stdout.write(`Listening on http://${HOST}:${PORT}\n`);
});

function shutdown() {
  bridge.close();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 200);
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, shutdown);
}
