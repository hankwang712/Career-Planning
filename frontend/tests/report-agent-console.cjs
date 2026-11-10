const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1550, height: 900 } });
    await page.route("**/*", route => route.abort());
    await page.setContent('<div id="reportAgentMap"></div>');
    await page.addStyleTag({ content: fs.readFileSync(path.join(__dirname, "../static/styles.css"), "utf8") });
    const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
    const consoleCode = source.slice(source.indexOf("const REPORT_AGENT_IMAGE_URL"), source.indexOf("const CAREER_REPORT_POLL_MS"));
    await page.addScriptTag({ content: `
      let accountRequestEpoch = 1;
      const appState = {};
      const userWorkspaceState = { currentUser: { username: 'test' } };
      const state = { report_id: 'test', status: 'running', stage: 'job_analysis', updated_at: '1' };
      window.getCareerReportStateSafe = () => state;
      function escHtml(value) { return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'); }
      let finishSnapshot;
      function requestJson() { return new Promise(resolve => { finishSnapshot = resolve; }); }
      ${consoleCode}
      window.testConsole = async () => {
        const map = document.getElementById('reportAgentMap');
        updateReportAgentMap(map, {}, []);
        reportAgentConsoleState.selected = 'job_analysis';
        reportAgentConsoleState.snapshot = { results: {} };
        renderReportAgentInspector(map);
        const panel = map.querySelector('.report-agent-inspector');
        const canvas = map.querySelector('.report-console-canvas');
        const card = map.querySelector('[data-agent-key="job_analysis"]');
        const tab = panel.querySelector('[data-agent-tab="overview"]');
        tab.focus();
        const height = panel.getBoundingClientRect().height;
        // Repeated polling and background loads must retain DOM, focus and height.
        for (let i = 0; i < 5; i++) {
          state.updated_at = String(i + 2);
          updateReportAgentMap(map, {}, []);
          renderReportAgentInspector(map);
          const pending = loadReportAgentSnapshot(map);
          if (panel.querySelector('.report-inspector-loading')) throw Error('Background load changed layout');
          finishSnapshot({ results: {} });
          await pending;
        }
        const stable = panel === map.querySelector('.report-agent-inspector')
          && canvas === map.querySelector('.report-console-canvas')
          && card === map.querySelector('[data-agent-key="job_analysis"]')
          && tab === document.activeElement
          && panel.getBoundingClientRect().height === height;
        state.agent_activity = { job_analysis: { status: 'done', message: 'Analysis complete' } };
        updateReportAgentMap(map, {}, []);
        renderReportAgentInspector(map);
        const updated = card.classList.contains('is-done') && panel.textContent.includes('已完成');
        reportAgentConsoleState.tab = 'output';
        renderReportAgentInspector(map);
        const switched = panel.querySelector('[data-agent-tab="output"]').getAttribute('aria-selected') === 'true';
        reportAgentConsoleState.collapsed = true;
        renderReportAgentInspector(map);
        const collapsed = panel.hidden;
        state.report_id = 'new-report';
        updateReportAgentMap(map, {}, []);
        const reset = reportAgentConsoleState.selected === '' && panel !== map.querySelector('.report-agent-inspector');
        return { stable, updated, switched, collapsed, reset };
      };
    ` });
    const result = await page.evaluate(() => window.testConsole());
    assert.deepEqual(result, { stable: true, updated: true, switched: true, collapsed: true, reset: true });
    console.log("PASS: repeated polls retain panel, canvas, card, focus and height; status, tabs, collapse and new reports still update.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
