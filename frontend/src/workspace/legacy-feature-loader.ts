/**
 * 按需加载旧版功能脚本，并为尚未加载的 window 函数安装一次性桥接。
 * 这是从 classic script 迁出的第一个 TS 模块：显式类型、无全局污染。
 */
type BundleAsset = { key: string; src: string };
type BundleId = string;

const SECTION_BUNDLES: Record<string, BundleId[]> = {
  profile: ["profile"]
};

const LEGACY_BUNDLES: Record<string, BundleAsset[]> = {
  profile: [
    { key: "assessment-hub", src: "/static/assessment-hub.js" },
    { key: "assessment-pet", src: "/static/assessment-pet.js" },
    { key: "deep-test-hub", src: "/static/deep-test-hub.js" }
  ]
};

const bundlePromises = new Map<BundleId, Promise<void>>();

function loadLegacyScriptOnce(src: string, key: string): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[data-legacy-key="${key}"]`);
    if (existing) {
      if (existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${key}`)), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.dataset.legacyKey = key;
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    }, { once: true });
    script.addEventListener("error", () => reject(new Error(`Failed to load ${key}`)), { once: true });
    document.body.appendChild(script);
  });
}

async function ensureBundle(bundleId: BundleId): Promise<void> {
  const assets = LEGACY_BUNDLES[bundleId];
  if (!assets?.length) return;
  if (!bundlePromises.has(bundleId)) {
    const promise = (async () => {
      for (const asset of assets) {
        await loadLegacyScriptOnce(asset.src, asset.key);
      }
    })().catch((error: unknown) => {
      bundlePromises.delete(bundleId);
      throw error;
    });
    bundlePromises.set(bundleId, promise);
    return promise;
  }
  return bundlePromises.get(bundleId)!;
}

async function ensureSectionReady(sectionId: string): Promise<void> {
  const bundleIds = SECTION_BUNDLES[sectionId] || [];
  for (const bundleId of bundleIds) {
    await ensureBundle(bundleId);
  }
}

function callLoadedWindowFunction(functionName: string, fallback: unknown, args: unknown[]): unknown {
  const fn = window[functionName];
  if (typeof fn === "function" && fn !== fallback) {
    return (fn as (...a: unknown[]) => unknown)(...args);
  }
  return undefined;
}

function installWindowBridge(functionName: string, bundleId: BundleId): void {
  if (typeof window[functionName] === "function") return;
  const bridge = (...args: unknown[]): Promise<unknown> =>
    ensureBundle(bundleId)
      .then(() => callLoadedWindowFunction(functionName, bridge, args))
      .catch((error: unknown) => {
        console.error(`${functionName} load failed`, error);
        if (typeof window.showToast === "function") {
          const message = error instanceof Error ? error.message : "请稍后重试";
          window.showToast("模块加载失败", message, "error", 2200);
        }
      });
  window[functionName] = bridge;
}

function installShowSectionBridge(): void {
  const originalShowSection = window.showSection;
  if (typeof originalShowSection !== "function") return;

  window.showSection = async function wrappedShowSection(this: unknown, sectionId: string, ...rest: unknown[]): Promise<unknown> {
    await ensureSectionReady(sectionId);
    return originalShowSection.call(this, sectionId, ...rest);
  };
}

function bindWorkspaceActions(): void {
  document.addEventListener("click", async (event: MouseEvent) => {
    const target = event.target as Element | null;

    const showSectionTrigger = target?.closest<HTMLElement>("[data-show-section]");
    if (showSectionTrigger) {
      event.preventDefault();
      await window.showSection?.(showSectionTrigger.dataset.showSection || "");
      return;
    }

    const assessmentTrigger = target?.closest<HTMLElement>("[data-open-assessment]");
    if (assessmentTrigger) {
      event.preventDefault();
      const test = assessmentTrigger.dataset.openAssessment || undefined;
      await window.openAssessmentModal?.(test);
      return;
    }

    const deepRunnerTrigger = target?.closest<HTMLElement>("[data-open-deep-runner]");
    if (deepRunnerTrigger) {
      event.preventDefault();
      const type = deepRunnerTrigger.dataset.openDeepRunner || "";
      const restart = deepRunnerTrigger.dataset.deepRestart !== "false";
      await window.openDeepTestRunnerPage?.(type, restart);
      return;
    }

    const historyTrigger = target?.closest<HTMLElement>("[data-toggle-deep-history]");
    if (historyTrigger) {
      event.preventDefault();
      await window.toggleHistoryPanel?.();
    }
  });
}

export function initLegacyFeatureLoader(): void {
  if (window.__workspaceLegacyFeatureLoaderReady) return;
  window.__workspaceLegacyFeatureLoaderReady = true;

  installWindowBridge("openAssessmentModal", "profile");
  installWindowBridge("openDeepTestModal", "profile");
  installWindowBridge("openDeepTestRunnerPage", "profile");
  installWindowBridge("openDeepTestResultPage", "profile");
  installWindowBridge("toggleHistoryPanel", "profile");

  installShowSectionBridge();
  bindWorkspaceActions();
  window.ensureWorkspaceSectionReady = ensureSectionReady;
}
