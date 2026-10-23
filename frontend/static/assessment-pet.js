/**
 * assessment-pet.js
 * 卡通助手嵌入 Modal 左侧"当前状态"卡片底部（#assessmentPetSlot）
 * 不修改 assessment-hub.js，通过包装 window 函数 + 监听事件实现联动
 */
(function () {
  const GIF_BASE = "/static/pet/";
  const GIFS = {
    idle:  GIF_BASE + "clawd-mini-idle.gif",
    enter: GIF_BASE + "clawd-mini-enter.gif",
    happy: GIF_BASE + "clawd-mini-happy.gif",
    peek:  GIF_BASE + "clawd-mini-peek.gif",
    alert: GIF_BASE + "clawd-mini-alert.gif",
    think: GIF_BASE + "clawd-thinking.gif",
    cheer: GIF_BASE + "clawd-happy.gif",
    sleep: GIF_BASE + "clawd-sleeping.gif",
  };

  const SPEECHES = {
    enter:        ["来啦！我们一起完成测评吧 ✨", "准备好了吗？我陪你一起答题 🎯", "加油！每道题都很重要哦 🌟"],
    answer:       ["答得不错！", "继续保持 💪", "很棒！", "嗯嗯，很认真 👍", "这题答得好！", "你很了解自己呢 ✨"],
    quarter:      ["才开始，慢慢来 🌱", "别急，认真想想 🤔", "每道题都是了解自己的机会！"],
    half:         ["做到一半啦！继续加油 ⚡", "节奏很好，坚持住！", "过半了，你很棒 🎉"],
    most:         ["快完成了！再坚持一下 🔥", "最后冲刺！加油 ✨", "眼看就完成了，不要放弃 💪"],
    done_mbti:    ["MBTI 完成！你了解自己了 🎊", "性格测评完成，结果很有趣哦 🧠", "厉害！MBTI 全搞定 🎉"],
    done_holland: ["霍兰德完成！兴趣画像清晰多了 🗺️", "测评完成！你知道自己喜欢什么了 ✨", "太棒了！霍兰德测评搞定 🎉"],
    done_both:    ["双测评全部完成！太厉害了 🏆", "两个测评都搞定啦！厉害 🎊", "全部完成！去看看你的职业画像吧 🌟"],
    idle:         ["我等你哦～", "不用急，想好再选 🤔", "有我陪着呢 😊", "认真思考是好事 💭"],
    sleep:        ["Zzz... 叫我别睡了...", "打了个盹... 我在 Zzz"],
  };

  function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  // ── 样式 ──────────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("assessment-pet-styles")) return;
    const s = document.createElement("style");
    s.id = "assessment-pet-styles";
    s.textContent = `
      .assessment-pet-slot {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        margin-top: 8px;
        min-height: 152px;
        padding: 4px 0 2px;
      }
      .assessment-pet-slot .pet-img {
        width: 132px;
        height: 132px;
        max-width: 100%;
        object-fit: contain;
        display: block;
        filter: drop-shadow(0 4px 12px rgba(0,0,0,0.14));
      }
      .assessment-pet-slot .pet-bubble {
        background: #fff;
        border: 1.5px solid #e0e7ff;
        border-radius: 12px 12px 12px 4px;
        padding: 6px 10px;
        font-size: 11.5px;
        line-height: 1.5;
        color: #3730a3;
        width: 100%;
        box-sizing: border-box;
        margin-bottom: 6px;
        box-shadow: 0 2px 10px rgba(99,102,241,0.10);
        white-space: normal;
        word-break: break-all;
        animation: pet-bubble-in 0.22s ease forwards;
      }
      .assessment-pet-slot .pet-bubble.hidden { display: none; }
      @keyframes pet-bubble-in {
        from { opacity: 0; transform: translateY(4px) scale(0.94); }
        to   { opacity: 1; transform: translateY(0) scale(1); }
      }
    `;
    document.head.appendChild(s);
  }

  // ── 状态 ──────────────────────────────────────────────────────────────────
  let gifEl = null;
  let bubbleEl = null;
  let bubbleTimer = null;
  let idleTimer = null;
  let sleepTimer = null;
  let lastAnsweredCount = 0;
  let currentGif = "idle";
  let slotMounted = false;

  // 找 slot 并注入 GIF + 气泡（Modal 打开后 DOM 才稳定）
  function ensureMount() {
    const slot = document.getElementById("assessmentPetSlot");
    if (!slot) return false;
    if (!slotMounted) {
      slot.innerHTML = `
        <div id="pet-bubble" class="pet-bubble hidden"></div>
        <img id="pet-gif" src="${GIFS.idle}" alt="pet" class="pet-img" />
      `;
      gifEl    = document.getElementById("pet-gif");
      bubbleEl = document.getElementById("pet-bubble");
      slotMounted = true;
    }
    return true;
  }

  function setGif(name) {
    if (currentGif === name) return;
    currentGif = name;
    if (gifEl) { gifEl.src = ""; gifEl.src = GIFS[name] || GIFS.idle; }
  }

  function showBubble(text, duration = 3000) {
    clearTimeout(bubbleTimer);
    if (!bubbleEl) return;
    bubbleEl.textContent = text;
    bubbleEl.classList.remove("hidden");
    bubbleEl.style.animation = "none";
    void bubbleEl.offsetWidth;
    bubbleEl.style.animation = "";
    bubbleTimer = setTimeout(() => { if (bubbleEl) bubbleEl.classList.add("hidden"); }, duration);
  }

  function resetIdleTimers() {
    clearTimeout(idleTimer);
    clearTimeout(sleepTimer);
    idleTimer = setTimeout(() => {
      if (currentGif === "idle") showBubble(pick(SPEECHES.idle), 3500);
    }, 15000);
    sleepTimer = setTimeout(() => {
      if (currentGif === "idle") { setGif("sleep"); showBubble(pick(SPEECHES.sleep), 4000); }
    }, 40000);
  }

  // ── 事件处理 ──────────────────────────────────────────────────────────────
  function onModalOpen() {
    // 预加载 GIF（首次触发才执行）
    if (!onModalOpen._preloaded) {
      onModalOpen._preloaded = true;
      Object.values(GIFS).forEach((src) => { const i = new Image(); i.src = src; });
    }
    // Modal 渲染是同步的，但 innerHTML 刷新需等一帧
    requestAnimationFrame(() => {
      if (!ensureMount()) return;
      currentGif = "idle"; // 重置状态，避免 setGif 跳过
      setGif("enter");
      showBubble(pick(SPEECHES.enter), 3000);
      resetIdleTimers();
      setTimeout(() => { if (currentGif === "enter") setGif("idle"); }, 2200);
    });
  }

  function onModalClose() {
    clearTimeout(idleTimer);
    clearTimeout(sleepTimer);
    clearTimeout(bubbleTimer);
    // slot 会随 modal DOM 一起隐藏，无需额外操作
    slotMounted = false;
    gifEl = null;
    bubbleEl = null;
  }

  function getAnsweredCount(snap) {
    return (snap?.mbti?.answered_count || 0) + (snap?.holland?.answered_count || 0);
  }

  function onHubUpdated(snapshot) {
    if (!snapshot || !slotMounted) return;

    const mbtiDone    = snapshot.mbti?.completed;
    const hollandDone = snapshot.holland?.completed;
    const total       = getAnsweredCount(snapshot);
    const newAnswer   = total > lastAnsweredCount;
    lastAnsweredCount = total;

    if (mbtiDone && hollandDone) {
      setGif("cheer"); showBubble(pick(SPEECHES.done_both), 4500);
      setTimeout(() => setGif("idle"), 4000); resetIdleTimers(); return;
    }
    if (mbtiDone && newAnswer) {
      setGif("cheer"); showBubble(pick(SPEECHES.done_mbti), 4000);
      setTimeout(() => setGif("idle"), 3500); resetIdleTimers(); return;
    }
    if (hollandDone && newAnswer) {
      setGif("cheer"); showBubble(pick(SPEECHES.done_holland), 4000);
      setTimeout(() => setGif("idle"), 3500); resetIdleTimers(); return;
    }

    if (newAnswer) {
      setGif("happy"); showBubble(pick(SPEECHES.answer), 1800); resetIdleTimers();
      const mAns = snapshot.mbti?.answered_count || 0;
      const hAns = snapshot.holland?.answered_count || 0;
      setTimeout(() => {
        if (currentGif !== "happy") return;
        const nearEnd = mAns / 93 > 0.8 || hAns / 90 > 0.8;
        setGif(nearEnd ? "alert" : "idle");
        if (nearEnd) {
          setTimeout(() => { showBubble(pick(SPEECHES.most), 2500); setTimeout(() => setGif("idle"), 2000); }, 300);
        } else {
          const p = (mAns + hAns) / 183;
          if (p > 0.5 && p < 0.55) showBubble(pick(SPEECHES.half), 2500);
          else if (p > 0.25 && p < 0.28) showBubble(pick(SPEECHES.quarter), 2500);
        }
      }, 1500);
    }
  }

  // ── 钩子安装 ──────────────────────────────────────────────────────────────
  function installHooks() {
    const origOpen  = window.openAssessmentModal;
    const origClose = window.closeAssessmentModal;

    if (origOpen) {
      window.openAssessmentModal = function () {
        const r = origOpen.apply(this, arguments);
        onModalOpen();
        return r;
      };
    }
    if (origClose) {
      window.closeAssessmentModal = function () {
        const r = origClose.apply(this, arguments);
        onModalClose();
        return r;
      };
    }

    // 点击遮罩关闭
    const overlay = document.getElementById("assessmentModal");
    if (overlay) {
      overlay.addEventListener("click", (e) => { if (e.target === overlay) onModalClose(); });
    }

    window.addEventListener("assessment-hub:updated", (e) => {
      const modal = document.getElementById("assessmentModal");
      if (modal && !modal.classList.contains("hidden")) onHubUpdated(e.detail);
    });
  }

  // ── 初始化 ────────────────────────────────────────────────────────────────
  function init() {
    injectStyles();
    installHooks();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    setTimeout(init, 0);
  }
})();
