// 设置面板与首页动效
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function openSettingsPanel() {}

function closeSettingsPanel() {}

async function openModelPicker(onReady) {
  let config = null;
  try {
    config = await fetchLlmStatus();
  } catch (error) {
    console.error("read model status failed", error);
  }
  if (config && config.configured) {
    if (typeof onReady === "function") onReady();
    return;
  }
  showToast("模型尚未配置", "请联系部署人员在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL 后重启。", "warning", 3200);
}

function closeModelPicker() {}

/* =========================================================
   Product Website Redesign — GSAP 动画与交互增强
   ========================================================= */
function initHeroProductParallax() {
  const hero = document.getElementById("productHero");
  const orb1 = document.getElementById("gradient-orb-1");
  const orb2 = document.getElementById("gradient-orb-2");
  const orb3 = document.getElementById("gradient-orb-3");
  if (!hero || !orb1 || !orb2) return;

  hero.addEventListener("mousemove", (e) => {
    const rect = hero.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;

    orb1.style.left = `${-5 + x * 8}%`;
    orb1.style.top = `${-10 + y * 8}%`;
    orb2.style.right = `${-10 + x * 12}%`;
    orb2.style.top = `${20 + y * 10}%`;
    if (orb3) {
      orb3.style.left = `${30 + x * 6}%`;
      orb3.style.bottom = `${-15 + y * 8}%`;
    }
  }, { passive: true });
}

function initHeroProductGsapAnimations() {
  if (typeof gsap === "undefined") return;

  const tl = gsap.timeline({ defaults: { ease: "power3.out" } });

  tl.fromTo("#productHero .cs-hero-product-badge",
    { opacity: 0, y: 20 },
    { opacity: 1, y: 0, duration: 0.6 }
  )
  .fromTo("#heroBrandTitle",
    { opacity: 0, y: 26 },
    { opacity: 1, y: 0, duration: 0.65 },
    "-=0.35"
  )
  .fromTo("#heroBrandSubEn",
    { opacity: 0, y: 16 },
    { opacity: 1, y: 0, duration: 0.5 },
    "-=0.4"
  )
  .fromTo(".cs-hero-brand-zh",
    { opacity: 0 },
    { opacity: 1, duration: 0.4 },
    "-=0.35"
  )
  .fromTo(".cs-hero-search-wrap",
    { opacity: 0, y: 18 },
    { opacity: 1, y: 0, duration: 0.55 },
    "-=0.3"
  )
  .fromTo("#productHero .cs-hero-product-actions .cs-btn-product",
    { opacity: 0, y: 15 },
    { opacity: 1, y: 0, duration: 0.5, stagger: 0.08 },
    "-=0.35"
  )
  .fromTo("#productHero .cs-product-stat",
    { opacity: 0, y: 22 },
    { opacity: 1, y: 0, duration: 0.55, stagger: 0.07 },
    "-=0.3"
  )
  .fromTo("#productHero .cs-hero-product-visual",
    { opacity: 0, scale: 0.96, y: 24 },
    { opacity: 1, scale: 1, y: 0, duration: 0.85 },
    "-=0.75"
  )
  .fromTo(".cs-hero-pulse",
    { opacity: 0, y: 18 },
    { opacity: 1, y: 0, duration: 0.55 },
    "-=0.55"
  )
  .fromTo(".cs-product-quickbar",
    { opacity: 0, y: 36 },
    { opacity: 1, y: 0, duration: 0.7 },
    "-=0.5"
  );
}

function initProductSvgAnimations() {
  if (typeof gsap === "undefined") return;

  gsap.utils.toArray("#productHero .product-nodes circle").forEach((node, i) => {
    gsap.fromTo(node,
      { scale: 0, opacity: 0, transformOrigin: "center center" },
      { scale: 1, opacity: 1, duration: 0.5, delay: 0.8 + i * 0.12, ease: "back.out(1.7)" }
    );
    gsap.to(node, {
      scale: 1.3,
      opacity: 0.6,
      duration: 1.6,
      repeat: -1,
      yoyo: true,
      ease: "sine.inOut",
      delay: 1.4 + i * 0.12
    });
  });

  const nodesEl = document.querySelector(".product-nodes");
  const path = nodesEl && nodesEl.previousElementSibling && nodesEl.previousElementSibling.tagName.toLowerCase() === "path"
    ? nodesEl.previousElementSibling
    : null;
  if (path && path.getTotalLength) {
    const length = path.getTotalLength();
    gsap.set(path, { strokeDasharray: length, strokeDashoffset: length });
    gsap.to(path, { strokeDashoffset: 0, duration: 1.8, ease: "power2.inOut", delay: 0.4 });
  }

  const figure = document.querySelector(".product-figure");
  if (figure) {
    gsap.fromTo(figure,
      { opacity: 0, x: -15 },
      { opacity: 1, x: 0, duration: 0.9, delay: 0.5, ease: "power2.out" }
    );
  }

  gsap.utils.toArray(".product-card-float").forEach((card, i) => {
    gsap.fromTo(card,
      { opacity: 0, y: 20 },
      { opacity: 1, y: 0, duration: 0.7, delay: 1 + i * 0.2, ease: "power2.out" }
    );
    gsap.to(card, {
      y: "-=6",
      duration: 3 + i,
      repeat: -1,
      yoyo: true,
      ease: "sine.inOut",
      delay: 1.5 + i * 0.3
    });
  });
}

function initDashboardHeroSearch() {
  const el = document.getElementById("dashboardHeroSearch");
  const btn = document.getElementById("dashboardHeroSearchBtn");
  const go = () => {
    showSection("jobs");
    void openDatasetBrowser({ query: el?.value || "" });
  };
  if (el && el.dataset.bound !== "1") {
    el.dataset.bound = "1";
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        go();
      }
    });
  }
  if (btn && btn.dataset.bound !== "1") {
    btn.dataset.bound = "1";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      go();
    });
  }
}

function initCareerNewsGsapAnimations() {
  if (typeof gsap === "undefined") return;

  const track = document.getElementById("careerNewsGridBoard");
  if (!track) return;

  const cards = track.querySelectorAll(".career-news-item");
  if (cards.length) {
    gsap.fromTo(cards,
      { opacity: 0, y: 30, rotateX: 6 },
      { opacity: 1, y: 0, rotateX: 0, duration: 0.6, stagger: 0.08, ease: "power2.out", clearProps: "transform" }
    );
  }

  track.addEventListener("scroll", updateCareerNewsTrackProgress, { passive: true });
  updateCareerNewsTrackProgress();
}

function updateCareerNewsTrackProgress() {
  const track = document.getElementById("careerNewsFeatured");
  const bar = document.getElementById("careerNewsTrackBar")?.querySelector("span");
  if (!track || !bar) return;
  const max = Math.max(1, track.scrollWidth - track.clientWidth);
  const pct = Math.min(100, Math.max(0, (track.scrollLeft / max) * 100));
  bar.style.width = `${pct}%`;
}
