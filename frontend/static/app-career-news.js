// 实时动态与职业资讯看板
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function addLiveActivity(message) {
  const timeLabel = formatClock(new Date());
  ["liveActivityFeed", "liveActivityFeedDisplay"].forEach((id) => {
    const feed = document.getElementById(id);
    if (!feed) return;
    const li = document.createElement("li");
    li.className = "live-feed-item";
    li.innerHTML = `
      <span class="live-feed-dot"></span>
      <div>
        <p class="text-sm text-gray-800">${message}</p>
        <p class="text-xs text-gray-500">${timeLabel}</p>
      </div>
    `;
    feed.insertBefore(li, feed.firstChild);
    while (feed.children.length > 6) feed.removeChild(feed.lastElementChild);
  });
}

function _careerNewsPublishedTs(el) {
  if (!el) return 0;
  const raw = String(el.dataset.published || "").trim();
  const ts = raw ? Date.parse(raw) : NaN;
  if (Number.isFinite(ts)) return ts;
  const label = String(el.querySelector(".career-news-time")?.textContent || "").trim();
  const guess = Date.parse(label);
  return Number.isFinite(guess) ? guess : 0;
}

function _getCareerNewsWorkingItems() {
  const working = [...careerNewsState.items];
  working.sort((a, b) => {
    return _careerNewsPublishedTs(b) - _careerNewsPublishedTs(a);
  });
  return working;
}

function _careerNewsClearProgressRaf() {
  if (careerNewsState.progressRaf) {
    cancelAnimationFrame(careerNewsState.progressRaf);
    careerNewsState.progressRaf = null;
  }
}

function _careerNewsClearAutoPlay() {
  if (careerNewsState.autoPlayTimer) {
    window.clearInterval(careerNewsState.autoPlayTimer);
    careerNewsState.autoPlayTimer = null;
  }
  _careerNewsClearProgressRaf();
  careerNewsState.progressEpoch = 0;
}

function _careerNewsResetProgressEpoch() {
  careerNewsState.progressEpoch = Date.now();
}

function _careerNewsTickProgress() {
  careerNewsState.progressRaf = null;
  const bar = document.getElementById("careerNewsProgressBar");
  if (!careerNewsState.progressEpoch || !careerNewsState.autoPlayTimer) return;
  if (!bar) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    bar.style.width = "100%";
    return;
  }
  const elapsed = Date.now() - careerNewsState.progressEpoch;
  const pct = Math.min(100, (elapsed / 10000) * 100);
  bar.style.width = `${pct}%`;
  careerNewsState.progressRaf = requestAnimationFrame(_careerNewsTickProgress);
}

function _careerNewsStartProgressLoop() {
  _careerNewsClearProgressRaf();
  careerNewsState.progressRaf = requestAnimationFrame(_careerNewsTickProgress);
}

/** 旧版 DOM 自愈：补全三卡轮排 + 网格结构 */
function _ensureCareerNewsFeaturedDom() {
  const root = document.getElementById("careerNewsFeatured");
  if (!root) return false;
  if (root.querySelector("[data-career-news-cards-wrapper]") && root.querySelector("#careerNewsGridBoard")) return true;
  root.className = "career-news-carousel";
  root.setAttribute("role", "region");
  root.setAttribute("aria-roledescription", "carousel");
  root.setAttribute("aria-label", "职业快报轮播");
  root.innerHTML = `
    <div class="career-news-spotlight" aria-label="焦点快讯，三卡轮排">
      <div class="career-news-spotlight-viewport" tabindex="0" aria-label="焦点区，左右键切换">
        <div class="career-news-cards-wrapper" data-career-news-cards-wrapper>
          <div class="career-news-spot-card previous--card" aria-hidden="true"></div>
          <div class="career-news-spot-card current--card"></div>
          <div class="career-news-spot-card next--card" aria-hidden="true"></div>
        </div>
      </div>
    </div>
    <div id="careerNewsGridBoard" class="career-news-grid-board" aria-label="本批快讯列表"></div>
  `;
  return true;
}

function _careerNewsSpotlightClone(el, role) {
  const c = el.cloneNode(true);
  c.classList.remove("career-news-item--grid");
  c.classList.add("career-news-item--spotlight", `career-news-item--spotlight-${role}`);
  c.setAttribute("data-spotlight-clone", role);
  return c;
}

