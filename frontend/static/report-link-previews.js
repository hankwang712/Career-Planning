(() => {
  const cache = new Map();
  const queue = [];
  let active = 0, epoch = 0, scheduled = false;
  const apiUrl = (url) => typeof window.resolveApiUrl === "function" ? window.resolveApiUrl(url) : url;
  const userKey = () => window.getCurrentUser?.()?.username || "";
  const selector = ".career-report-source-link:not([data-preview-processed])";

  function pump() {
    while (active < 4 && queue.length) {
      const { task, resolve } = queue.shift();
      active++;
      Promise.resolve().then(task).catch(() => null).then(resolve).finally(() => { active--; pump(); });
    }
  }

  function metadata(endpoint) {
    const key = `${epoch}:${userKey()}:${endpoint}`;
    if (cache.has(key)) return cache.get(key);
    const promise = new Promise(resolve => {
      const requestEpoch = epoch;
      queue.push({ resolve, task: async () => {
        if (requestEpoch !== epoch) return null;
        const controller = new AbortController();
        let timeout;
        try {
          const request = typeof window.requestJson === "function"
            ? window.requestJson(endpoint, { signal: controller.signal })
            : fetch(apiUrl(endpoint), { credentials: "include", cache: "no-store", signal: controller.signal }).then(response => response.ok ? response.json() : null);
          const result = await Promise.race([request, new Promise(resolve => {
            timeout = setTimeout(() => { controller.abort(); resolve(null); }, 12000);
          })]);
          return result?.data || null;
        } finally { clearTimeout(timeout); }
      }});
      pump();
    });
    cache.set(key, promise);
    while (cache.size > 128) cache.delete(cache.keys().next().value);
    return promise;
  }

  async function load(card) {
    const requestEpoch = epoch, owner = userKey();
    const reportId = card.dataset.previewReportId || window.appState?.careerReport?.meta?.report_id || "";
    const params = new URLSearchParams({ url: card.href, report_id: reportId });
    if (card.dataset.previewSnapshotId) params.set("snapshot_id", card.dataset.previewSnapshotId);
    const info = await metadata(`/api/career-report/link-preview?${params}`);
    if (!card.isConnected || epoch !== requestEpoch || owner !== userKey()) return;
    card.dataset.previewState = info?.status === "ok" ? "ready" : "fallback";
    const title = card.querySelector(".report-link-title");
    const summary = card.querySelector(".report-link-description");
    if (info?.title) title.textContent = info.title;
    summary.textContent = info?.description || "打开原网页，查看完整内容";
    if (info?.site_name) card.querySelector(".report-link-site").textContent = info.site_name;
    if (info?.image_url) {
      const imageUrl = new URL(apiUrl(info.image_url), location.href);
      const apiBase = new URL(apiUrl("/api/career-report/link-preview/image"), location.href);
      if (imageUrl.origin !== apiBase.origin || imageUrl.pathname !== apiBase.pathname) return;
      const image = document.createElement("img");
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("load", () => card.classList.add("has-image"), { once: true });
      image.addEventListener("error", () => image.remove(), { once: true });
      image.src = imageUrl.href;
      card.querySelector(".report-link-media").appendChild(image);
    }
  }

  const visible = typeof IntersectionObserver === "function" ? new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) { visible.unobserve(entry.target); void load(entry.target); }
    }
  }, { rootMargin: "180px" }) : null;

  function enhance(anchor) {
    const paragraph = anchor.closest("p");
    // Keep citations inside sentences and table cells compact.
    if (!paragraph || paragraph.textContent.trim() !== anchor.textContent.trim() || paragraph.querySelectorAll("a").length !== 1 || paragraph.querySelector("img, pre, code")) return;
    let url;
    try { url = new URL(anchor.href); } catch { return; }
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return;
    const label = anchor.textContent.trim();
    anchor.classList.add("report-link-card");
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.referrerPolicy = "no-referrer";
    anchor.dataset.previewState = "loading";
    anchor.innerHTML = '<span class="report-link-media" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="4" y="5" width="24" height="22" rx="4"/><path d="M4 12h24M9 8.5h.01M12 8.5h.01M13 21l3-3m-6 6 3-3m3-3 3-3m-6 0h6v6"/></svg></span><span class="report-link-content"><span class="report-link-source"></span><strong class="report-link-title"></strong><span class="report-link-description">正在读取网页摘要…</span><span class="report-link-footer"><span class="report-link-site"></span><span>打开网页 ↗</span></span></span>';
    anchor.querySelector(".report-link-source").textContent = url.hostname + (url.pathname === "/" ? "" : url.pathname);
    anchor.querySelector(".report-link-title").textContent = label || url.hostname;
    anchor.querySelector(".report-link-site").textContent = url.hostname;
    if (visible) visible.observe(anchor);
    else void load(anchor);
  }

  function scan() {
    scheduled = false;
    // Old reports may contain a URL on its own line instead of a Markdown link.
    document.querySelectorAll(".career-report-md-article p, .report-editor-md-article-body p").forEach(paragraph => {
      if (paragraph.children.length || !/^https?:\/\/\S+$/.test(paragraph.textContent.trim())) return;
      const anchor = document.createElement("a");
      anchor.className = "career-report-source-link";
      anchor.href = paragraph.textContent.trim();
      anchor.textContent = anchor.href;
      paragraph.replaceChildren(anchor);
    });
    document.querySelectorAll(selector).forEach(anchor => {
      anchor.dataset.previewProcessed = "true";
      enhance(anchor);
    });
  }

  const schedule = () => { if (!scheduled) { scheduled = true; requestAnimationFrame(scan); } };
  function init() {
    new MutationObserver(records => {
      if (records.some(record => [...record.addedNodes].some(node => node.nodeType === 1 && (node.matches(selector) || node.querySelector(selector) || node.matches(".career-report-md-article, .report-editor-md-article-body") || node.querySelector(".career-report-md-article, .report-editor-md-article-body"))))) schedule();
      // Removed previews should not be retained by IntersectionObserver.
      for (const record of records) for (const node of record.removedNodes) {
        if (node.nodeType !== 1) continue;
        if (node.matches(".report-link-card")) visible?.unobserve(node);
        node.querySelectorAll(".report-link-card").forEach(card => visible?.unobserve(card));
      }
    }).observe(document.body, { childList: true, subtree: true });
    schedule();
  }
  window.addEventListener("app:auth-changed", () => { epoch++; cache.clear(); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
