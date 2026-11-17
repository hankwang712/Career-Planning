// 岗位列表、详情弹层、图表与实时引擎
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

async function loadJobs() {
  const loading = document.getElementById("jobsLoading");
  const grid = document.getElementById("jobGrid");
  const pager = document.getElementById("jobPagination");
  if (loading) loading.classList.remove("hidden");
  if (grid) grid.classList.add("hidden");
  if (pager) pager.classList.add("hidden");

  try {
    const geoAssetsPromise = ensureJobsGeoAssets().catch((error) => {
      console.warn("jobs geo assets failed to load", error);
      return null;
    });
    let jobsBootstrap = null;
    try {
      jobsBootstrap = await fetchJsonWithSessionCache("/api/jobs?view=bootstrap&city=all", `${JOBS_LIST_CACHE_PREFIX}bootstrap`);
    } catch (bootstrapError) {
      console.warn("jobs bootstrap endpoint unavailable, fallback to legacy requests", bootstrapError);
    }
    let cities = [];
    let jobs = [];
    if (Array.isArray(jobsBootstrap?.cities) && Array.isArray(jobsBootstrap?.jobs)) {
      cities = jobsBootstrap.cities;
      jobs = jobsBootstrap.jobs;
      jobsAnalyticsBossCities = Array.isArray(jobsBootstrap.boss_cities) ? jobsBootstrap.boss_cities : null;
      jobsAnalyticsCitySupplementExtra =
        jobsBootstrap.city_supplement_extra_count && typeof jobsBootstrap.city_supplement_extra_count === "object"
          ? jobsBootstrap.city_supplement_extra_count
          : null;
    } else {
      const [citiesData, jobsData] = await Promise.all([
        fetchJsonWithSessionCache("/api/cities", JOBS_CITIES_CACHE_KEY, 60 * 60 * 1000),
        fetchJsonWithSessionCache("/api/jobs?city=all&view=summary", `${JOBS_LIST_CACHE_PREFIX}all`)
      ]);
      cities = Array.isArray(citiesData) ? citiesData : [];
      jobs = Array.isArray(jobsData) ? jobsData : [];
      jobsAnalyticsBossCities = null;
      jobsAnalyticsCitySupplementExtra = null;
    }
    const citySelect = document.getElementById("cityFilter");
    if (citySelect) {
      citySelect.innerHTML = '<option value="all">全部城市</option>';
      cities.forEach((city) => {
        const option = document.createElement("option");
        option.value = city;
        option.textContent = city;
        citySelect.appendChild(option);
      });
    }

    allJobsData = jobs;
    filteredJobsData = [...allJobsData];
    fuseIndex = null;
    appState.lastJobFilterKey = "";

    const industrySet = new Set(allJobsData.map((job) => job["公司行业"]).filter(Boolean));
    const industrySel = document.getElementById("industryFilter");
    if (industrySel) {
      industrySel.innerHTML = '<option value="all">全部行业</option>';
      [...industrySet].sort().forEach((industry) => {
        const option = document.createElement("option");
        option.value = industry;
        option.textContent = industry;
        industrySel.appendChild(option);
      });
    }

    if (loading) loading.classList.add("hidden");
    filterJobs(true);
    geoAssetsPromise.then(() => scheduleGeoInsightsInit(allJobsData));
    scheduleAnalyticsInit(allJobsData);

    const summary = document.getElementById("jobFilterSummary");
    if (summary) summary.textContent = `已加载 ${allJobsData.length} 个岗位摘要`;
  } catch (err) {
    if (loading) {
      loading.innerHTML = `<p class="text-red-500">无法连接数据服务<br><span class="text-xs text-gray-400">${escHtml(err.message)}</span></p>`;
    }
  }
}

function filterJobs(silent = false) {
  if (allJobsData.length === 0) return;
  const query = (document.getElementById("jobSearch")?.value || "").trim();
  const cityVal = document.getElementById("cityFilter")?.value || "all";
  const industryVal = document.getElementById("industryFilter")?.value || "all";
  const filterKey = `${query}__${cityVal}__${industryVal}__${allJobsData.length}`;
  if (filterKey === appState.lastJobFilterKey) return;
  appState.lastJobFilterKey = filterKey;
  if (cityVal !== "all" && typeof window.syncJobGeoSelectionWithCity === "function") {
    window.syncJobGeoSelectionWithCity(cityVal);
  }

  let queryResult = allJobsData;
  if (query) {
    buildJobSearchIndex();
    if (fuseIndex) {
      queryResult = fuseIndex.search(query).map((item) => item.item);
      if (queryResult.length === 0) {
        const lowerQuery = query.toLowerCase();
        queryResult = allJobsData.filter((job) =>
          [job["岗位名称"], job["公司名称"], job["技能要求"], job["职位类别"], job["公司行业"]]
            .join(" ")
            .toLowerCase()
            .includes(lowerQuery)
        );
      }
    }
  }

  filteredJobsData = queryResult.filter((job) => {
    const okCity = cityVal === "all" || (job["采集城市"] || job["城市"] || "") === cityVal;
    const okIndustry = industryVal === "all" || (job["公司行业"] || "") === industryVal;
    return okCity && okIndustry;
  });

  jobCurrentPage = 1;
  renderJobCards();

  const summary = document.getElementById("jobFilterSummary");
  if (summary) summary.textContent = `当前显示 ${filteredJobsData.length} / ${allJobsData.length} 个岗位`;
  if (!silent) {
    addLiveActivity(`岗位筛选完成：共 ${filteredJobsData.length} 个结果`);
  }
}