function _careerNewsFillSpotCard(shell, sourceItem, role) {
  if (!shell) return;
  shell.innerHTML = "";
  if (!sourceItem) return;
  shell.appendChild(_careerNewsSpotlightClone(sourceItem, role));
}

function _syncSpotlightInnerRoles(wrapper) {
  if (!wrapper) return;
  const prevShell = wrapper.querySelector(".career-news-spot-card.previous--card");
  const curShell = wrapper.querySelector(".career-news-spot-card.current--card");
  const nextShell = wrapper.querySelector(".career-news-spot-card.next--card");
  [
    [prevShell, "prev"],
    [curShell, "current"],
    [nextShell, "next"]
  ].forEach(([shell, r]) => {
    const link = shell?.querySelector(".career-news-item");
    if (!link) return;
    link.classList.remove(
      "career-news-item--spotlight-prev",
      "career-news-item--spotlight-current",
      "career-news-item--spotlight-next"
    );
    link.classList.add("career-news-item--spotlight", `career-news-item--spotlight-${r}`);
  });
  [prevShell, curShell, nextShell].forEach((shell) => {
    if (!shell) return;
    shell.setAttribute("aria-hidden", shell.classList.contains("current--card") ? "false" : "true");
  });
}

/** 参考 CSS Cards：向右切 = 原右侧卡平移进中，仅给轮换到「右」位的那张壳子换新稿 */
function _careerNewsSpotlightSwapForward(slice) {
  const wrapper = document.querySelector("#careerNewsFeatured [data-career-news-cards-wrapper]");
  if (!wrapper) return;
  const currentEl = wrapper.querySelector(".career-news-spot-card.current--card");
  const previousEl = wrapper.querySelector(".career-news-spot-card.previous--card");
  const nextEl = wrapper.querySelector(".career-news-spot-card.next--card");
  if (!currentEl || !previousEl || !nextEl) return;

  const N = slice.length;
  const k = ((careerNewsState.spotlightIndex % N) + N) % N;
  const newNextIdx = (k + 2) % N;

  currentEl.classList.remove("current--card");
  previousEl.classList.remove("previous--card");
  nextEl.classList.remove("next--card");

  currentEl.classList.add("previous--card");
  nextEl.classList.add("current--card");
  previousEl.classList.add("next--card");

  currentEl.style.zIndex = "50";
  nextEl.style.zIndex = "42";
  previousEl.style.zIndex = "38";

  _careerNewsFillSpotCard(previousEl, slice[newNextIdx], "next");
  careerNewsState.spotlightIndex = (k + 1) % N;
  _syncSpotlightInnerRoles(wrapper);

  const trio = [currentEl, previousEl, nextEl];
  const clearZ = () => {
    trio.forEach((el) => {
      el.style.zIndex = "";
    });
  };
  previousEl.addEventListener(
    "transitionend",
    (e) => {
      if (e.propertyName === "transform") clearZ();
    },
    { once: true }
  );
  window.setTimeout(clearZ, 820);
}

function _careerNewsSpotlightSwapBackward(slice) {
  const wrapper = document.querySelector("#careerNewsFeatured [data-career-news-cards-wrapper]");
  if (!wrapper) return;
  const currentEl = wrapper.querySelector(".career-news-spot-card.current--card");
  const previousEl = wrapper.querySelector(".career-news-spot-card.previous--card");
  const nextEl = wrapper.querySelector(".career-news-spot-card.next--card");
  if (!currentEl || !previousEl || !nextEl) return;

  const N = slice.length;
  const k = ((careerNewsState.spotlightIndex % N) + N) % N;
  const newPrevIdx = (k - 2 + N) % N;

  currentEl.classList.remove("current--card");
  previousEl.classList.remove("previous--card");
  nextEl.classList.remove("next--card");

  currentEl.classList.add("next--card");
  previousEl.classList.add("current--card");
  nextEl.classList.add("previous--card");

  currentEl.style.zIndex = "50";
  previousEl.style.zIndex = "42";
  nextEl.style.zIndex = "38";

  _careerNewsFillSpotCard(nextEl, slice[newPrevIdx], "prev");
  careerNewsState.spotlightIndex = (k - 1 + N) % N;
  _syncSpotlightInnerRoles(wrapper);

  const trio = [currentEl, previousEl, nextEl];
  const clearZ = () => {
    trio.forEach((el) => {
      el.style.zIndex = "";
    });
  };
  nextEl.addEventListener(
    "transitionend",
    (e) => {
      if (e.propertyName === "transform") clearZ();
    },
    { once: true }
  );
  window.setTimeout(clearZ, 820);
}

