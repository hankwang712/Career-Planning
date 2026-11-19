// 设置面板与首页动效
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function openSettingsPanel() {
  window.location.assign("/system-settings");
}

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
  openSettingsPanel();
}

function closeModelPicker() {}

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
