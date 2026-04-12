(function () {
  const CITY_PROVINCE_MAP = Object.freeze({
    "北京": "北京",
    "上海": "上海",
    "天津": "天津",
    "重庆": "重庆",
    "广州": "广东",
    "深圳": "广东",
    "杭州": "浙江",
    "厦门": "福建",
    "武汉": "湖北",
    "长沙": "湖南",
    "成都": "四川",
    "西安": "陕西",
    "郑州": "河南",
    "苏州": "江苏"
  });

  const BACHELOR_PLUS = new Set(["本科", "硕士", "博士"]);
  const EMPTY_HTML = '<p class="jobs-geo-empty">当前维度暂无足够样本。</p>';

  const HIGH_VALUE_BENEFITS = new Set([
    "股票期权", "期权", "上市公司", "13薪", "14薪", "15薪", "16薪",
    "年终奖", "年底双薪", "双薪", "绩效奖金", "季度奖金"
  ]);

  const CITY_COORDS = Object.freeze({
    "北京": [116.41, 39.90], "上海": [121.47, 31.23],
    "天津": [117.19, 39.13], "重庆": [106.55, 29.57],
    "广州": [113.27, 23.13], "深圳": [114.06, 22.54],
    "杭州": [120.15, 30.27], "厦门": [118.10, 24.46],
    "武汉": [114.31, 30.52], "长沙": [112.98, 28.21],
    "成都": [104.07, 30.67], "西安": [108.93, 34.27],
    "郑州": [113.65, 34.76], "苏州": [120.59, 31.30]
  });

  const state = {
    chart: null,
    insights: null,
    selectedProvince: "",
    selectedCity: "",
    resizeBound: false
  };

  function countUp(el, toValue, duration, formatter) {
    if (!el) return;
    const from = 0;
    const start = performance.now();
    function step(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = formatter(from + (toValue - from) * eased);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function safeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getCityName(job) {
    return String(job["采集城市"] || job["城市"] || "").trim();
  }

  function getProvinceName(city) {
    return CITY_PROVINCE_MAP[city] || "";
  }

  function parseSalary(text) {
    const raw = String(text || "").replace(/\s/g, "");
    if (!raw || raw === "面议") return null;

    const payMonths = Number((raw.match(/·(\d+)薪/) || [])[1] || 12);
    const isDaily = /元\/天/.test(raw);
    let low = null;
    let high = null;

    if (isDaily) {
      const match = raw.match(/(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)元\/天/);
      if (!match) return null;
      low = Number(match[1]) * 30 / 1000;
      high = Number(match[2]) * 30 / 1000;
    } else {
      const rangeMatch = raw.match(/(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)K/i);
      const singleMatch = raw.match(/(\d+(?:\.\d+)?)K/i);
      if (rangeMatch) {
        low = Number(rangeMatch[1]);
        high = Number(rangeMatch[2]);
      } else if (singleMatch) {
        low = Number(singleMatch[1]);
        high = low;
      } else {
        return null;
      }
    }

    const monthlyMid = (low + high) / 2;
    return {
      raw,
      low,
      high,
      monthlyMid,
      annualizedMid: monthlyMid * payMonths / 12,
      payMonths,
      salaryType: isDaily ? "daily" : "monthly"
    };
  }

  function splitSkills(text) {
    return String(text || "")
      .split(/[，,、]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function normalizeEducation(value) {
    const text = String(value || "").trim();
    if (!text) return "未注明";
    if (text.includes("博士")) return "博士";
    if (text.includes("硕士")) return "硕士";
    if (text.includes("本科")) return "本科";
    if (text.includes("大专")) return "大专";
    return text;
  }

  function normalizeExperience(value) {
    const text = String(value || "").trim();
    if (!text) return "未注明";
    if (text.includes("在校") || text.includes("应届")) return "应届/校招";
    if (/天\/周/.test(text) || /个月/.test(text)) return "实习岗位";
    return text;
  }

  function average(values) {
    if (!values.length) return 0;
    return values.reduce((sum, item) => sum + item, 0) / values.length;
  }

  function median(values) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
  }

  function countBy(values) {
    const counts = new Map();
    values.forEach((value) => {
      const key = String(value || "未注明").trim() || "未注明";
      counts.set(key, (counts.get(key) || 0) + 1);
    });

    const total = values.length || 1;
    return [...counts.entries()]
      .map(([name, count]) => ({ name, count, ratio: count / total }))
      .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name, "zh-CN"));
  }

  function formatPercent(value) {
    if (!Number.isFinite(value)) return "--";
    return `${Math.round(value * 100)}%`;
  }

  function formatSalaryK(value) {
    if (!Number.isFinite(value) || value <= 0) return "--";
    const rounded = value >= 10 ? value.toFixed(1) : value.toFixed(1);
    return `${rounded}K`;
  }

  function formatRange(low, high) {
    if (!Number.isFinite(low) || !Number.isFinite(high) || low <= 0 || high <= 0) return "--";
    return `${low.toFixed(1)}-${high.toFixed(1)}K`;
  }

  function summarizeBucket(label, jobs) {
    const salaryRecords = jobs.map((job) => parseSalary(job["薪资"])).filter(Boolean);
    const lowValues = salaryRecords.map((item) => item.low);
    const highValues = salaryRecords.map((item) => item.high);
    const annualizedValues = salaryRecords.map((item) => item.annualizedMid);
    const dailyCount = salaryRecords.filter((item) => item.salaryType === "daily").length;
    const campusCount = jobs.filter((job) => {
      const text = String(job["经验要求"] || "");
      return text.includes("在校") || text.includes("应届") || /天\/周/.test(text);
    }).length;
    const bachelorPlusCount = jobs.filter((job) => BACHELOR_PLUS.has(normalizeEducation(job["学历要求"]))).length;

    return {
      label,
      jobCount: jobs.length,
      salaryCount: salaryRecords.length,
      averageLow: average(lowValues),
      averageHigh: average(highValues),
      averageAnnualized: average(annualizedValues),
      medianAnnualized: median(annualizedValues),
      dailyShare: salaryRecords.length ? dailyCount / salaryRecords.length : 0,
      campusShare: jobs.length ? campusCount / jobs.length : 0,
      bachelorPlusShare: jobs.length ? bachelorPlusCount / jobs.length : 0,
      experience: countBy(jobs.map((job) => normalizeExperience(job["经验要求"]))),
      education: countBy(jobs.map((job) => normalizeEducation(job["学历要求"]))),
      industries: countBy(jobs.map((job) => job["公司行业"] || "未注明")),
      skills: countBy(jobs.flatMap((job) => splitSkills(job["技能要求"]))),
      _rawJobs: jobs
    };
  }

  function buildInsights(jobs) {
    const provinceBuckets = new Map();
    const mappedCities = new Set();

    jobs.forEach((job) => {
      const city = getCityName(job);
      const province = getProvinceName(city);
      if (!city || !province) return;

      mappedCities.add(city);

      if (!provinceBuckets.has(province)) {
        provinceBuckets.set(province, {
          name: province,
          jobs: [],
          cityBuckets: new Map()
        });
      }

      const provinceBucket = provinceBuckets.get(province);
      provinceBucket.jobs.push(job);

      if (!provinceBucket.cityBuckets.has(city)) {
        provinceBucket.cityBuckets.set(city, []);
      }

      provinceBucket.cityBuckets.get(city).push(job);
    });

    const provinces = [...provinceBuckets.values()]
      .map((provinceBucket) => {
        const cities = [...provinceBucket.cityBuckets.entries()]
          .map(([city, cityJobs]) => {
            const summary = summarizeBucket(city, cityJobs);
            return {
              city,
              ...summary
            };
          })
          .sort((a, b) => (b.jobCount - a.jobCount) || (b.averageAnnualized - a.averageAnnualized));

        const provinceSummary = summarizeBucket(provinceBucket.name, provinceBucket.jobs);

        return {
          name: provinceBucket.name,
          jobCount: provinceSummary.jobCount,
          cityCount: cities.length,
          cityNames: cities.map((item) => item.city),
          averageAnnualized: provinceSummary.averageAnnualized,
          averageLow: provinceSummary.averageLow,
          averageHigh: provinceSummary.averageHigh,
          dailyShare: provinceSummary.dailyShare,
          campusShare: provinceSummary.campusShare,
          bachelorPlusShare: provinceSummary.bachelorPlusShare,
          cities,
          topSkills: provinceSummary.skills.slice(0, 8),
          topIndustries: provinceSummary.industries.slice(0, 4)
        };
      })
      .sort((a, b) => (b.jobCount - a.jobCount) || (b.averageAnnualized - a.averageAnnualized));

    return {
      totalJobs: jobs.length,
      totalCities: mappedCities.size,
      totalProvinces: provinces.length,
      provinces,
      provinceMap: new Map(provinces.map((item) => [item.name, item]))
    };
  }

  function getDefaultProvince(insights) {
    const preferred = ["广东", "北京", "上海", "浙江"];
    return preferred.find((name) => insights.provinceMap.has(name)) || (insights.provinces[0] && insights.provinces[0].name) || "";
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function renderTagList(items, limit) {
    const list = (items || []).slice(0, limit);
    if (!list.length) return EMPTY_HTML;
    return list.map((item, idx) => {
      const cls = idx === 0 ? " large" : idx < 3 ? " medium" : "";
      return `<span class="jobs-geo-tag${cls}">${safeHtml(item.name)} <strong>${item.count}</strong></span>`;
    }).join("");
  }

  function renderBarList(items, options) {
    const list = (items || []).slice(0, options.limit || items.length);
    if (!list.length) return EMPTY_HTML;
    const max = Math.max(...list.map((item) => options.value(item)), 1);

    return list.map((item) => {
      const value = options.value(item);
      const width = Math.max(8, (value / max) * 100);
      return `
        <div class="jobs-geo-bar-item">
          <div class="jobs-geo-bar-top">
            <span class="jobs-geo-bar-label">${safeHtml(options.label(item))}</span>
            <span class="jobs-geo-bar-value">${safeHtml(options.valueText(item))}</span>
          </div>
          <div class="jobs-geo-bar-track">
            <span class="jobs-geo-bar-fill" style="width:${width}%"></span>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderCityTabs(province, selectedCity) {
    const container = document.getElementById("jobGeoCityTabs");
    if (!container) return;

    container.innerHTML = province.cities.map((item) => (
      `<button type="button" class="jobs-geo-city-btn${item.city === selectedCity ? " active" : ""}" data-city="${safeHtml(item.city)}">
        ${safeHtml(item.city)} · ${item.jobCount}
      </button>`
    )).join("");

    container.querySelectorAll("[data-city]").forEach((button) => {
      button.addEventListener("click", () => {
        selectProvince(province.name, button.getAttribute("data-city"));
      });
    });
  }

  function renderProvinceComparison(province, city) {
    setText("jobGeoCompareLabel", province.cities.length > 1 ? "按平均折算月薪" : "当前城市薪资结构");

    const container = document.getElementById("jobGeoCompareList");
    if (!container) return;

    if (province.cities.length > 1) {
      container.innerHTML = renderBarList(province.cities, {
        limit: 6,
        label: (item) => `${item.city} · ${item.jobCount}岗`,
        value: (item) => item.averageAnnualized,
        valueText: (item) => formatSalaryK(item.averageAnnualized)
      });
      return;
    }

    const salaryItems = [
      { name: "平均区间下限", metric: city.averageLow },
      { name: "平均区间上限", metric: city.averageHigh },
      { name: "年化月均", metric: city.averageAnnualized },
      { name: "薪资中位值", metric: city.medianAnnualized }
    ].filter((item) => item.metric > 0);

    container.innerHTML = renderBarList(salaryItems, {
      limit: 4,
      label: (item) => item.name,
      value: (item) => item.metric,
      valueText: (item) => formatSalaryK(item.metric)
    });
  }

  function renderBenefitTicker(cityJobs) {
    const container = document.getElementById("jobGeoBenefitTicker");
    const label = document.getElementById("jobGeoBenefitLabel");
    if (!container) return;

    const counts = new Map();
    cityJobs.forEach((job) => {
      String(job["公司福利"] || "").split(/[，,]/).forEach((b) => {
        const name = b.trim();
        if (name.length >= 2 && name.length <= 10) {
          counts.set(name, (counts.get(name) || 0) + 1);
        }
      });
    });

    const sorted = [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 24)
      .map(([name, count]) => ({ name, count }));

    if (!sorted.length) {
      container.innerHTML = '<span class="jobs-geo-benefit-chip normal">暂无数据</span>';
      return;
    }

    if (label) label.textContent = `${sorted.length} 项`;

    const makeChips = () => sorted.map((item) => {
      const cls = HIGH_VALUE_BENEFITS.has(item.name) ? "high" : "normal";
      return `<span class="jobs-geo-benefit-chip ${cls}">${safeHtml(item.name)}</span>`;
    }).join("");

    container.innerHTML = makeChips() + makeChips();
    const totalW = container.scrollWidth / 2;
    container.style.setProperty("--ticker-w", `${totalW}px`);
    container.style.animation = "none";
    void container.offsetWidth;
    container.style.animation = `geo-ticker-scroll ${Math.max(12, sorted.length * 0.9)}s linear infinite`;
  }

  function renderPanel(province, city) {
    state.selectedProvince = province.name;
    state.selectedCity = city.city;

    const provLabel = document.getElementById("jobGeoProvinceLabel");
    if (provLabel) {
      provLabel.innerHTML = `<span class="jobs-geo-dot"></span>${safeHtml(province.name)} · ${province.cityCount} 个城市`;
    }
    setText("jobGeoCityTitle", city.city);
    setText(
      "jobGeoNarrative",
      `${city.city} 共收录 ${city.jobCount} 个岗位样本，平均折算月薪 ${formatSalaryK(city.averageAnnualized)}，平均薪资区间 ${formatRange(city.averageLow, city.averageHigh)}。其中 ${formatPercent(city.dailyShare)} 来自日薪岗位折算。`
    );

    const sampleEl = document.getElementById("jobGeoSampleCount");
    countUp(sampleEl, city.jobCount, 700, (v) => String(Math.round(v)));
    setText("jobGeoCoverageText", `省内累计 ${province.jobCount} 个岗位样本`);

    const salaryEl = document.getElementById("jobGeoAvgSalary");
    countUp(salaryEl, city.averageAnnualized, 800, (v) => formatSalaryK(v));
    setText("jobGeoSalaryText", `均值区间 ${formatRange(city.averageLow, city.averageHigh)} · 中位 ${formatSalaryK(city.medianAnnualized)}`);

    const annualTag = document.getElementById("jobGeoAnnualTag");
    const annualEl = document.getElementById("jobGeoAnnualSalary");
    if (annualTag && annualEl && city.averageAnnualized > 0) {
      const annualK = city.averageAnnualized * 12;
      annualTag.style.display = "";
      countUp(annualEl, annualK, 900, (v) => {
        const w = v / 10000;
        return w >= 10 ? `${w.toFixed(1)}万` : `${(v / 1000).toFixed(1)}K`;
      });
    } else if (annualTag) {
      annualTag.style.display = "none";
    }

    const campusEl = document.getElementById("jobGeoCampusShare");
    countUp(campusEl, city.campusShare * 100, 700, (v) => `${Math.round(v)}%`);
    setText("jobGeoCampusText", `日薪折算样本 ${formatPercent(city.dailyShare)}`);

    const degreeEl = document.getElementById("jobGeoDegreeShare");
    countUp(degreeEl, city.bachelorPlusShare * 100, 700, (v) => `${Math.round(v)}%`);
    setText("jobGeoDegreeText", `主流学历 ${city.education[0] ? city.education[0].name : "未注明"}`);

    renderCityTabs(province, city.city);
    renderProvinceComparison(province, city);

    const expContainer = document.getElementById("jobGeoExperienceList");
    if (expContainer) {
      expContainer.innerHTML = renderBarList(city.experience, {
        limit: 4,
        label: (item) => item.name,
        value: (item) => item.count,
        valueText: (item) => `${item.count} · ${formatPercent(item.ratio)}`
      });
    }

    const skillContainer = document.getElementById("jobGeoSkillTags");
    if (skillContainer) skillContainer.innerHTML = renderTagList(city.skills, 8);

    const industryContainer = document.getElementById("jobGeoIndustryList");
    if (industryContainer) {
      industryContainer.innerHTML = renderBarList(city.industries, {
        limit: 4,
        label: (item) => item.name,
        value: (item) => item.count,
        valueText: (item) => `${item.count} · ${formatPercent(item.ratio)}`
      });
    }

  }

  function bindResize() {
    if (state.resizeBound) return;
    state.resizeBound = true;
    const doResize = () => {
      if (state.chart) state.chart.resize();
    };
    window.addEventListener("resize", doResize);
    const mapEl = document.getElementById("jobsChinaMap");
    if (mapEl && typeof ResizeObserver === "function") {
      const ro = new ResizeObserver(() => {
        window.requestAnimationFrame(doResize);
      });
      ro.observe(mapEl);
    }
  }

  function buildCityScatterData() {
    if (!state.insights) return [];
    return state.insights.provinces.flatMap((province) => province.cities.map((city) => {
      const coords = CITY_COORDS[city.city];
      if (!coords) return null;
      return {
        name: city.city,
        city: city.city,
        province: province.name,
        jobCount: city.jobCount,
        averageAnnualized: city.averageAnnualized,
        value: [...coords, city.averageAnnualized]
      };
    })).filter(Boolean);
  }

  function renderMap() {
    const mapEl = document.getElementById("jobsChinaMap");
    if (!mapEl || !window.echarts || !state.insights) return;

    bindResize();

    if (!state.chart) {
      state.chart = window.echarts.init(mapEl, null, { renderer: "canvas" });
      state.chart.on("click", (params) => {
        const hint = document.getElementById("jobsGeoHint");
        if (hint) hint.style.display = "none";
        if (params.componentType === "series" && (params.seriesType === "effectScatter" || params.seriesType === "scatter")) {
          const cityName = params.data?.city || params.name;
          const provinceName = getProvinceName(cityName);
          if (cityName && provinceName && state.insights.provinceMap.has(provinceName)) {
            selectProvince(provinceName, cityName);
            return;
          }
        }
        if (params.name && state.insights.provinceMap.has(params.name)) {
          selectProvince(params.name);
        } else if (params.name && typeof window.showToast === "function") {
          window.showToast("暂无数据", `${params.name} 暂无采集城市样本。`, "warning", 1400);
        }
      });
    }

    const activeProvinces = state.insights.provinces.filter((item) => item.averageAnnualized > 0);
    const salaryValues = activeProvinces.map((item) => item.averageAnnualized);
    const minValue = salaryValues.length ? Math.floor(Math.min(...salaryValues)) : 0;
    const maxValue = salaryValues.length ? Math.ceil(Math.max(...salaryValues)) : 1;
    const mapLayout = {
      layoutCenter: ["45%", "52%"],
      layoutSize: "118%",
      aspectScale: 0.95
    };

    const activeCityScatter = Object.entries(CITY_COORDS)
      .filter(([city]) => {
        const province = state.insights.provinceMap.get(
          Object.entries({ "北京": "北京", "上海": "上海", "天津": "天津", "重庆": "重庆",
            "广州": "广东", "深圳": "广东", "杭州": "浙江", "厦门": "福建",
            "武汉": "湖北", "长沙": "湖南", "成都": "四川", "西安": "陕西",
            "郑州": "河南", "苏州": "江苏" }).find(([c]) => c === city)?.[1] || ""
        );
        return !!province;
      })
      .map(([city, coords]) => ({
        name: city,
        value: coords,
        symbolSize: 6
      }));

    state.chart.setOption({
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(3, 10, 22, 0.97)",
        borderColor: "rgba(34, 211, 238, 0.4)",
        borderWidth: 1,
        padding: [10, 14],
        textStyle: { color: "#e2f3ff", fontSize: 13 },
        extraCssText: "box-shadow: 0 8px 28px rgba(0,0,0,0.5); border-radius: 10px;",
        formatter(params) {
          if (params.seriesType === "effectScatter") {
            return `<strong style="color:#22d3ee">${safeHtml(params.name)}</strong>`;
          }
          const province = state.insights.provinceMap.get(params.name);
          if (!province || !params.name) {
            return params.name
              ? `<span style="color:#64748b">${safeHtml(params.name)}</span><br/><span style="color:#475569;font-size:11px">暂无采集样本</span>`
              : null;
          }
          return [
            `<strong style="color:#67e8f9;font-size:14px">${safeHtml(province.name)}</strong>`,
            `<span style="color:#7aa3bc;font-size:12px">岗位样本：</span><span style="color:#e0f7ff">${province.jobCount}</span>`,
            `<span style="color:#7aa3bc;font-size:12px">覆盖城市：</span><span style="color:#e0f7ff">${safeHtml(province.cityNames.join("、"))}</span>`,
            `<span style="color:#7aa3bc;font-size:12px">平均折算月薪：</span><strong style="color:#22d3ee;font-size:14px">${formatSalaryK(province.averageAnnualized)}</strong>`,
            `<span style="color:#7aa3bc;font-size:12px">实习/应届占比：</span><span style="color:#e0f7ff">${formatPercent(province.campusShare)}</span>`
          ].join("<br/>");
        }
      },
      geo: {
        map: "china",
        roam: false,
        silent: true,
        z: 0,
        ...mapLayout,
        itemStyle: { opacity: 0 },
        label: { show: false }
      },
      visualMap: {
        show: false,
        min: minValue,
        max: maxValue,
        calculable: false,
        inRange: {
          color: ["#083352", "#0c5080", "#0e7ab0", "#0ea5e9", "#22d3ee"]
        }
      },
      series: [
        {
          type: "map",
          map: "china",
          roam: false,
          selectedMode: "single",
          z: 2,
          ...mapLayout,
          label: {
            show: true,
            color: "#4a7a94",
            fontSize: 10,
            formatter(params) {
              if (!params.name) return "";
              return state.insights.provinceMap.has(params.name)
                ? `{active|${params.name}}`
                : (params.name.length <= 3 ? params.name : "");
            },
            rich: {
              active: { color: "#7ec8e0", fontWeight: 600, fontSize: 11 }
            }
          },
          itemStyle: {
            areaColor: "#071828",
            borderColor: "rgba(14, 165, 233, 0.45)",
            borderWidth: 1.2
          },
          emphasis: {
            label: {
              show: true, color: "#ffffff", fontWeight: 700, fontSize: 12,
              rich: { active: { color: "#ffffff", fontWeight: 700, fontSize: 12 } }
            },
            itemStyle: {
              areaColor: "#0c4878",
              borderColor: "#38bdf8",
              borderWidth: 2,
              shadowBlur: 18,
              shadowColor: "rgba(56, 189, 248, 0.45)"
            }
          },
          select: {
            label: {
              show: true, color: "#ffffff", fontWeight: 700, fontSize: 12,
              rich: { active: { color: "#ffffff", fontWeight: 700, fontSize: 12 } }
            },
            itemStyle: {
              areaColor: "#0369a1",
              borderColor: "#7dd3fc",
              borderWidth: 2,
              shadowBlur: 32,
              shadowColor: "rgba(34, 211, 238, 0.7)"
            }
          },
          data: state.insights.provinces.map((province) => ({
            name: province.name,
            value: Number(province.averageAnnualized.toFixed(2))
          }))
        },
        {
          type: "effectScatter",
          coordinateSystem: "geo",
          geoIndex: 0,
          z: 5,
          data: activeCityScatter,
          symbolSize: 6,
          showEffectOn: "render",
          rippleEffect: {
            brushType: "stroke",
            scale: 4.5,
            period: 2.2,
            color: "rgba(255, 60, 60, 0.65)"
          },
          label: { show: false },
          itemStyle: {
            color: "#ff3c3c",
            shadowBlur: 14,
            shadowColor: "rgba(255, 60, 60, 0.9)"
          }
        }
      ]
    }, true);

    window.requestAnimationFrame(() => {
      if (state.chart) state.chart.resize();
    });

    if (state.selectedProvince && state.insights.provinceMap.has(state.selectedProvince)) {
      state.chart.dispatchAction({ type: "select", seriesIndex: 0, name: state.selectedProvince });
    }
  }

  function selectProvince(provinceName, preferredCity) {
    if (!state.insights) return;

    const province = state.insights.provinceMap.get(provinceName);
    if (!province) return;

    const city = province.cities.find((item) => item.city === preferredCity) || province.cities[0];
    renderPanel(province, city);

    if (state.chart) {
      state.chart.dispatchAction({ type: "select", seriesIndex: 0, name: province.name });
    }
  }

  function renderOverview(insights) {
    setText("jobGeoProvinceCount", String(insights.totalProvinces));
    setText("jobGeoCityCount", String(insights.totalCities));
    setText("jobGeoJobCount", String(insights.totalJobs));
  }

  window.initializeJobGeoInsights = function initializeJobGeoInsights(jobs) {
    if (!Array.isArray(jobs) || jobs.length === 0) return;
    state.insights = buildInsights(jobs);
    renderOverview(state.insights);
    renderMap();
    const targetProvince = state.selectedProvince && state.insights.provinceMap.has(state.selectedProvince)
      ? state.selectedProvince
      : getDefaultProvince(state.insights);
    if (targetProvince) {
      const hint = document.getElementById("jobsGeoHint");
      if (hint) hint.style.display = "none";
      selectProvince(targetProvince, state.selectedCity);
    }
  };

  window.syncJobGeoSelectionWithCity = function syncJobGeoSelectionWithCity(city) {
    const province = getProvinceName(String(city || "").trim());
    if (province) selectProvince(province, city);
  };
})();
