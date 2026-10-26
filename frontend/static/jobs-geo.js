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
  const DEFAULT_WORKDAYS_PER_MONTH = 22;
  const WEEKS_PER_MONTH = 4.33;

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

  /** 补充采集里常见城市：省份用于聚合，坐标用于散点（与 boss 十四城对齐 ECharts 省级名称） */
  const GEO_CITY_EXTRA = Object.freeze({
    南京: { province: "江苏", coord: [118.80, 32.06] },
    无锡: { province: "江苏", coord: [120.29, 31.59] },
    徐州: { province: "江苏", coord: [117.18, 34.26] },
    常州: { province: "江苏", coord: [119.95, 31.79] },
    南通: { province: "江苏", coord: [120.86, 32.01] },
    扬州: { province: "江苏", coord: [119.42, 32.39] },
    盐城: { province: "江苏", coord: [120.16, 33.35] },
    泰州: { province: "江苏", coord: [119.92, 32.49] },
    镇江: { province: "江苏", coord: [119.44, 32.20] },
    合肥: { province: "安徽", coord: [117.23, 31.82] },
    芜湖: { province: "安徽", coord: [118.38, 31.33] },
    南昌: { province: "江西", coord: [115.89, 28.68] },
    赣州: { province: "江西", coord: [114.93, 25.83] },
    福州: { province: "福建", coord: [119.30, 26.08] },
    泉州: { province: "福建", coord: [118.68, 24.87] },
    漳州: { province: "福建", coord: [117.65, 24.51] },
    济南: { province: "山东", coord: [117.00, 36.65] },
    青岛: { province: "山东", coord: [120.38, 36.09] },
    烟台: { province: "山东", coord: [121.39, 37.54] },
    潍坊: { province: "山东", coord: [119.11, 36.71] },
    临沂: { province: "山东", coord: [118.35, 35.05] },
    淄博: { province: "山东", coord: [118.05, 36.81] },
    济宁: { province: "山东", coord: [116.59, 35.41] },
    威海: { province: "山东", coord: [122.12, 37.51] },
    东莞: { province: "广东", coord: [113.75, 23.02] },
    佛山: { province: "广东", coord: [113.11, 23.02] },
    珠海: { province: "广东", coord: [113.58, 22.27] },
    惠州: { province: "广东", coord: [114.42, 23.11] },
    中山: { province: "广东", coord: [113.39, 22.52] },
    江门: { province: "广东", coord: [113.08, 22.58] },
    汕头: { province: "广东", coord: [116.68, 23.35] },
    湛江: { province: "广东", coord: [110.36, 21.27] },
    南宁: { province: "广西", coord: [108.37, 22.82] },
    柳州: { province: "广西", coord: [109.43, 24.33] },
    桂林: { province: "广西", coord: [110.28, 25.29] },
    海口: { province: "海南", coord: [110.33, 20.03] },
    三亚: { province: "海南", coord: [109.51, 18.25] },
    石家庄: { province: "河北", coord: [114.48, 38.03] },
    唐山: { province: "河北", coord: [118.18, 39.63] },
    保定: { province: "河北", coord: [115.48, 38.87] },
    廊坊: { province: "河北", coord: [116.70, 39.52] },
    太原: { province: "山西", coord: [112.53, 37.87] },
    洛阳: { province: "河南", coord: [112.45, 34.62] },
    南阳: { province: "河南", coord: [112.53, 33.00] },
    襄阳: { province: "湖北", coord: [112.12, 32.01] },
    宜昌: { province: "湖北", coord: [111.29, 30.70] },
    衡阳: { province: "湖南", coord: [112.57, 26.90] },
    株洲: { province: "湖南", coord: [113.13, 27.83] },
    常德: { province: "湖南", coord: [111.69, 29.03] },
    绵阳: { province: "四川", coord: [104.68, 31.47] },
    德阳: { province: "四川", coord: [104.40, 31.13] },
    南充: { province: "四川", coord: [106.08, 30.80] },
    昆明: { province: "云南", coord: [102.71, 25.04] },
    曲靖: { province: "云南", coord: [103.80, 25.49] },
    贵阳: { province: "贵州", coord: [106.71, 26.57] },
    遵义: { province: "贵州", coord: [106.93, 27.70] },
    兰州: { province: "甘肃", coord: [103.82, 36.06] },
    乌鲁木齐: { province: "新疆", coord: [87.62, 43.83] },
    银川: { province: "宁夏", coord: [106.27, 38.47] },
    西宁: { province: "青海", coord: [101.78, 36.62] },
    拉萨: { province: "西藏", coord: [91.11, 29.97] },
    呼和浩特: { province: "内蒙古", coord: [111.65, 40.82] },
    包头: { province: "内蒙古", coord: [109.84, 40.66] },
    长春: { province: "吉林", coord: [125.32, 43.88] },
    哈尔滨: { province: "黑龙江", coord: [126.63, 45.75] },
    沈阳: { province: "辽宁", coord: [123.43, 41.80] },
    大连: { province: "辽宁", coord: [121.62, 38.92] },
    宁波: { province: "浙江", coord: [121.54, 29.87] },
    温州: { province: "浙江", coord: [120.70, 28.00] },
    嘉兴: { province: "浙江", coord: [120.76, 30.77] },
    绍兴: { province: "浙江", coord: [120.58, 30.01] },
    金华: { province: "浙江", coord: [119.65, 29.08] },
    台州: { province: "浙江", coord: [121.42, 28.66] },
    湖州: { province: "浙江", coord: [120.09, 30.89] },
    义乌: { province: "浙江", coord: [120.08, 29.31] },
    石河子: { province: "新疆", coord: [86.03, 44.30] }
  });

  const MAP_PROVINCES = new Set([
    "北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
    "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "香港", "澳门", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆"
  ]);

  /** 省会城市/首府/直辖市：地图散点仅标注这些城市 */
  const PROVINCIAL_CAPITALS = new Set([
    "北京", "上海", "天津", "重庆",
    "石家庄", "太原", "沈阳", "长春", "哈尔滨",
    "南京", "杭州", "合肥", "福州", "南昌", "济南",
    "郑州", "武汉", "长沙", "广州", "海口",
    "成都", "贵阳", "昆明", "西安", "兰州", "西宁", "拉萨",
    "南宁", "呼和浩特", "乌鲁木齐", "银川",
    "台北", "香港", "澳门"
  ]);

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
    if (!city) return "";
    if (CITY_PROVINCE_MAP[city]) return CITY_PROVINCE_MAP[city];
    const row = GEO_CITY_EXTRA[city];
    return row ? row.province : "";
  }

  function getCityCoord(city) {
    if (!city) return null;
    if (CITY_COORDS[city]) return CITY_COORDS[city];
    const row = GEO_CITY_EXTRA[city];
    return row ? row.coord : null;
  }

  function normalizeProvinceToken(raw) {
    const s = String(raw || "").trim();
    if (!s) return "";
    const special = [
      ["新疆维吾尔自治区", "新疆"],
      ["内蒙古自治区", "内蒙古"],
      ["广西壮族自治区", "广西"],
      ["西藏自治区", "西藏"],
      ["宁夏回族自治区", "宁夏"],
      ["香港特别行政区", "香港"],
      ["澳门特别行政区", "澳门"]
    ];
    for (let i = 0; i < special.length; i += 1) {
      if (s === special[i][0] || s.startsWith(special[i][0])) return special[i][1];
    }
    if (s.endsWith("省")) {
      const core = s.slice(0, -1);
      return MAP_PROVINCES.has(core) ? core : "";
    }
    const muni = s.match(/^(北京|上海|天津|重庆)市?$/);
    if (muni) return muni[1];
    if (MAP_PROVINCES.has(s)) return s;
    return "";
  }

  /** 工作地址形如「广东-东莞-镇区」时推断省/市，补全仅有城市名却不在字典里的样本 */
  function inferRegionFromWorkAddress(job) {
    const addr = String(job["工作地址"] || "").trim();
    if (!addr) return null;
    const parts = addr.split(/[-－]/).map((x) => x.trim()).filter(Boolean);
    if (parts.length < 2) return null;
    const province = normalizeProvinceToken(parts[0]);
    if (!province || !MAP_PROVINCES.has(province)) return null;
    const cityGuess = String(parts[1] || "").replace(/市辖区$/, "").replace(/市$/, "").trim();
    if (!cityGuess) return null;
    return { province, city: cityGuess };
  }

  function estimateMonthlyWorkdays(contextText) {
    const text = String(contextText || "");
    const match = text.match(/([1-7])\s*天\/周/);
    if (!match) return DEFAULT_WORKDAYS_PER_MONTH;
    return Math.max(4, Math.min(31, Number(match[1]) * WEEKS_PER_MONTH));
  }

  function parseSalary(text, contextText = "") {
    void contextText;
    const raw = String(text || "").replace(/\s/g, "");
    if (!raw || raw === "面议") return null;

    const payMonths = Number((raw.match(/·(\d+)薪/) || [])[1] || 12);
    let low = null;
    let high = null;

    // 日薪统一按 22 天/月折算为月薪，不再区分 daily/monthly
    const dailyMatch = raw.match(/(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)元\/天/);
    if (dailyMatch) {
      low = Number(dailyMatch[1]) * 22 / 1000;
      high = Number(dailyMatch[2]) * 22 / 1000;
    } else {
      // 去掉「·13薪」等后缀，仅对数字区间做匹配（payMonths 仍从完整 raw 读取）
      const salaryBody = raw.replace(/·\d+薪.*$/i, "").trim();

      const wanRange = salaryBody.match(/(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)万(?:\/月)?/i);
      const wanSingle = !wanRange && salaryBody.match(/^(\d+(?:\.\d+)?)万(?:\/月)?$/i);
      const yuanMonthRange = salaryBody.match(/(\d+)\s*-\s*(\d+)元\/月/i);
      const yuanMonthSingle = !yuanMonthRange && salaryBody.match(/^(\d+)元\/月$/i);
      const rangeMatch = salaryBody.match(/(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)K/i);
      const singleMatch = salaryBody.match(/(\d+(?:\.\d+)?)K/i);

      if (wanRange) {
        low = Number(wanRange[1]) * 10;
        high = Number(wanRange[2]) * 10;
      } else if (wanSingle) {
        low = high = Number(wanSingle[1]) * 10;
      } else if (yuanMonthRange) {
        low = Number(yuanMonthRange[1]) / 1000;
        high = Number(yuanMonthRange[2]) / 1000;
      } else if (yuanMonthSingle) {
        low = high = Number(yuanMonthSingle[1]) / 1000;
      } else if (rangeMatch) {
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
      workdaysPerMonth: null,
      salaryType: "monthly"
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
    const salaryRecords = jobs.map((job) => parseSalary(job["薪资"], job["经验要求"])).filter(Boolean);
    const lowValues = salaryRecords.map((item) => item.low);
    const highValues = salaryRecords.map((item) => item.high);
    const annualizedValues = salaryRecords.map((item) => item.annualizedMid);
    const dailyCount = salaryRecords.filter((item) => item.salaryType === "daily").length;
    const monthlyCount = salaryRecords.filter((item) => item.salaryType === "monthly").length;
    const dailyWorkdayValues = salaryRecords
      .filter((item) => item.salaryType === "daily" && Number.isFinite(item.workdaysPerMonth))
      .map((item) => item.workdaysPerMonth);
    const campusCount = jobs.filter((job) => {
      const text = String(job["经验要求"] || "");
      return text.includes("在校") || text.includes("应届") || /天\/周/.test(text);
    }).length;
    const bachelorPlusCount = jobs.filter((job) => BACHELOR_PLUS.has(normalizeEducation(job["学历要求"]))).length;

    return {
      label,
      jobCount: jobs.length,
      salaryCount: salaryRecords.length,
      salaryCoverageShare: jobs.length ? salaryRecords.length / jobs.length : 0,
      averageLow: average(lowValues),
      averageHigh: average(highValues),
      averageAnnualized: average(annualizedValues),
      medianAnnualized: median(annualizedValues),
      monthlyCount,
      dailyCount,
      averageDailyWorkdays: average(dailyWorkdayValues) || DEFAULT_WORKDAYS_PER_MONTH,
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
      let city = getCityName(job);
      let province = getProvinceName(city);
      if (!province) {
        const inferred = inferRegionFromWorkAddress(job);
        if (!inferred) return;
        province = inferred.province;
        if (!city) city = inferred.city;
      }
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

    let mappedJobCount = 0;
    provinces.forEach((p) => {
      mappedJobCount += p.jobCount;
    });

    return {
      totalJobs: mappedJobCount,
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

  function renderSalaryMix(city) {
    const dailyDays = Number.isFinite(city.averageDailyWorkdays)
      ? `${city.averageDailyWorkdays.toFixed(1)} 天/月`
      : `${DEFAULT_WORKDAYS_PER_MONTH} 天/月`;
    return `
      <div class="jobs-geo-salary-row">
        <span>有效薪资样本</span>
        <strong>${city.salaryCount || 0}/${city.jobCount || 0}</strong>
        <small>${formatPercent(city.salaryCoverageShare)} 可用于薪资估算</small>
      </div>
      <div class="jobs-geo-salary-row">
        <span>月薪岗位</span>
        <strong>${city.monthlyCount || 0}</strong>
        <small>按 K/月原始区间读取</small>
      </div>
      <div class="jobs-geo-salary-row">
        <span>日薪岗位</span>
        <strong>${city.dailyCount || 0}</strong>
        <small>${dailyDays} 估算</small>
      </div>
    `;
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
      `${city.city} 共收录 ${city.jobCount} 个岗位样本，估算月薪 ${formatSalaryK(city.averageAnnualized)}，平均薪资区间 ${formatRange(city.averageLow, city.averageHigh)}。`
    );

    const sampleEl = document.getElementById("jobGeoSampleCount");
    countUp(sampleEl, city.jobCount, 700, (v) => String(Math.round(v)));
    setText("jobGeoCoverageText", `省内累计 ${province.jobCount} 个岗位样本`);

    const salaryEl = document.getElementById("jobGeoAvgSalary");
    countUp(salaryEl, city.averageAnnualized, 800, (v) => formatSalaryK(v));
    setText("jobGeoSalaryText", `均值区间 ${formatRange(city.averageLow, city.averageHigh)} · 中位 ${formatSalaryK(city.medianAnnualized)}`);
    setText("jobGeoSalaryPolicy", "");
    const salaryMix = document.getElementById("jobGeoSalaryMix");
    if (salaryMix) salaryMix.innerHTML = renderSalaryMix(city);

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
    setText("jobGeoCampusText", `日薪样本 ${formatPercent(city.dailyShare)}`);

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

    const educationContainer = document.getElementById("jobGeoEducationList");
    if (educationContainer) {
      educationContainer.innerHTML = renderBarList(city.education, {
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
    return state.insights.provinces.flatMap((province) =>
      province.cities
        .filter((city) => PROVINCIAL_CAPITALS.has(city.city))
        .map((city) => {
          const coords = getCityCoord(city.city);
          if (!coords) return null;
          return {
            name: city.city,
            city: city.city,
            province: province.name,
            jobCount: city.jobCount,
            averageAnnualized: city.averageAnnualized,
            value: [...coords, city.averageAnnualized]
          };
        })
    ).filter(Boolean);
  }

  const MAP_ZOOM_LIMIT = Object.freeze({ min: 1, max: 5 });

  function updateMapControls() {
    const zoom = state.chart?.getOption()?.geo?.[0]?.zoom || 1;
    const stage = document.getElementById("jobsChinaMap")?.closest(".jobs-geo-stage");
    if (!stage) return;
    stage.querySelector('[data-job-geo-action="zoom-in"]').disabled = zoom >= MAP_ZOOM_LIMIT.max;
    stage.querySelector('[data-job-geo-action="zoom-out"]').disabled = zoom <= MAP_ZOOM_LIMIT.min;
  }

  function bindMapControls(mapEl) {
    const stage = mapEl.closest(".jobs-geo-stage");
    if (!stage || stage.dataset.zoomBound) return;
    stage.dataset.zoomBound = "true";
    stage.addEventListener("click", (event) => {
      const button = event.target.closest("[data-job-geo-action]");
      if (!button || !state.chart) return;
      const action = button.dataset.jobGeoAction;
      if (action === "reset") {
        state.chart.setOption({ geo: { center: null, zoom: 1 } });
      } else {
        const zoom = state.chart.getOption().geo[0].zoom || 1;
        const next = Math.max(MAP_ZOOM_LIMIT.min, Math.min(MAP_ZOOM_LIMIT.max,
          zoom * (action === "zoom-in" ? 1.25 : 0.8)));
        state.chart.dispatchAction({ type: "geoRoam", componentType: "geo", geoIndex: 0,
          zoom: next / zoom, originX: state.chart.getWidth() / 2, originY: state.chart.getHeight() / 2 });
      }
      updateMapControls();
    });
  }

  function renderMap() {
    const mapEl = document.getElementById("jobsChinaMap");
    if (!mapEl || !window.echarts || !state.insights) return;

    bindResize();
    bindMapControls(mapEl);

    if (!state.chart) {
      state.chart = window.echarts.init(mapEl, null, { renderer: "canvas" });
      state.chart.on("georoam", updateMapControls);
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
    const regionStyle = {
          label: {
            show: true,
            color: "#496377",
            fontSize: 10,
            formatter(params) {
              if (!params.name) return "";
              return state.insights.provinceMap.has(params.name)
                ? `{active|${params.name}}`
                : (params.name.length <= 3 ? params.name : "");
            },
            rich: {
              active: { color: "#0f3554", fontWeight: 800, fontSize: 11 }
            }
          },
          itemStyle: {
            areaColor: "#cdd9e5",
            borderColor: "rgba(248, 250, 252, 0.96)",
            borderWidth: 1.2,
            shadowBlur: 14,
            shadowColor: "rgba(15, 45, 72, 0.14)"
          },
          emphasis: {
            label: {
              show: true, color: "#0f172a", fontWeight: 800, fontSize: 12,
              rich: { active: { color: "#0f172a", fontWeight: 800, fontSize: 12 } }
            },
            itemStyle: {
              areaColor: "#3d93b6",
              borderColor: "#ffffff",
              borderWidth: 2,
              shadowBlur: 20,
              shadowColor: "rgba(13, 92, 120, 0.34)"
            }
          },
          select: {
            label: {
              show: true, color: "#ffffff", fontWeight: 700, fontSize: 12,
              rich: { active: { color: "#ffffff", fontWeight: 700, fontSize: 12 } }
            },
            itemStyle: {
              areaColor: "#0d5c78",
              borderColor: "#ffffff",
              borderWidth: 2,
              shadowBlur: 30,
              shadowColor: "rgba(13, 92, 120, 0.46)"
            }
          },
    };
    const previousGeo = state.chart.getOption()?.geo?.[0];
    const mapView = { zoom: previousGeo?.zoom || 1 };
    if (previousGeo?.center) mapView.center = previousGeo.center;
    const mapLayout = {
      layoutCenter: ["46%", "52%"],
      layoutSize: "108%",
      aspectScale: 0.95
    };

    const maxCityJobs = Math.max(1, ...state.insights.provinces.flatMap((province) => province.cities.map((city) => city.jobCount || 0)));
    const activeCityScatter = buildCityScatterData().map((item) => ({
      ...item,
      symbolSize: Math.max(7, Math.min(18, 7 + (item.jobCount / maxCityJobs) * 12))
    }));

    state.chart.setOption({
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(248, 250, 252, 0.98)",
        borderColor: "rgba(148, 163, 184, 0.42)",
        borderWidth: 1,
        padding: [10, 14],
        textStyle: { color: "#1e293b", fontSize: 13 },
        extraCssText: "box-shadow: 0 14px 34px rgba(15,23,42,0.16); border-radius: 10px;",
        formatter(params) {
          if (params.seriesType === "effectScatter") {
            const salary = Number(params.data?.averageAnnualized || params.value?.[2] || 0);
            return [
              `<strong style="color:#0f766e">${safeHtml(params.name)}</strong>`,
              `<span style="color:#64748b;font-size:12px">岗位样本：</span><span>${safeHtml(params.data?.jobCount || "--")}</span>`,
              `<span style="color:#64748b;font-size:12px">平均折算月薪：</span><strong style="color:#0f766e">${formatSalaryK(salary)}</strong>`
            ].join("<br/>");
          }
          const province = state.insights.provinceMap.get(params.name);
          if (!province || !params.name) {
            return params.name
              ? `<span style="color:#64748b">${safeHtml(params.name)}</span><br/><span style="color:#475569;font-size:11px">暂无采集样本</span>`
              : null;
          }
          return [
            `<strong style="color:#1a365d;font-size:14px">${safeHtml(province.name)}</strong>`,
            `<span style="color:#64748b;font-size:12px">岗位样本：</span><span>${province.jobCount}</span>`,
            `<span style="color:#64748b;font-size:12px">覆盖城市：</span><span>${safeHtml(province.cityNames.join("、"))}</span>`,
            `<span style="color:#64748b;font-size:12px">平均折算月薪：</span><strong style="color:#0f766e;font-size:14px">${formatSalaryK(province.averageAnnualized)}</strong>`,
            `<span style="color:#64748b;font-size:12px">实习/应届占比：</span><span>${formatPercent(province.campusShare)}</span>`
          ].join("<br/>");
        }
      },
      geo: {
        map: "china",
        roam: true,
        scaleLimit: MAP_ZOOM_LIMIT,
        selectedMode: "single",
        z: 2,
        ...mapLayout,
        ...mapView,
        ...regionStyle
      },
      visualMap: {
        show: false,
        seriesIndex: 0,
        min: minValue,
        max: maxValue,
        calculable: false,
        inRange: {
          color: ["#c6d4e2", "#93adc6", "#5f8eb3", "#2f789f", "#0d5c78"]
        }
      },
      series: [
        {
          type: "map",
          map: "china",
          geoIndex: 0,
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
          symbolSize: (value, params) => params.data?.symbolSize || 7,
          showEffectOn: "render",
          rippleEffect: {
            brushType: "stroke",
            scale: 3.2,
            period: 2.6,
            color: "rgba(11, 114, 133, 0.5)"
          },
          label: { show: false },
          itemStyle: {
            color: "#0b7285",
            borderColor: "#ffffff",
            borderWidth: 2,
            shadowBlur: 14,
            shadowColor: "rgba(11, 114, 133, 0.58)"
          }
        }
      ]
    }, true);
    updateMapControls();

    window.requestAnimationFrame(() => {
      if (state.chart) state.chart.resize();
    });

    if (state.selectedProvince && state.insights.provinceMap.has(state.selectedProvince)) {
      state.chart.dispatchAction({ type: "geoSelect", geoIndex: 0, name: state.selectedProvince });
    }
  }

  function selectProvince(provinceName, preferredCity) {
    if (!state.insights) return;

    const province = state.insights.provinceMap.get(provinceName);
    if (!province) return;

    const city = province.cities.find((item) => item.city === preferredCity) || province.cities[0];
    renderPanel(province, city);

    if (state.chart) {
      state.chart.dispatchAction({ type: "geoSelect", geoIndex: 0, name: province.name });
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