function _renderCareerNewsSpotlight(visibleList) {
  const root = document.getElementById("careerNewsFeatured");
  if (!root) return;
  const wrapper = root.querySelector("[data-career-news-cards-wrapper]");
  const previousEl = wrapper?.querySelector(".career-news-spot-card.previous--card");
  const currentEl = wrapper?.querySelector(".career-news-spot-card.current--card");
  const nextEl = wrapper?.querySelector(".career-news-spot-card.next--card");
  if (!wrapper || !previousEl || !currentEl || !nextEl) return;

  [previousEl, currentEl, nextEl].forEach((el) => {
    el.innerHTML = "";
    el.style.zIndex = "";
  });

  const N = visibleList.length;
  wrapper.classList.toggle("career-news-cards-wrapper--single", N <= 1);

  if (!N) return;

  const i = ((careerNewsState.spotlightIndex % N) + N) % N;
  const ip = (i - 1 + N) % N;
  const ix = (i + 1) % N;

  _careerNewsFillSpotCard(previousEl, visibleList[ip], "prev");
  _careerNewsFillSpotCard(currentEl, visibleList[i], "current");
  _careerNewsFillSpotCard(nextEl, visibleList[ix], "next");
  _syncSpotlightInnerRoles(wrapper);
}

function _updateCareerNewsCarouselControls() {
  const prevBtn = document.getElementById("careerNewsPrevBtn");
  const nextBtn = document.getElementById("careerNewsNextBtn");
  const posEl = document.getElementById("careerNewsSpotlightPos");
  const countEl = document.getElementById("careerNewsShowingCount");
  const visibleCount = Math.min(Math.max(0, careerNewsState.visibleCount), careerNewsState.items.length);
  const workingLen = careerNewsState.items.length;
  const N = Math.min(visibleCount, workingLen);
  const idx = N ? ((careerNewsState.spotlightIndex % N) + N) % N : 0;
  const disableNav = N <= 1;
  if (prevBtn) prevBtn.disabled = disableNav;
  if (nextBtn) nextBtn.disabled = disableNav;
  if (posEl) posEl.textContent = N ? `${idx + 1} / ${N}` : "0 / 0";
  if (countEl) {
    countEl.textContent = `已加载 ${visibleCount} / ${workingLen} 条 · 当前第 ${N ? idx + 1 : 0} 条`;
  }
}

function _careerNewsScheduleAutoPlay() {
  _careerNewsClearAutoPlay();
  const visibleCount = Math.min(Math.max(0, careerNewsState.visibleCount), careerNewsState.items.length);
  if (visibleCount <= 1) {
    const bar = document.getElementById("careerNewsProgressBar");
    if (bar) bar.style.width = "0%";
    return;
  }
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) {
    const bar = document.getElementById("careerNewsProgressBar");
    if (bar) bar.style.width = "100%";
    // 仍定时换焦点；仅跳过进度条 RAF（与无障碍「减少动态效果」一致，不停止轮播）
  }
  _careerNewsResetProgressEpoch();
  careerNewsState.autoPlayTimer = window.setInterval(() => {
    careerNewsSlide(1, { fromTimer: true });
    _careerNewsResetProgressEpoch();
  }, 10000);
  if (!reducedMotion) {
    _careerNewsStartProgressLoop();
  }
}

