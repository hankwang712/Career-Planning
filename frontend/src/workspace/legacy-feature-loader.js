const SECTION_BUNDLES = {
  jobs: ["jobs"],
  profile: ["profile"]
};

const LEGACY_BUNDLES = {
  jobs: [
    { key: "jobs-analytics", src: "/static/jobs-analytics.js" }
  ],
  profile: [
    { key: "assessment-hub", src: "/static/assessment-hub.js" },
    { key: "assessment-pet", src: "/static/assessment-pet.js" },
    { key: "deep-test-hub", src: "/static/deep-test-hub.js" }
  ]
};

const bundlePromises = new Map();

function loadLegacyScriptOnce(src, key) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-legacy-key="${key}"]`);
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
    script.addEventListener(
      "load",
      () => {
        script.dataset.loaded = "true";
        resolve();
      },
      { once: true }
    );
    script.addEventListener("error", () => reject(new Error(`Failed to load ${key}`)), { once: true });
    document.body.appendChild(script);
  });
}

async function ensureBundle(bundleId) {
  if (!LEGACY_BUNDLES[bundleId]?.length) return;
  if (!bundlePromises.has(bundleId)) {
    const promise = (async () => {
      for (const asset of LEGACY_BUNDLES[bundleId]) {
        await loadLegacyScriptOnce(asset.src, asset.key);
      }
    })().catch((error) => {
      bundlePromises.delete(bundleId);
      throw error;
    });
    bundlePromises.set(bundleId, promise);
  }
  return bundlePromises.get(bundleId);
}

async function ensureSectionReady(sectionId) {
  const bundleIds = SECTION_BUNDLES[sectionId] || [];
  for (const bundleId of bundleIds) {
    await ensureBundle(bundleId);
  }
}

function callLoadedWindowFunction(functionName, fallback, args) {
  const fn = window[functionName];
  if (typeof fn === "function" && fn !== fallback) {
    return fn(...args);
  }
  return undefined;
}

function installWindowBridge(functionName, bundleId) {
  if (typeof window[functionName] === "function") return;
  const bridge = (...args) =>
    ensureBundle(bundleId)
      .then(() => callLoadedWindowFunction(functionName, bridge, args))
      .catch((error) => {
        console.error(`${functionName} load failed`, error);
        if (typeof window.showToast === "function") {
          window.showToast("模块加载失败", error.message || "请稍后重试", "error", 2200);
        }
      });
  window[functionName] = bridge;
}

function installShowSectionBridge() {
  const originalShowSection = window.showSection;
  if (typeof originalShowSection !== "function") return;

  window.showSection = async function wrappedShowSection(sectionId, ...rest) {
    await ensureSectionReady(sectionId);
    return originalShowSection.call(this, sectionId, ...rest);
  };
}

function bindWorkspaceActions() {
  document.addEventListener("click", async (event) => {
    const showSectionTrigger = event.target.closest("[data-show-section]");
    if (showSectionTrigger) {
      event.preventDefault();
      await window.showSection?.(showSectionTrigger.dataset.showSection || "");
      return;
    }

    const assessmentTrigger = event.target.closest("[data-open-assessment]");
    if (assessmentTrigger) {
      event.preventDefault();
      const test = assessmentTrigger.dataset.openAssessment || undefined;
      await window.openAssessmentModal?.(test);
      return;
    }

    const deepRunnerTrigger = event.target.closest("[data-open-deep-runner]");
    if (deepRunnerTrigger) {
      event.preventDefault();
      const type = deepRunnerTrigger.dataset.openDeepRunner || "";
      const restart = deepRunnerTrigger.dataset.deepRestart !== "false";
      await window.openDeepTestRunnerPage?.(type, restart);
      return;
    }

    const analyticsTrigger = event.target.closest("[data-analytics-tab]");
    if (analyticsTrigger) {
      event.preventDefault();
      await window.analyticsSelectTab?.(analyticsTrigger.dataset.analyticsTab || "");
      return;
    }

    const historyTrigger = event.target.closest("[data-toggle-deep-history]");
    if (historyTrigger) {
      event.preventDefault();
      await window.toggleHistoryPanel?.();
    }
  });
}

export function initLegacyFeatureLoader() {
  if (window.__workspaceLegacyFeatureLoaderReady) return;
  window.__workspaceLegacyFeatureLoaderReady = true;

  installWindowBridge("analyticsSelectTab", "jobs");
  installWindowBridge("openAssessmentModal", "profile");
  installWindowBridge("openDeepTestModal", "profile");
  installWindowBridge("openDeepTestRunnerPage", "profile");
  installWindowBridge("openDeepTestResultPage", "profile");
  installWindowBridge("toggleHistoryPanel", "profile");

  installShowSectionBridge();
  bindWorkspaceActions();
  window.ensureWorkspaceSectionReady = ensureSectionReady;
}
