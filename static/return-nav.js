(function () {
  const STACK_KEY = "app_return_nav_stack_v1";
  const MAX_STACK_SIZE = 24;
  const RELock_PATH = "/main.html";

  function currentUrl() {
    const path = window.location.pathname || "/";
    const search = window.location.search || "";
    const hash = window.location.hash || "";
    return `${path}${search}${hash}`;
  }

  function safeParseStack() {
    try {
      const parsed = JSON.parse(sessionStorage.getItem(STACK_KEY) || "[]");
      return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string" && item.trim()) : [];
    } catch (_) {
      return [];
    }
  }

  function saveStack(stack) {
    try {
      sessionStorage.setItem(STACK_KEY, JSON.stringify(stack.slice(-MAX_STACK_SIZE)));
    } catch (_) {
      // Ignore session storage errors.
    }
  }

  function syncStack(mode = "push") {
    const current = currentUrl();
    const stack = safeParseStack();
    const last = stack[stack.length - 1];
    if (!last) {
      saveStack([current]);
      return;
    }
    if (last === current) return;
    if (mode === "replace") {
      stack[stack.length - 1] = current;
      saveStack(stack);
      return;
    }
    stack.push(current);
    saveStack(stack);
  }

  function normalizeFallbackUrl(fallbackUrl) {
    const raw = String(fallbackUrl || "/main.html#profile").trim();
    if (!raw) return "/main.html#profile";
    if (/^https?:\/\//i.test(raw)) {
      try {
        const parsed = new URL(raw);
        if (parsed.origin === window.location.origin) {
          return `${parsed.pathname}${parsed.search}${parsed.hash}`;
        }
      } catch (_) {
        return "/main.html#profile";
      }
    }
    return raw;
  }

  function isBlockedReturnTarget(url) {
    const safe = normalizeFallbackUrl(url);
    return safe === "/login.html";
  }

  function readReferrerTarget() {
    try {
      if (!document.referrer) return "";
      const parsed = new URL(document.referrer);
      if (parsed.origin !== window.location.origin) return "";
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch (_) {
      return "";
    }
  }

  function buildRelockUrl(target) {
    const safeTarget = normalizeFallbackUrl(target);
    return `${RELock_PATH}?force_lock=1&return_to=${encodeURIComponent(safeTarget)}`;
  }

  function goBackToLastInterface(fallbackUrl) {
    const current = currentUrl();
    const fallback = normalizeFallbackUrl(fallbackUrl);
    const stack = safeParseStack();
    while (stack.length && stack[stack.length - 1] === current) {
      stack.pop();
    }
    let target = stack[stack.length - 1] || "";
    if (!target || target === current || isBlockedReturnTarget(target)) {
      const referrerTarget = readReferrerTarget();
      if (referrerTarget && referrerTarget !== current && !isBlockedReturnTarget(referrerTarget)) {
        target = referrerTarget;
      }
    }
    if (!target || target === current || isBlockedReturnTarget(target)) {
      target = fallback;
    }
    saveStack(stack.length ? stack : [target]);
    window.location.href = buildRelockUrl(target);
  }

  function bindReturnLinks() {
    document.querySelectorAll("[data-return-last]").forEach((node) => {
      if (node.dataset.returnLastBound === "1") return;
      node.addEventListener("click", (event) => {
        event.preventDefault();
        goBackToLastInterface(node.getAttribute("href") || "/main.html#profile");
      });
      node.dataset.returnLastBound = "1";
    });
  }

  function wrapHistoryMethod(methodName) {
    const original = window.history[methodName];
    if (typeof original !== "function") return;
    window.history[methodName] = function (...args) {
      const result = original.apply(this, args);
      syncStack("replace");
      return result;
    };
  }

  window.goBackToLastInterface = goBackToLastInterface;
  wrapHistoryMethod("pushState");
  wrapHistoryMethod("replaceState");

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      syncStack("push");
      bindReturnLinks();
    }, { once: true });
  } else {
    syncStack("push");
    bindReturnLinks();
  }

  window.addEventListener("hashchange", () => syncStack("replace"));
  window.addEventListener("pageshow", () => {
    syncStack("replace");
    bindReturnLinks();
  });
})();