function _applyCareerNewsBoard(options = {}) {
  const preserveSpotlight = Boolean(options.preservePage || options.preserveScroll);
  const board = document.getElementById("careerNewsBoard");
  const carousel = document.getElementById("careerNewsFeatured");
  const parking = document.getElementById("careerNewsListRows");
  const moreBtn = document.getElementById("careerNewsMoreBtn");
  if (!board || !carousel) return;
  _ensureCareerNewsFeaturedDom();
  const gridBoard = document.getElementById("careerNewsGridBoard");
  if (!gridBoard) return;

  const working = _getCareerNewsWorkingItems();
  working.forEach((el, idx) => {
    const rank = el.querySelector(".career-news-rank");
    if (rank) rank.textContent = String(idx + 1).padStart(2, "0");
  });

  if (parking) {
    careerNewsState.items.forEach((el) => {
      el.classList.remove("career-news-slide", "career-news-item--grid");
      parking.appendChild(el);
    });
  }

  gridBoard.innerHTML = "";
  const visibleCount = Math.min(Math.max(0, careerNewsState.visibleCount), working.length);
  const slice = working.slice(0, visibleCount);

  if (!slice.length) {
    if (moreBtn) {
      moreBtn.hidden = true;
      moreBtn.disabled = true;
    }
    const countEl = document.getElementById("careerNewsShowingCount");
    if (countEl) countEl.textContent = "当前展示 0 / 0 条";
    const bar = document.getElementById("careerNewsProgressBar");
    if (bar) bar.style.width = "0%";
    const prevE = document.getElementById("careerNewsPrevBtn");
    const nextE = document.getElementById("careerNewsNextBtn");
    if (prevE) prevE.disabled = true;
    if (nextE) nextE.disabled = true;
    _careerNewsClearAutoPlay();
    _renderCareerNewsSpotlight([]);
    return;
  }

  if (!preserveSpotlight) careerNewsState.spotlightIndex = 0;
  else {
    const N = slice.length;
    careerNewsState.spotlightIndex = Math.min(Math.max(0, careerNewsState.spotlightIndex), N - 1);
  }

  slice.forEach((el) => {
    el.classList.add("career-news-item--grid");
    gridBoard.appendChild(el);
  });

  _renderCareerNewsSpotlight(slice);

  if (moreBtn) {
    const hasMore = visibleCount < working.length;
    moreBtn.hidden = !hasMore;
    moreBtn.disabled = !hasMore;
    const labelSpan = moreBtn.querySelector("span");
    if (labelSpan) labelSpan.textContent = "加载更多（每次 10 条）";
    else moreBtn.textContent = "加载更多（每次 10 条）";
  }

  requestAnimationFrame(() => {
    _updateCareerNewsCarouselControls();
    _careerNewsScheduleAutoPlay();
  });
}