function renderJobCards() {
  const grid  = document.getElementById("jobGrid");
  const pager = document.getElementById("jobPagination");
  if (!grid) return;

  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  const start      = (jobCurrentPage - 1) * JOB_PAGE_SIZE;
  const pageData   = filteredJobsData.slice(start, start + JOB_PAGE_SIZE);

  if (total === 0) {
    grid.innerHTML = `<div class="col-span-3 py-16 text-center text-gray-400">
      <p class="text-4xl mb-3">馃攳</p>
      <p class="text-lg font-medium text-gray-500">没有找到匹配的岗位</p>
      <p class="text-sm mt-1">试试调整搜索关键词或城市筛选</p>
    </div>`;
    grid.classList.remove("hidden");
    pager.classList.add("hidden");
    return;
  }

grid.innerHTML = pageData.map((job, i) => {
    const idx     = start + i;
    const skills  = String(job["技能要求"] || "").split(",").map((s) => s.trim()).filter(Boolean);
    const skillTags = skills.slice(0, 5).map(s =>
      `<span class="job-skill-tag whitespace-nowrap">${escHtml(s)}</span>`
    ).join("") + (skills.length > 5 ? `<span class="job-skill-tag job-skill-tag-more">+${skills.length - 5}</span>` : "");

    const fundingColors = {
      "已上市": "bg-blue-100 text-blue-700",
      "D轮及以上": "bg-indigo-100 text-indigo-700",
      "C轮": "bg-violet-100 text-violet-700",
      "B轮": "bg-purple-100 text-purple-700",
      "A轮": "bg-fuchsia-100 text-fuchsia-700",
      "天使轮": "bg-pink-100 text-pink-700"
    };
    const fundingCls = fundingColors[job["融资阶段"]] || "bg-gray-100 text-gray-500";

    return `
    <div class="job-card-real job-card-shell glass-surface p-5 cursor-pointer"
         onclick="openJobModal(${idx})">
      <!-- 标题 + 薪资 -->
      <div class="flex justify-between items-start mb-2 gap-3">
        <h3 class="job-card-title line-clamp-2 flex-1">${escHtml(job["岗位名称"] || "--")}</h3>
        <span class="job-card-salary flex-shrink-0 mt-0.5">${escHtml(job["薪资"] || "面议")}</span>
      </div>
      <!-- 公司 -->
      <p class="job-card-company mb-3 truncate">${escHtml(job["公司名称"] || "")}</p>
      <!-- 城市 / 经验 / 学历 -->
      <div class="flex flex-wrap gap-1.5 mb-3">
        <span class="job-meta-chip is-city whitespace-nowrap">城市 ${escHtml(job["城市"] || job["采集城市"] || "")}</span>
        <span class="job-meta-chip whitespace-nowrap">${escHtml(job["经验要求"] || "")}</span>
        <span class="job-meta-chip whitespace-nowrap">学历 ${escHtml(job["学历要求"] || "")}</span>
      </div>
      <!-- 技能标签 -->
      <div class="job-skill-row mb-4">${skillTags}</div>
      <!-- 底部：公司信息 -->
      <div class="job-card-footer">
        <span class="job-company-meta truncate">${escHtml(job["公司规模"] || "")} · ${escHtml(job["公司行业"] || "")}</span>
        <span class="job-stage-chip flex-shrink-0 ml-2 ${fundingCls}">${escHtml(job["融资阶段"] || "")}</span>
      </div>
    </div>`;
  }).join("");

  grid.classList.remove("hidden");

  // 分页
  const prevBtn  = document.getElementById("jobPrevBtn");
  const nextBtn  = document.getElementById("jobNextBtn");
  const pageInfo = document.getElementById("jobPageInfo");
  if (pager) {
    pager.classList.remove("hidden");
    if (prevBtn)  prevBtn.disabled  = jobCurrentPage <= 1;
    if (nextBtn)  nextBtn.disabled  = jobCurrentPage >= totalPages;
    if (pageInfo) pageInfo.textContent = `第 ${jobCurrentPage} / ${totalPages} 页 · 共 ${total} 个岗位`;
  }
}

