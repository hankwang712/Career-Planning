/* 智航生涯 · Chart Room 动效层
   原则：一次有编排的入场（每个区块首次出现时），其余动效只回应操作。
   不依赖 GSAP；prefers-reduced-motion 时全部静态呈现。
   加载位置：body 末尾、所有 app-* 脚本之后（链在 app-boot 的 showSection 包装之后）。 */
(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const EASE_MS = 550;

  /* 把一组元素按次序淡入上移；结束后清理类名，交还给各自的 hover 过渡。 */
  function revealGroup(elements, stagger = 60) {
    const items = elements.filter((el) => el && !el.classList.contains("dr-pre"));
    if (!items.length) return;
    items.forEach((el) => el.classList.add("dr-pre"));
    void document.body.offsetWidth; // 强制回流，确保过渡生效
    items.forEach((el, i) => {
      el.style.transitionDelay = `${i * stagger}ms`;
      el.classList.add("dr-in");
    });
    const total = EASE_MS + items.length * stagger + 120;
    window.setTimeout(() => {
      items.forEach((el) => {
        el.classList.remove("dr-pre", "dr-in");
        el.style.transitionDelay = "";
      });
    }, total);
  }

  function visibleChildren(section, limit = 8) {
    if (!section) return [];
    return [...section.children]
      .filter((el) => !el.classList.contains("hidden") && el.offsetParent !== null)
      .slice(0, limit);
  }

  /* 数字滚动：只处理纯数字/百分比读数，一次性。 */
  function countUp(el, duration = 900) {
    if (!el || el.dataset.drCounted === "1") return;
    const raw = (el.textContent || "").trim();
    const match = raw.match(/^(\d+)(%?)$/);
    if (!match) return;
    el.dataset.drCounted = "1";
    const target = Number(match[1]);
    const suffix = match[2];
    if (reduceMotion || target === 0) { el.textContent = raw; return; }
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = Math.round(target * eased) + suffix;
      if (t < 1) requestAnimationFrame(tick);
      else el.textContent = raw;
    };
    el.classList.add("dr-count");
    requestAnimationFrame(tick);
  }

  function countHeroStats() {
    ["pendingTaskCount", "exploredJobsCount", "topMatchRate", "dashboardScore"].forEach((id, i) => {
      const el = document.getElementById(id);
      if (el) window.setTimeout(() => countUp(el), i * 120);
    });
  }

  /* B-1 修复：导航选中态在点击当帧更新（capture 先于 onclick），
     与区块数据渲染解耦——下划线/颜色即时响应，不等重渲染。 */
  function initImmediateNav() {
    const strip = document.querySelector("nav.app-topbar .nav-tab-strip");
    if (!strip) return;
    strip.addEventListener("click", (e) => {
      const btn = e.target.closest(".nav-item");
      if (!btn) return;
      strip.querySelectorAll(".nav-item").forEach((item) => {
        const on = item === btn;
        item.classList.toggle("active", on);
        if (on) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
      });
    }, true);
  }

  /* 区块切换不做整屏隐藏式入场（曾造成约 2s 反馈真空）；
     仅 dashboard 首显补数字滚动，其余交给应用自身 fade 与滚动揭示。 */
  const seenSections = new Set();
  function onSectionShown(sectionId) {
    if (reduceMotion || sectionId !== "dashboard") return;
    if (seenSections.has("dashboard")) return;
    seenSections.add("dashboard");
    // Hero 入场由既有 GSAP 时间线负责；这里只补数字滚动。
    const delay = typeof gsap !== "undefined" ? 1400 : 300;
    window.setTimeout(countHeroStats, delay);
  }

  if (typeof window.showSection === "function") {
    const previous = window.showSection;
    window.showSection = function (sectionId) {
      previous.apply(this, arguments);
      onSectionShown(sectionId);
    };
  }

  /* 惯性平滑滚动（Lenis）：与 GSAP ticker 同步；嵌套滚动容器保持原生 */
  function initSmoothScroll() {
    if (reduceMotion || typeof Lenis === "undefined") return;
    const lenis = new Lenis({
      duration: 1.05,
      easing: (t) => 1 - Math.pow(1 - t, 3),
      smoothWheel: true,
      prevent: (node) => Boolean(node.closest && node.closest(".modal-overlay, .conversation-scroll, [data-lenis-prevent]"))
    });
    window.__drLenis = lenis;
    if (window.gsap && window.ScrollTrigger) {
      lenis.on("scroll", window.ScrollTrigger.update);
      window.gsap.ticker.add((time) => lenis.raf(time * 1000));
      window.gsap.ticker.lagSmoothing(0);
    } else {
      const raf = (time) => { lenis.raf(time); requestAnimationFrame(raf); };
      requestAnimationFrame(raf);
    }
  }

  /* 指挥台面板跟随指针的微光：仪器感，仅深色 hero */
  function initHeroSheen() {
    const hero = document.getElementById("productHero");
    if (!hero || reduceMotion) return;
    hero.addEventListener("pointermove", (e) => {
      const r = hero.getBoundingClientRect();
      hero.style.setProperty("--mx", (((e.clientX - r.left) / r.width) * 100).toFixed(2) + "%");
      hero.style.setProperty("--my", (((e.clientY - r.top) / r.height) * 100).toFixed(2) + "%");
    }, { passive: true });
  }

  /* 滚动进入视口时的一次性揭示（只针对未被既有动画覆盖的卡片） */
  function initScrollReveals() {
    if (reduceMotion) return;
    /* 新闻卡片由应用既有 GSAP 时间线负责，这里不重复接管，避免互相覆盖 */
    const targets = [...document.querySelectorAll(
      ".cs-career-process-step, .cs-product-feature-card, .report-setup-card, .assessment-center-card"
    )];
    if (!targets.length) return;
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((entries) => {
      const batch = entries.filter((e) => e.isIntersecting).map((e) => e.target);
      if (!batch.length) return;
      batch.forEach((el) => io.unobserve(el));
      revealGroup(batch, 80);
    }, { threshold: 0.15, rootMargin: "0px 0px -6% 0px" });
    targets.forEach((el) => io.observe(el));
  }

  /* 个人中心 / 招聘 / 设置：加载时的一次编排（登录页已退役，无启动遮罩编排） */
  function initPageEntrance() {
    if (reduceMotion) return;
    if (document.body.classList.contains("user-center-page")) {
      const surfaces = [...document.querySelectorAll(".uc-main .uc-surface, .uc-content .uc-surface")].slice(0, 6);
      revealGroup(surfaces.length ? surfaces : visibleChildren(document.querySelector("main"), 6), 80);
      return;
    }
    const recruitment = document.querySelector(".recruitment-main");
    if (recruitment) {
      // 首个子节点（标题区）保持即现，避免首绘空窗；其余软入场
      revealGroup(visibleChildren(recruitment, 6).slice(1), 80);
      return;
    }
    const settings = document.querySelector(".sc-main");
    if (settings) { revealGroup(visibleChildren(settings, 6), 80); }
  }

  /* 图表默认字体与墨色，跟随设计令牌（仅影响此后创建的图表实例） */
  function initChartDefaults() {
    if (!window.Chart) return;
    const stack = getComputedStyle(document.documentElement).getPropertyValue("--app-font-stack").trim();
    if (stack) window.Chart.defaults.font.family = stack;
    window.Chart.defaults.color = "#5c6b84";
    window.Chart.defaults.borderColor = "rgba(23, 35, 59, 0.08)";
  }

  function boot() {
    initChartDefaults();
    initImmediateNav();
    initSmoothScroll();
    initHeroSheen();
    initPageEntrance();
    initScrollReveals();
    // 初始哈希可能直接落在非 dashboard 区块
    const hash = (location.hash || "").replace("#", "");
    const dashboard = document.getElementById("dashboard");
    if (hash && document.getElementById(hash)) onSectionShown(hash);
    else if (dashboard && dashboard.offsetParent !== null) onSectionShown("dashboard");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();