/**
 * TourGuide — 职业规划智能体使用引导
 * 7步 Spotlight 引导，localStorage 记录完成状态
 */
(function () {
  'use strict';

  var STEPS = [
    {
      title: '欢迎使用职业规划智能体 👋',
      content: '我来带你快速了解各功能模块。<br><br>推荐使用流程：<br><span class="tg-flow"><span class="tg-step-tag">1</span>能力画像<span class="tg-arrow">→</span><span class="tg-step-tag">2</span>岗位探索<span class="tg-arrow">→</span><span class="tg-step-tag">3</span>人岗匹配<span class="tg-arrow">→</span><span class="tg-step-tag">4</span>规划报告</span>',
      target: null,
    },
    {
      title: '① 能力画像 — 从这里开始',
      content: '上传简历或手动填写基本信息，AI 自动生成你的六维能力雷达图。<br>这是所有后续分析的基础数据来源。',
      target: '[data-section="profile"]',
    },
    {
      title: '② 岗位探索 — 了解市场',
      content: '浏览 100+ 热门岗位，查看技能要求和薪资区间，收藏感兴趣的方向，构建岗位画像。',
      target: '[data-section="jobs"]',
    },
    {
      title: '③ 人岗匹配 — 找到差距',
      content: '系统将你的能力画像与目标岗位比对，输出匹配度评分和具体差距分析，明确提升重点。',
      target: '[data-section="matching"]',
    },
    {
      title: '④ 规划报告 — 你的行动方案',
      content: '整合以上数据后，系统生成专属职业规划报告，包含学习路径、证书建议和里程碑时间线。',
      target: '[data-section="report"]',
    },
    {
      title: '智能仪表盘 — 查看全局进度',
      content: '你现在所在的位置。实时显示画像成熟度、匹配情况和待办任务，让你随时掌握整体状态。',
      target: '[data-section="dashboard"]',
    },
  ];

  var current = 0;

  /* ── 样式注入 ── */
  function injectStyles() {
    var style = document.createElement('style');
    style.id = 'tour-guide-style';
    style.textContent = [
      '#tg-wrap { display:none; }',
      '#tg-wrap.tg-active { display:block; }',

      /* 四块遮罩 */
      '.tg-mask {',
      '  position:fixed; background:rgba(0,0,0,0.62);',
      '  z-index:9200; transition:all 0.32s cubic-bezier(.4,0,.2,1);',
      '  pointer-events:all; cursor:default;',
      '}',

      /* 高亮边框 */
      '#tg-hl {',
      '  position:fixed; z-index:9201; border-radius:10px;',
      '  border:2px solid rgba(139,92,246,0.9);',
      '  box-shadow:0 0 0 4px rgba(139,92,246,0.2),0 0 24px rgba(139,92,246,0.35);',
      '  pointer-events:none;',
      '  transition:all 0.32s cubic-bezier(.4,0,.2,1);',
      '}',

      /* 提示卡片 */
      '#tg-tip {',
      '  position:fixed; z-index:9300;',
      '  background:#fff; border-radius:14px;',
      '  padding:20px 22px 18px;',
      '  width:308px; max-width:calc(100vw - 32px);',
      '  box-shadow:0 24px 60px rgba(0,0,0,0.28),0 0 0 1px rgba(0,0,0,0.05);',
      '  transition:top 0.32s cubic-bezier(.4,0,.2,1),left 0.32s cubic-bezier(.4,0,.2,1);',
      '  pointer-events:all;',
      '}',

      /* 进度条 */
      '#tg-prog { display:flex; gap:4px; margin-bottom:13px; }',
      '.tg-dot {',
      '  height:3px; flex:1; border-radius:2px;',
      '  background:#e5e7eb; transition:background 0.25s;',
      '}',
      '.tg-dot.tg-done { background:#7c3aed; }',

      /* 步骤标签 */
      '#tg-label {',
      '  font-size:11px; color:#a78bfa; font-weight:700;',
      '  letter-spacing:0.06em; text-transform:uppercase; margin-bottom:6px;',
      '}',

      /* 标题 */
      '#tg-tip h4 {',
      '  font-size:15px; font-weight:700; color:#111827;',
      '  margin:0 0 8px; line-height:1.4;',
      '}',

      /* 正文 */
      '#tg-tip p {',
      '  font-size:13px; color:#6b7280;',
      '  line-height:1.75; margin:0 0 16px;',
      '}',

      /* 流程标签（第一步用） */
      '.tg-flow {',
      '  display:inline-flex; align-items:center; flex-wrap:wrap;',
      '  gap:4px; margin-top:6px;',
      '}',
      '.tg-step-tag {',
      '  display:inline-flex; align-items:center; justify-content:center;',
      '  width:16px; height:16px; border-radius:50%;',
      '  background:#7c3aed; color:#fff; font-size:10px; font-weight:700;',
      '}',
      '.tg-arrow { color:#9ca3af; font-size:12px; }',

      /* 按钮区 */
      '#tg-acts { display:flex; gap:8px; align-items:center; }',

      '.tg-btn-pri {',
      '  flex:1; background:#7c3aed; color:#fff;',
      '  border:none; border-radius:8px;',
      '  padding:8px 16px; font-size:13px; font-weight:600;',
      '  cursor:pointer; transition:background 0.18s;',
      '}',
      '.tg-btn-pri:hover { background:#6d28d9; }',

      '.tg-btn-sec {',
      '  background:#f3f4f6; color:#6b7280;',
      '  border:none; border-radius:8px;',
      '  padding:8px 12px; font-size:13px;',
      '  cursor:pointer; transition:background 0.18s;',
      '}',
      '.tg-btn-sec:hover { background:#e5e7eb; }',

      '.tg-btn-skip {',
      '  background:none; color:#d1d5db;',
      '  border:none; font-size:12px;',
      '  cursor:pointer; margin-left:auto; padding:4px;',
      '  transition:color 0.15s;',
      '}',
      '.tg-btn-skip:hover { color:#9ca3af; }',

      /* 悬浮引导入口按钮 */
      '#tg-fab {',
      '  position:fixed; bottom:28px; right:24px;',
      '  z-index:9100;',
      '  width:46px; height:46px; border-radius:50%;',
      '  background:linear-gradient(135deg,#7c3aed,#6d28d9);',
      '  color:#fff; border:none; cursor:pointer;',
      '  font-size:18px; font-weight:700;',
      '  box-shadow:0 4px 20px rgba(109,40,217,0.45);',
      '  display:flex; align-items:center; justify-content:center;',
      '  transition:transform 0.2s,box-shadow 0.2s;',
      '  outline:none;',
      '}',
      '#tg-fab:hover {',
      '  transform:scale(1.1);',
      '  box-shadow:0 6px 24px rgba(109,40,217,0.6);',
      '}',
      '#tg-fab-tip {',
      '  position:fixed; bottom:82px; right:24px;',
      '  z-index:9100;',
      '  background:#1f2937; color:#fff;',
      '  font-size:12px; padding:6px 12px;',
      '  border-radius:8px; white-space:nowrap;',
      '  opacity:0; pointer-events:none;',
      '  transition:opacity 0.2s;',
      '}',
      '#tg-fab:hover + #tg-fab-tip,',
      '#tg-fab-tip:hover { opacity:1; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  /* ── HTML 注入 ── */
  function injectHTML() {
    var n = STEPS.length;

    // 主引导容器
    var wrap = document.createElement('div');
    wrap.id = 'tg-wrap';
    wrap.innerHTML = [
      '<div class="tg-mask" id="tg-mt"></div>',
      '<div class="tg-mask" id="tg-mb"></div>',
      '<div class="tg-mask" id="tg-ml"></div>',
      '<div class="tg-mask" id="tg-mr"></div>',
      '<div id="tg-hl"></div>',
      '<div id="tg-tip">',
      '  <div id="tg-prog">' + Array(n).fill('<div class="tg-dot"></div>').join('') + '</div>',
      '  <div id="tg-label">步骤 1 / ' + n + '</div>',
      '  <h4 id="tg-title"></h4>',
      '  <p id="tg-content"></p>',
      '  <div id="tg-acts">',
      '    <button class="tg-btn-sec" id="tg-prev">← 上一步</button>',
      '    <button class="tg-btn-pri" id="tg-next">下一步 →</button>',
      '    <button class="tg-btn-skip" id="tg-skip">跳过</button>',
      '  </div>',
      '</div>',
    ].join('');
    document.body.appendChild(wrap);

    // 悬浮按钮
    var fab = document.createElement('button');
    fab.id = 'tg-fab';
    fab.title = '使用引导';
    fab.innerHTML = '?';
    fab.addEventListener('click', function () { TourGuide.start(); });
    document.body.appendChild(fab);

    var fabTip = document.createElement('div');
    fabTip.id = 'tg-fab-tip';
    fabTip.textContent = '重新引导';
    document.body.appendChild(fabTip);

    // 事件绑定
    document.getElementById('tg-next').addEventListener('click', function () { TourGuide.next(); });
    document.getElementById('tg-prev').addEventListener('click', function () { TourGuide.prev(); });
    document.getElementById('tg-skip').addEventListener('click', function () { TourGuide.end(); });

    // 点遮罩关闭
    ['tg-mt', 'tg-mb', 'tg-ml', 'tg-mr'].forEach(function (id) {
      document.getElementById(id).addEventListener('click', function () { TourGuide.end(); });
    });

    // 键盘操作
    document.addEventListener('keydown', function (e) {
      if (!document.getElementById('tg-wrap').classList.contains('tg-active')) return;
      if (e.key === 'ArrowRight' || e.key === 'Enter') TourGuide.next();
      if (e.key === 'ArrowLeft') TourGuide.prev();
      if (e.key === 'Escape') TourGuide.end();
    });
  }

  /* ── 定位逻辑 ── */
  function positionStep(step) {
    var dots = document.querySelectorAll('#tg-prog .tg-dot');
    dots.forEach(function (d, i) {
      d.classList.toggle('tg-done', i <= current);
    });
    document.getElementById('tg-label').textContent = '步骤 ' + (current + 1) + ' / ' + STEPS.length;
    document.getElementById('tg-title').textContent = step.title;
    document.getElementById('tg-content').innerHTML = step.content;

    var prevBtn = document.getElementById('tg-prev');
    var nextBtn = document.getElementById('tg-next');
    var skipBtn = document.getElementById('tg-skip');
    prevBtn.style.display = current === 0 ? 'none' : '';
    var isLast = current === STEPS.length - 1;
    nextBtn.textContent = isLast ? '完成 ✓' : '下一步 →';
    skipBtn.style.display = isLast ? 'none' : '';

    var mt = document.getElementById('tg-mt');
    var mb = document.getElementById('tg-mb');
    var ml = document.getElementById('tg-ml');
    var mr = document.getElementById('tg-mr');
    var hl = document.getElementById('tg-hl');
    var tip = document.getElementById('tg-tip');

    if (!step.target) {
      // 居中模式：整屏遮罩
      Object.assign(mt.style, { top: '0', left: '0', right: '0', bottom: '0', width: '', height: '' });
      mb.style.display = 'none';
      ml.style.display = 'none';
      mr.style.display = 'none';
      hl.style.display = 'none';

      tip.style.top = '50%';
      tip.style.left = '50%';
      tip.style.transform = 'translate(-50%,-50%)';
      tip.style.bottom = 'auto';
      return;
    }

    mb.style.display = '';
    ml.style.display = '';
    mr.style.display = '';
    mt.style.bottom = 'auto';
    mt.style.width = '';
    hl.style.display = 'block';
    tip.style.transform = '';

    var el = document.querySelector(step.target);
    if (!el) return;
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });

    // 延迟一帧确保滚动完成后取正确坐标
    requestAnimationFrame(function () {
      var r = el.getBoundingClientRect();
      var pad = 7;
      var t = r.top - pad, l = r.left - pad, b = r.bottom + pad, ri = r.right + pad;

      // 四块遮罩
      Object.assign(mt.style, { top: '0', left: '0', right: '0', height: t + 'px', bottom: 'auto', width: '' });
      Object.assign(mb.style, { top: b + 'px', left: '0', right: '0', bottom: '0', height: '', width: '' });
      Object.assign(ml.style, { top: t + 'px', left: '0', width: l + 'px', height: (b - t) + 'px', right: 'auto', bottom: 'auto' });
      Object.assign(mr.style, { top: t + 'px', left: ri + 'px', right: '0', height: (b - t) + 'px', width: '', bottom: 'auto' });

      // 高亮框
      Object.assign(hl.style, { top: t + 'px', left: l + 'px', width: (ri - l) + 'px', height: (b - t) + 'px' });

      // 定位提示卡
      var vw = window.innerWidth, vh = window.innerHeight;
      var tw = 308, th = 200;
      var tx = l, ty;

      if (b + th + 14 < vh) {
        ty = b + 14;
      } else if (t - th - 14 > 60) {
        ty = t - th - 14;
      } else {
        ty = Math.max(60, (vh - th) / 2);
      }

      if (tx + tw > vw - 16) tx = vw - tw - 16;
      if (tx < 16) tx = 16;

      tip.style.top = ty + 'px';
      tip.style.left = tx + 'px';
      tip.style.bottom = 'auto';
    });
  }

  /* ── 公开 API ── */
  window.TourGuide = {
    start: function () {
      current = 0;
      document.getElementById('tg-wrap').classList.add('tg-active');
      positionStep(STEPS[current]);
    },
    next: function () {
      if (current < STEPS.length - 1) {
        current++;
        positionStep(STEPS[current]);
      } else {
        this.end();
      }
    },
    prev: function () {
      if (current > 0) {
        current--;
        positionStep(STEPS[current]);
      }
    },
    end: function () {
      document.getElementById('tg-wrap').classList.remove('tg-active');
      localStorage.setItem('tg_done', '1');
    },
  };

  /* ── 初始化 ── */
  function init() {
    injectStyles();
    injectHTML();
    // 新用户自动启动（延迟等待登录完成）
    if (!localStorage.getItem('tg_done')) {
      var timer = setInterval(function () {
        // 等待登录屏消失后才启动
        var screen = document.getElementById('startupScreen');
        if (!screen || screen.classList.contains('hidden')) {
          clearInterval(timer);
          setTimeout(function () { TourGuide.start(); }, 600);
        }
      }, 300);
      // 最多等 30 秒
      setTimeout(function () { clearInterval(timer); }, 30000);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