function _initCareerNewsBrief(board) {
  careerNewsState.initialized = true;
  const pool = document.getElementById("careerNewsPool");
  const content = document.getElementById("careerNewsBriefContent");
  if (!pool || !content) return;
  const items = [...pool.querySelectorAll(".nd-story")].sort((a, b) => _careerNewsPublishedTs(b) - _careerNewsPublishedTs(a));
  const filters = [...board.querySelectorAll("[data-news-filter]")];
  const more = document.getElementById("careerNewsMoreBtn");
  const count = document.getElementById("careerNewsShowingCount");
  const initialLimit = Math.max(1, Number(board.dataset.displayLimit) || 7);
  let category = "all";
  let limit = initialLimit;
  let focal = 0;
  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const pauseButton = document.getElementById("careerNewsPauseBtn");
  let manuallyPaused = motionPreference.matches;
  let hovered = false;
  let inView = !("IntersectionObserver" in window);
  let matchedCount = items.length;
  let timer = null;

  function scheduleAutoPlay() {
    window.clearTimeout(timer);
    timer = null;
    if (pauseButton) {
      pauseButton.textContent = manuallyPaused ? "▶" : "Ⅱ";
      pauseButton.setAttribute("aria-pressed", String(manuallyPaused));
      const label = manuallyPaused ? "开启自动切换" : "暂停自动切换";
      pauseButton.setAttribute("aria-label", label);
      pauseButton.title = label;
    }
    if (manuallyPaused || hovered || !inView || document.hidden || !board.isConnected || content.contains(document.activeElement) || matchedCount <= 1) return;
    timer = window.setTimeout(() => {
      timer = null;
      focal += 1;
      render(true);
    }, 8000);
  }

  board.addEventListener("error", (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    const media = image.closest(".nd-feature-media");
    if (media) media.remove();
    else image.hidden = true;
  }, true);

  function cloneStory(item, variant) {
    const node = item.cloneNode(true);
    if (variant) node.classList.add(variant);
    if (variant && item.dataset.image) {
      const media = document.createElement("span");
      media.className = "nd-feature-media";
      media.setAttribute("aria-hidden", "true");
      const cover = document.createElement("img");
      cover.className = "nd-feature-image";
      cover.width = 144;
      cover.height = 144;
      cover.alt = "";
      cover.loading = "lazy";
      cover.decoding = "async";
      cover.referrerPolicy = "no-referrer";
      cover.src = item.dataset.image;
      media.append(cover);
      node.prepend(media);
    }
    return node;
  }

  function render(focusOnly = false) {
    const matched = items.filter(item => category === "all" || item.dataset.category === category);
    matchedCount = matched.length;
    const index = matched.length ? ((focal % matched.length) + matched.length) % matched.length : 0;
    const featuredIndexes = matched.slice(0, 3).map((_, offset) => (index + offset) % matched.length);
    const remaining = matched.filter((_, i) => !featuredIndexes.includes(i)).slice(0, Math.max(0, limit - featuredIndexes.length));
    const visibleCount = featuredIndexes.length + remaining.length;
    const fragment = document.createDocumentFragment();
    filters.forEach(button => {
      const active = button.dataset.newsFilter === category;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (matched.length) {
      const deck = document.createElement("div");
      deck.className = "nd-deck";
      deck.setAttribute("aria-label", "焦点新闻");
      featuredIndexes.forEach(i => deck.append(cloneStory(matched[i], i === index ? "nd-story--lead" : "nd-story--side")));
      fragment.append(deck);
      if (remaining.length) {
        const label = document.createElement("div");
        label.className = "nd-section-label";
        label.textContent = "更多资讯";
        const grid = document.createElement("div");
        grid.className = "nd-grid";
        remaining.forEach(item => grid.append(cloneStory(item)));
        fragment.append(label, grid);
      }
    } else {
      const empty = document.createElement("div");
      empty.className = "nd-empty";
      empty.innerHTML = '<span class="nd-empty-symbol" aria-hidden="true">↗</span><h4>这个方向，静候新消息</h4><p>本期暂无此类资讯，切换其他分类发现更多内容。</p>';
      fragment.append(empty);
    }
    const oldDeck = content.querySelector(".nd-deck");
    const newDeck = fragment.querySelector(".nd-deck");
    if (focusOnly && oldDeck && newDeck) {
      newDeck.classList.add("is-switching");
      oldDeck.replaceWith(newDeck);
    } else {
      content.replaceChildren(fragment);
    }
    const countLabel = `已呈现 ${visibleCount} / ${matched.length} 则资讯`;
    if (count && count.textContent !== countLabel) count.textContent = countLabel;
    if (more) {
      more.hidden = visibleCount >= matched.length;
      more.disabled = more.hidden;
    }
    const position = document.getElementById("careerNewsSpotlightPos");
    if (position) position.textContent = `${String(matched.length ? index + 1 : 0).padStart(2, "0")} / ${String(matched.length).padStart(2, "0")}`;
    ["careerNewsPrevBtn", "careerNewsNextBtn"].forEach(id => {
      const button = document.getElementById(id);
      if (button) button.disabled = matched.length <= 1;
    });
    scheduleAutoPlay();
  }

  filters.forEach(button => button.addEventListener("click", () => {
    category = button.dataset.newsFilter;
    limit = initialLimit;
    focal = 0;
    render();
  }));
  function loadMore() { limit += 6; render(); }
  more?.addEventListener("click", loadMore);
  document.getElementById("careerNewsPrevBtn")?.addEventListener("click", () => { focal -= 1; render(true); });
  document.getElementById("careerNewsNextBtn")?.addEventListener("click", () => { focal += 1; render(true); });
  pauseButton?.addEventListener("click", () => {
    manuallyPaused = !manuallyPaused;
    scheduleAutoPlay();
  });
  board.addEventListener("pointerenter", event => {
    if (event.pointerType === "mouse") { hovered = true; scheduleAutoPlay(); }
  });
  board.addEventListener("pointerleave", () => { hovered = false; scheduleAutoPlay(); });
  board.addEventListener("focusin", scheduleAutoPlay);
  board.addEventListener("focusout", () => window.setTimeout(scheduleAutoPlay, 0));
  document.addEventListener("visibilitychange", scheduleAutoPlay);
  motionPreference.addEventListener("change", event => {
    manuallyPaused = event.matches;
    scheduleAutoPlay();
  });
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(entries => {
      inView = entries.some(entry => entry.isIntersecting);
      scheduleAutoPlay();
    });
    observer.observe(board.querySelector(".nd-toolbar") || board);
  }
  board.addEventListener("news:more", loadMore);
  render();
}

function initCareerNewsBoard() {
  const board = document.getElementById("careerNewsBoard");
  if (!board || careerNewsState.initialized) return;
  if (board.dataset.layout === "brief") return _initCareerNewsBrief(board);
  careerNewsState.initialized = true;
  careerNewsState.displayLimit = Math.max(1, Number(board.dataset.displayLimit || 10));
  careerNewsState.pageSize = 10;
  const pool = document.getElementById("careerNewsPool");
  careerNewsState.items = [...(pool || board).querySelectorAll(".career-news-item")];
  /* 首屏 displayLimit 条（默认 10）；顶部三卡轮排在批次内循环；下方 2×5 概览；加载更多 +10 */
  careerNewsState.visibleCount = Math.min(
    careerNewsState.displayLimit,
    careerNewsState.items.length
  );

  document.getElementById("careerNewsPrevBtn")?.addEventListener("click", () => careerNewsSlide(-1));
  document.getElementById("careerNewsNextBtn")?.addEventListener("click", () => careerNewsSlide(1));
  document.getElementById("careerNewsMoreBtn")?.addEventListener("click", () => careerNewsLoadMore());
  window.addEventListener("resize", () => {
    _updateCareerNewsCarouselControls();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) _careerNewsClearAutoPlay();
    else _careerNewsScheduleAutoPlay();
  });
  const spotlightVp = document.querySelector("#careerNewsFeatured .career-news-spotlight-viewport");
  spotlightVp?.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      careerNewsSlide(-1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      careerNewsSlide(1);
    }
  });
  _applyCareerNewsBoard();
}

