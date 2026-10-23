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

  const CITY_COORDS = Object.freeze({
    "北京": [116.41, 39.90],
    "上海": [121.47, 31.23],
    "天津": [117.19, 39.13],
    "重庆": [106.55, 29.57],
    "广州": [113.27, 23.13],
    "深圳": [114.06, 22.54],
    "杭州": [120.15, 30.27],
    "厦门": [118.10, 24.46],
    "武汉": [114.31, 30.52],
    "长沙": [112.98, 28.21],
    "成都": [104.07, 30.67],
    "西安": [108.93, 34.27],
    "郑州": [113.65, 34.76],
    "苏州": [120.59, 31.30]
  });

  let cachedJobs = [];
  let provinceStats = new Map();
  let cityStats = new Map();

  function getCityName(job) {
    return String(job["采集城市"] || job["城市"] || "").trim();
  }

  function getProvinceName(city) {
    return CITY_PROVINCE_MAP[city] || "";
  }

  function average(values) {
    if (!values.length) return 0;
    return values.reduce((sum, item) => sum + item, 0) / values.length;
  }

  function formatSalaryK(value) {
    if (!Number.isFinite(value) || value <= 0) return "--";
    return `${value.toFixed(1)}K`;
  }

  function formatPercent(value) {
    if (!Number.isFinite(value)) return "--";
    return `${Math.round(value * 100)}%`;
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
      // 统一按 22 天/月折算为月薪
      low = Number(match[1]) * 22 / 1000;
      high = Number(match[2]) * 22 / 1000;
    } else {
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

    return {
      annualizedMid: ((low + high) / 2) * payMonths / 12
    };
  }

  function buildStats(jobs) {
    const provinceBuckets = new Map();
    const cityBuckets = new Map();

    jobs.forEach((job) => {
      const city = getCityName(job);
      const province = getProvinceName(city);
      if (!city || !province) return;

      if (!provinceBuckets.has(province)) provinceBuckets.set(province, []);
      if (!cityBuckets.has(city)) cityBuckets.set(city, { city, province, jobs: [] });

      provinceBuckets.get(province).push(job);
      cityBuckets.get(city).jobs.push(job);
    });

    provinceStats = new Map([...provinceBuckets.entries()].map(([province, jobsForProvince]) => {
      const salaries = jobsForProvince.map((job) => parseSalary(job["薪资"])).filter(Boolean).map((item) => item.annualizedMid);
      const campusCount = jobsForProvince.filter((job) => {
        const exp = String(job["经验要求"] || "");
        return exp.includes("在校") || exp.includes("应届") || /天\/周/.test(exp);
      }).length;
      return [province, {
        name: province,
        jobCount: jobsForProvince.length,
        averageAnnualized: average(salaries),
        campusShare: jobsForProvince.length ? campusCount / jobsForProvince.length : 0,
        cityNames: [...new Set(jobsForProvince.map(getCityName).filter(Boolean))]
      }];
    }));

    cityStats = new Map([...cityBuckets.values()].map((bucket) => {
      const salaries = bucket.jobs.map((job) => parseSalary(job["薪资"])).filter(Boolean).map((item) => item.annualizedMid);
      return [bucket.city, {
        city: bucket.city,
        province: bucket.province,
        jobCount: bucket.jobs.length,
        averageAnnualized: average(salaries)
      }];
    }));
  }

  function getChart() {
    if (!window.echarts) return null;
    const el = document.getElementById("jobsChinaMap");
    if (!el) return null;
    return window.echarts.getInstanceByDom(el);
  }

  function getCurrentCityFromPanel() {
    const el = document.getElementById("jobGeoCityTitle");
    return el ? String(el.textContent || "").trim() : "";
  }

  function getCurrentProvinceFromPanel() {
    const el = document.getElementById("jobGeoProvinceLabel");
    if (!el) return "";
    const text = String(el.textContent || "").trim();
    return text.split("·")[0].trim();
  }

  function buildScatterData() {
    return [...cityStats.values()]
      .map((item) => {
        const coords = CITY_COORDS[item.city];
        if (!coords) return null;
        return {
          name: item.city,
          city: item.city,
          province: item.province,
          jobCount: item.jobCount,
          averageAnnualized: item.averageAnnualized,
          value: [...coords, item.averageAnnualized]
        };
      })
      .filter(Boolean);
  }

  function applyWarmTheme() {
    const chart = getChart();
    if (!chart || !cachedJobs.length) return;

    const currentCity = getCurrentCityFromPanel();
    const currentProvince = getCurrentProvinceFromPanel() || getProvinceName(currentCity);
    const provinceValues = [...provinceStats.values()].map((item) => item.averageAnnualized).filter((value) => value > 0);
    const minValue = provinceValues.length ? Math.floor(Math.min(...provinceValues)) : 0;
    const maxValue = provinceValues.length ? Math.ceil(Math.max(...provinceValues)) : 1;
    const mapLayout = {
      layoutCenter: ["45%", "52%"],
      layoutSize: "118%",
      aspectScale: 0.95
    };

    const scatterData = buildScatterData();
    const selectedData = currentCity ? scatterData.filter((item) => item.city === currentCity) : [];

    chart.setOption({
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(25, 16, 22, 0.96)",
        borderColor: "rgba(255, 132, 132, 0.38)",
        borderWidth: 1,
        padding: [10, 14],
        textStyle: { color: "#fff1ee", fontSize: 13 },
        extraCssText: "box-shadow: 0 10px 28px rgba(0,0,0,0.46); border-radius: 10px;",
        formatter(params) {
          if (params.seriesType === "scatter" || params.seriesType === "effectScatter") {
            const cityData = params.data || {};
            return [
              `<strong style="color:#ffd4cf;font-size:14px">${cityData.city || params.name}</strong>`,
              cityData.province ? `<span style="color:#e9b6ab;font-size:12px">所在省份：</span><span style="color:#fff1ee">${cityData.province}</span>` : "",
              cityData.jobCount ? `<span style="color:#e9b6ab;font-size:12px">岗位样本：</span><span style="color:#fff1ee">${cityData.jobCount}</span>` : "",
              cityData.averageAnnualized ? `<span style="color:#e9b6ab;font-size:12px">平均折算月薪：</span><strong style="color:#ff7b72;font-size:14px">${formatSalaryK(cityData.averageAnnualized)}</strong>` : ""
            ].filter(Boolean).join("<br/>");
          }

          const province = provinceStats.get(params.name);
          if (!province || !params.name) return params.name || "";

          return [
            `<strong style="color:#ffe2d8;font-size:14px">${province.name}</strong>`,
            `<span style="color:#ddb2a8;font-size:12px">岗位样本：</span><span style="color:#fff3ef">${province.jobCount}</span>`,
            `<span style="color:#ddb2a8;font-size:12px">覆盖城市：</span><span style="color:#fff3ef">${province.cityNames.join("、")}</span>`,
            `<span style="color:#ddb2a8;font-size:12px">平均折算月薪：</span><strong style="color:#ff8f7b;font-size:14px">${formatSalaryK(province.averageAnnualized)}</strong>`,
            `<span style="color:#ddb2a8;font-size:12px">实习/应届占比：</span><span style="color:#fff3ef">${formatPercent(province.campusShare)}</span>`
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
          color: ["#10304f", "#275968", "#4f7380", "#c98b79", "#f0b490"]
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
            color: "#93abbb",
            fontSize: 10,
            formatter(params) {
              if (!params.name) return "";
              return provinceStats.has(params.name) ? `{active|${params.name}}` : (params.name.length <= 3 ? params.name : "");
            },
            rich: {
              active: { color: "#d5e3ea", fontWeight: 600, fontSize: 11 }
            }
          },
          itemStyle: {
            areaColor: "#0b2237",
            borderColor: "rgba(81, 172, 218, 0.46)",
            borderWidth: 1.2
          },
          emphasis: {
            label: {
              show: true,
              color: "#fff7f5",
              fontWeight: 700,
              fontSize: 12,
              rich: { active: { color: "#fff7f5", fontWeight: 700, fontSize: 12 } }
            },
            itemStyle: {
              areaColor: "#557483",
              borderColor: "#ffd3c5",
              borderWidth: 2,
              shadowBlur: 20,
              shadowColor: "rgba(255, 149, 128, 0.32)"
            }
          },
          select: {
            label: {
              show: true,
              color: "#fff7f5",
              fontWeight: 700,
              fontSize: 12,
              rich: { active: { color: "#fff7f5", fontWeight: 700, fontSize: 12 } }
            },
            itemStyle: {
              areaColor: "#6d8793",
              borderColor: "#ffd7cb",
              borderWidth: 2,
              shadowBlur: 30,
              shadowColor: "rgba(255, 150, 130, 0.3)"
            }
          },
          data: [...provinceStats.values()].map((item) => ({
            name: item.name,
            value: Number(item.averageAnnualized.toFixed(2))
          }))
        },
        {
          type: "scatter",
          coordinateSystem: "geo",
          geoIndex: 0,
          z: 5,
          data: scatterData,
          symbol: "circle",
          symbolSize(value, params) {
            const data = params.data || {};
            return data.city === currentCity ? 12 : 8;
          },
          itemStyle: {
            color: "#ff6b6b",
            borderColor: "rgba(255, 245, 242, 0.95)",
            borderWidth: 1.5,
            shadowBlur: 14,
            shadowColor: "rgba(255, 107, 107, 0.58)"
          },
          emphasis: {
            scale: 1.18,
            itemStyle: {
              color: "#ff5a5f",
              borderColor: "#ffffff",
              borderWidth: 2.2
            }
          },
          label: { show: false }
        },
        {
          type: "effectScatter",
          coordinateSystem: "geo",
          geoIndex: 0,
          z: 6,
          data: selectedData,
          symbol: "pin",
          symbolSize: 22,
          showEffectOn: "render",
          rippleEffect: {
            brushType: "stroke",
            scale: 5.2,
            period: 2.5,
            color: "rgba(255, 99, 99, 0.45)"
          },
          label: {
            show: true,
            formatter: "{b}",
            position: "top",
            offset: [0, -10],
            color: "#ffe4df",
            fontSize: 11,
            fontWeight: 700,
            textBorderColor: "rgba(66, 12, 12, 0.82)",
            textBorderWidth: 3
          },
          itemStyle: {
            color: "#ff5252",
            borderColor: "#fff4f1",
            borderWidth: 1.5,
            shadowBlur: 18,
            shadowColor: "rgba(255, 82, 82, 0.72)"
          }
        }
      ]
    }, true);

    if (currentProvince && provinceStats.has(currentProvince)) {
      chart.dispatchAction({ type: "select", seriesIndex: 0, name: currentProvince });
    }
  }

  function scheduleApply() {
    setTimeout(applyWarmTheme, 0);
    setTimeout(applyWarmTheme, 80);
  }

  function bindChartEnhance() {
    const chart = getChart();
    if (!chart || chart.__jobsGeoEnhanceBound) return;
    chart.__jobsGeoEnhanceBound = true;
    chart.on("click", () => {
      scheduleApply();
    });
  }

  function initEnhance(jobs) {
    cachedJobs = Array.isArray(jobs) ? jobs : [];
    if (!cachedJobs.length) return;
    buildStats(cachedJobs);
    bindChartEnhance();
    scheduleApply();
  }

  const originalInit = window.initializeJobGeoInsights;
  window.initializeJobGeoInsights = function (jobs) {
    if (typeof originalInit === "function") originalInit(jobs);
    initEnhance(jobs);
  };

  const originalSync = window.syncJobGeoSelectionWithCity;
  window.syncJobGeoSelectionWithCity = function (city) {
    if (typeof originalSync === "function") originalSync(city);
    scheduleApply();
  };

  document.addEventListener("click", (event) => {
    if (event.target.closest(".jobs-geo-city-btn")) {
      scheduleApply();
    }
  });
})();
