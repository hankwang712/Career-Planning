// 图表、动画与实时引擎
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function initCharts() {
  const radarCanvas = document.getElementById("radarChart");
  const profileRadarCanvas = document.getElementById("profileRadarChart");
  if (radarCanvas && window.Chart) {
    // 防止重复创建（canvas 已被 Chart.js 占用时先销毁旧实例）
    if (appState.dashboardRadarChart) { appState.dashboardRadarChart.destroy(); appState.dashboardRadarChart = null; }
    appState.dashboardRadarChart = new Chart(radarCanvas.getContext("2d"), {
      type: "radar",
      data: {
        labels: ["专业技能", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历"],
        datasets: [
          { label: "当前能力", data: [75, 82, 88, 70, 65, 60], backgroundColor: "rgba(102,126,234,0.2)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)" },
          { label: "岗位要求", data: [85, 75, 80, 75, 70, 75], backgroundColor: "rgba(118,75,162,0.2)", borderColor: "rgba(118,75,162,1)", borderWidth: 2, pointBackgroundColor: "rgba(118,75,162,1)" }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 12 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { position: "top", labels: { usePointStyle: true } } } }
    });
  }
  if (profileRadarCanvas && window.Chart) {
    if (appState.profileRadarChart) { appState.profileRadarChart.destroy(); appState.profileRadarChart = null; }
    appState.profileRadarChart = new Chart(profileRadarCanvas.getContext("2d"), {
      type: "radar",
      data: { labels: ["专业技能", "证书资质", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历", "项目经验"], datasets: [{ label: "能力评分", data: [75, 60, 82, 88, 70, 65, 60, 55], backgroundColor: "rgba(102,126,234,0.3)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)", pointRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 11 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { display: false } } }
    });
  }
}

function initAnimations() {
  const bars = document.querySelectorAll(".progress-bar");
  bars.forEach((bar) => {
    const w = bar.style.width;
    bar.style.width = "0";
    setTimeout(() => { bar.style.width = w; }, 400);
  });
  const modal = document.getElementById("jobDetailModal");
  if (modal) modal.addEventListener("click", function (e) { if (e.target === this) closeModal("jobDetailModal"); });
  if (typeof IntersectionObserver !== "undefined") {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("slide-in");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".glass-surface, .cs-panel, .cs-feature-card, .career-news-item").forEach((el) => observer.observe(el));
  }
}

function bindGlobalEvents() {
}

function startRealtimeEngine() {
  if (appState.timersStarted) return;
  appState.timersStarted = true;
  updateLiveClock();
  setInterval(updateLiveClock, 1000);
  setInterval(() => {
    const msg = liveActivityTemplates[Math.floor(Math.random() * liveActivityTemplates.length)];
    addLiveActivity(msg);
  }, 20000);
}
