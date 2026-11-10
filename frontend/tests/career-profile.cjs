const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const screenshotDir = process.env.CAREER_TEST_SCREENSHOTS;
    const screenshot = async name => {
      if (!screenshotDir) return;
      fs.mkdirSync(screenshotDir, { recursive: true });
      await page.screenshot({ path: path.join(screenshotDir, name), fullPage: true });
    };
    await page.setContent(`<body class="user-center-page"><main style="padding:28px;max-width:1400px;margin:auto">${fs.readFileSync(path.join(__dirname, "../templates/partials/career_profile.html"), "utf8")}</main></body>`);
    for (const name of ["styles.css", "user-center.css", "career-profile.css", "product-theme.css"]) {
      await page.addStyleTag({ content: fs.readFileSync(path.join(__dirname, "../static/", name), "utf8") });
    }
    // The fixture displays the section without the app's fixed-height workspace shell.
    await page.addStyleTag({ content: '#career-profile { height:auto; overflow:visible; }' });
    await page.addScriptTag({ content: `
      const fixture = { profile: {id:'profile-1',display_name:'Test User',stage:'graduate',city:'杭州',source_type:'manual',version:1}, entries:[],skills:[],evidence:[],goals:[],assessments:[],resumes:[],memories:[],evidence_levels:{} };
      window.getCurrentUser = () => ({ username:'test',display_name:'Test User' });
      window.requestJson = async (url, options = {}) => {
        if (options.method === 'POST' || options.method === 'PUT') {
          const body = options.body;
          if (url.includes('/entries')) {
            const allowed = ['version','title','description','kind'];
            if (Object.keys(body).some(key => !allowed.includes(key))) throw Error('Unexpected API field');
            const id = options.method === 'POST' ? 'entry-' + fixture.entries.length : url.split('/').at(-1);
            const row = { ...body,id,source_type:'manual',updated_at:'2026-11-10',version:body.version + 1 };
            fixture.entries = fixture.entries.filter(entry => entry.id !== id).concat(row);
          }
          return {data:body};
        }
        return {data:JSON.parse(JSON.stringify(fixture))};
      };
    ` });
    await page.addScriptTag({ content: fs.readFileSync(path.join(__dirname, "../static/career-profile.js"), "utf8") });
    await page.evaluate(() => { document.dispatchEvent(new Event("DOMContentLoaded")); return window.loadCareerProfile(); });
    assert.equal(await page.locator(".cp-entry-empty").count(), 5);
    await screenshot("career-profile-empty.png");
    const examples = [
      ["education", "浙江大学", { major:"计算机科学与技术",degree:"本科",period:"2023.09 — 2027.06" }, "参与机器学习研究与软件工程课程项目。"],
      ["experience", "智能求职助手", { role:"后端开发",organization:"校内创新团队",period:"2026.03 — 至今" }, "搭建多智能体分析流程。\n完成报告生成与可编辑工作台。"],
      ["certificate", "大学英语六级", { issuer:"教育部教育考试院",obtained:"2026.06" }, "成绩 560 分。"],
      ["interest", "AI 产品与应用开发", { activity:"开源贡献、产品设计" }, "喜欢把想法做成可用的工具。"],
      ["preference", "我的第一份实习", { cities:"杭州、上海",mode:"线下办公",industry:"人工智能" }, "每周可出勤 4 天。"]
    ];
    for (const [kind,title,fields,description] of examples) {
      await page.locator(`.cp-entry-empty[data-kind="${kind}"]`).click();
      await page.locator('#cpField-title').fill(title);
      for (const [name,value] of Object.entries(fields)) await page.locator('#cpField-entry_' + name).fill(value);
      await page.locator('#cpField-description').fill(description);
      await page.locator('#cpSave').click();
      await page.locator('#cpEditor').waitFor({ state: 'hidden' });
      assert.equal(await page.locator('.cp-entry--' + kind + ' h4').textContent(), title);
      await page.locator(`.cp-entry--${kind} [data-cp-action="edit"]`).click();
      for (const [name,value] of Object.entries(fields)) assert.equal(await page.locator('#cpField-entry_' + name).inputValue(), value);
      assert.equal(await page.locator('#cpField-description').inputValue(), description);
      // A second save must not duplicate structured metadata.
      await page.locator('#cpSave').click();
      await page.locator('#cpEditor').waitFor({ state: 'hidden' });
    }
    assert.equal(await page.locator('.cp-progress-track .is-filled').count(), 5);
    await page.evaluate(() => scrollTo(0, 0));
    await screenshot("career-profile-filled.png");
    await page.setViewportSize({ width:390,height:844 });
    await page.evaluate(() => scrollTo(0, 0));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await screenshot("career-profile-mobile.png");
    await page.locator('.cp-entry--experience [data-cp-action="edit"]').click();
    assert(await page.evaluate(() => document.getElementById('cpEditor').scrollWidth <= document.getElementById('cpEditor').clientWidth));
    console.log('PASS: five entry types create/edit/save, structured fields round-trip, progress updates, mobile layout fits.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
