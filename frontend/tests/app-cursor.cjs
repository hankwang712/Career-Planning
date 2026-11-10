const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  try {
    const css = fs.readFileSync(path.join(__dirname,"../static/app-cursor.css"),"utf8");
    const script = fs.readFileSync(path.join(__dirname,"../static/app-cursor.js"),"utf8");
    const page = await browser.newPage({ viewport:{width:800,height:600} });
    await page.setContent('<style>body{margin:0;min-height:100vh}input,button{margin:30px}</style><input aria-label="Text"><button disabled><span>Disabled</span></button><dialog><p>Modal content</p><button>Continue</button></dialog>');
    await page.addStyleTag({content:css});
    await page.addScriptTag({content:script});
    for (const [x,y] of [[400,599],[799,599],[0,0],[799,20]]) {
      await page.mouse.move(x,y);
      const result = await page.evaluate(() => {
        const cursor = document.querySelector('.app-cursor-overlay');
        const rect = cursor.getBoundingClientRect();
        return { visible:getComputedStyle(cursor).visibility, native:getComputedStyle(document.body).cursor, x:rect.x,y:rect.y, hit:document.elementFromPoint(400,599)?.className };
      });
      assert.equal(result.visible,'visible');
      assert.equal(result.native,'none');
      assert.equal(result.x,x-6);
      assert.equal(result.y,y-3);
      assert.notEqual(result.hit,'app-cursor-overlay');
    }
    await page.locator('input').hover();
    assert.equal(await page.locator('input').evaluate(node => getComputedStyle(node).cursor),'text');
    assert.equal(await page.locator('.app-cursor-overlay').evaluate(node => getComputedStyle(node).visibility),'hidden');
    await page.locator('button:disabled span').hover();
    assert.equal(await page.locator('button:disabled span').evaluate(node => getComputedStyle(node).cursor),'not-allowed');
    await page.evaluate(() => document.querySelector('dialog').showModal());
    await page.locator('dialog p').hover();
    assert.equal(await page.locator('.app-cursor-overlay').evaluate(node => node.matches(':popover-open') && getComputedStyle(node).visibility === 'visible'),true);
    await page.locator('dialog button').click();
    await page.evaluate(() => window.dispatchEvent(new Event('blur')));
    assert.equal(await page.locator('.app-cursor-overlay').evaluate(node => getComputedStyle(node).visibility),'hidden');
    const touch = await browser.newPage({ viewport:{width:390,height:844},isMobile:true,hasTouch:true });
    await touch.setContent('<p>Touch page</p>');
    await touch.addStyleTag({content:css});
    await touch.addScriptTag({content:script});
    assert.equal(await touch.locator('.app-cursor-overlay').count(),0);
    console.log('PASS: glove remains at all viewport edges; text, disabled controls, modal interaction, blur and touch behavior are preserved.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