function careerNewsSlide(direction = 1, opts = {}) {
  if (!careerNewsState.initialized) initCareerNewsBoard();
  const visibleCount = Math.min(Math.max(0, careerNewsState.visibleCount), careerNewsState.items.length);
  const slice = _getCareerNewsWorkingItems().slice(0, visibleCount);
  const N = visibleCount;
  if (N <= 1) {
    careerNewsState.spotlightIndex = 0;
    _renderCareerNewsSpotlight(slice);
    _updateCareerNewsCarouselControls();
    if (!opts.fromTimer) {
      _careerNewsClearAutoPlay();
      _careerNewsScheduleAutoPlay();
    }
    return;
  }

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const narrow = window.matchMedia("(max-width: 620px)").matches;
  if (reduced || narrow) {
    careerNewsState.spotlightIndex = (careerNewsState.spotlightIndex + direction + N) % N;
    _renderCareerNewsSpotlight(slice);
    _updateCareerNewsCarouselControls();
    if (!opts.fromTimer) {
      _careerNewsClearAutoPlay();
      _careerNewsScheduleAutoPlay();
    }
    return;
  }

  if (direction === 1) _careerNewsSpotlightSwapForward(slice);
  else _careerNewsSpotlightSwapBackward(slice);

  _updateCareerNewsCarouselControls();
  if (opts.fromTimer) return;
  _careerNewsClearAutoPlay();
  _careerNewsScheduleAutoPlay();
}

function careerNewsLoadMore() {
  if (!careerNewsState.initialized) initCareerNewsBoard();
  const board = document.getElementById("careerNewsBoard");
  if (board?.dataset.layout === "brief") {
    board.dispatchEvent(new Event("news:more"));
    return;
  }
  careerNewsState.visibleCount = Math.min(
    careerNewsState.visibleCount + careerNewsState.pageSize,
    careerNewsState.items.length
  );
  _applyCareerNewsBoard({ preservePage: true, preserveScroll: true });
}

// 兼容旧调用
function careerNewsGoPage(page) {
  if (!careerNewsState.initialized) initCareerNewsBoard();
  if (Number(page) > 1) careerNewsLoadMore();
  else careerNewsSlide(-1);
  const board = document.getElementById("careerNewsBoard");
  if (board) board.scrollIntoView({ behavior: "smooth", block: "start" });
}

function toggleCareerNewsMore() { careerNewsLoadMore(); }

function clampPercent(value, fallback = 0) {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.max(0, Math.min(100, Math.round(num)));
}

function averageValues(values) {
  const list = Array.isArray(values) ? values.filter((value) => Number.isFinite(Number(value))) : [];
  if (!list.length) return null;
  return Math.round(list.reduce((sum, value) => sum + Number(value), 0) / list.length);
}

function uniqueValues(values, limit = 6) {
  return [...new Set((Array.isArray(values) ? values : []).map((item) => String(item || "").trim()).filter(Boolean))].slice(0, limit);
}