function jobChangePage(delta) {
  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  jobCurrentPage   = Math.max(1, Math.min(totalPages, jobCurrentPage + delta));
  renderJobCards();
  document.getElementById("jobs")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

async function openJobModal(idx) {
  let job = filteredJobsData[idx];
  if (!job) return;

  if (job.job_id) {
    try {
      job = await getJobDetail(job.job_id);
    } catch (error) {
      showToast("岗位详情加载失败", error.message, "warning", 2200);
    }
  }

  const companyName = job["公司名称"] || "--";
  const jobTitle = job["岗位名称"] || "--";

  const avatar = document.getElementById("jobModalAvatar");
  if (avatar) {
    const firstChar = companyName.charAt(0) || "?";
    avatar.textContent = firstChar;
    const hue = (firstChar.charCodeAt(0) * 37) % 360;
    avatar.style.background = `hsla(${hue},55%,55%,0.35)`;
  }

  document.getElementById("jobModalTitle").textContent = jobTitle;
  document.getElementById("jobModalCompany").textContent = companyName;
  document.getElementById("jobModalSalary").textContent = job["薪资"] || "面议";

  const meta = document.getElementById("jobModalMeta");
  const metaItems = [
    ["地点", job["城市"] || job["采集城市"]],
    ["经验", job["经验要求"]],
    ["学历", job["学历要求"]],
    ["行业", job["公司行业"]]
  ].filter(([, value]) => value);
  meta.innerHTML = metaItems.map(([label, text]) =>
    `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs text-white/80 whitespace-nowrap"
           style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.2)">
       ${escHtml(label)} ${escHtml(text)}
     </span>`
  ).join("");

  const skills = String(job["技能要求"] || "").split(",").map((item) => item.trim()).filter(Boolean);
document.getElementById("jobModalSkills").innerHTML = skills.length
    ? skills.map((skill) =>
        `<span class="job-modal-skill">${escHtml(skill)}</span>`
      ).join("")
    : `<span class="text-gray-400 text-sm">暂无标签</span>`;

  document.getElementById("jobModalDesc").textContent = job["岗位描述"] || "暂无描述";

  const compInfo = document.getElementById("jobModalCompanyInfo");
  const compFields = [
    { icon: "融资", label: "融资阶段", val: job["融资阶段"] },
    { icon: "规模", label: "公司规模", val: job["公司规模"] },
    { icon: "行业", label: "所属行业", val: job["公司行业"] }
  ];
  compInfo.innerHTML = compFields.map(({ icon, label, val }) => `
    <div class="rounded-xl p-3 text-center" style="background:#f8f5ff;border:1px solid #ede9fe">
      <p class="text-lg mb-0.5">${icon}</p>
      <p class="text-xs font-semibold text-violet-700 leading-tight">${escHtml(val || "--")}</p>
      <p class="text-xs text-gray-400 mt-0.5">${label}</p>
    </div>`).join("");
  document.getElementById("jobModalCompanyDesc").textContent = job["公司简介"] || "";

  const addr = document.getElementById("jobModalAddr");
  if (addr) addr.textContent = job["工作地址"] || "暂无地址信息";

  const welfares = String(job["公司福利"] || "").split(",").map((item) => item.trim()).filter(Boolean);
  document.getElementById("jobModalWelfare").innerHTML = welfares.length
    ? welfares.map((welfare) => {
        const icon = welfareIcons[welfare] || "✓";
        return `<span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full font-medium"
                      style="background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0">
                  ${icon} ${escHtml(welfare)}
                </span>`;
      }).join("")
    : `<span class="text-gray-400 text-xs">暂无福利信息</span>`;

  const modal = document.getElementById("jobModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  document.body.style.overflow = "hidden";
}

function closeJobModal() {
  const modal = document.getElementById("jobModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  document.body.style.overflow = "";
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
  initNavWorkspaceMenu();
  const notificationBtn = document.getElementById("notificationBtn");
  if (notificationBtn) {
    notificationBtn.addEventListener("click", () => {
      closeNavWorkspaceMenu();
      const unread = appState.notifications;
      if (unread > 0) {
        showToast("Notifications", `You have ${unread} new update(s).`, "info", 1600);
        addLiveActivity(`Notification center opened (${unread})`);
      } else {
        showToast("Notifications", "No new updates.", "info", 1400);
      }
      appState.notifications = Math.max(0, unread - 1);
      updateNotificationCount();
    });
  }

  const searchInput = document.getElementById("jobSearch");
  if (searchInput) {
    // 实时输入时直接触发筛选。
    searchInput.addEventListener("input", () => filterJobs());
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        filterJobs();
      }
    });
  }

  const industryFilter = document.getElementById("industryFilter");
  const cityFilter = document.getElementById("cityFilter");
  if (industryFilter) {
    industryFilter.addEventListener("change", () => filterJobs());
  }
  if (cityFilter) {
    cityFilter.addEventListener("change", () => filterJobs());
  }

}

function startRealtimeEngine() {
  if (appState.timersStarted) return;
  appState.timersStarted = true;
  updateLiveClock();
  setInterval(updateLiveClock, 1000);
  setInterval(() => {
    const msg = liveActivityTemplates[Math.floor(Math.random() * liveActivityTemplates.length)];
    addLiveActivity(msg);
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
  }, 20000);
}
