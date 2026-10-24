// Real Chromium / real HTTP / temporary DB / synthetic provider; no real account.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const port = 8876;
const url = 'http://127.0.0.1:' + port;
const child = spawn(process.env.PETIT_TEST_PYTHON || 'python',
  ['-m', 'uvicorn', 'tests.renaissance_ui_server:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'error'],
  { cwd: require('node:path').join(__dirname, '..'), stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
let logs = '';
child.stderr.on('data', data => { logs += data; });
async function main() {
  let ready = false;
  for (let attempt = 0; attempt < 70; attempt++) {
    try { ready = (await fetch(url + '/api/threads')).ok; } catch {}
    if (ready) break;
    if (child.exitCode !== null) throw Error('fixture exited: ' + logs.slice(-1000));
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  assert(ready, 'fixture server unavailable');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      page.on('pageerror', error => console.log('PAGE ERROR: ' + error.message));
      // Rendering the chat must not depend on CDN availability.
      await page.route('https://**/*', route => route.abort());
      await page.goto(url + '/static/universe.html?thread=browser-' + width);
      await page.waitForFunction(() => window.PetitAppShell?.activateView);
      await page.evaluate(() => window.PetitAppShell.activateView('chat'));
      await page.waitForTimeout(500);
      if (!(await page.locator('.petit-thread-controls').isVisible())) {
        console.log(await page.locator('[data-view-panel="chat"]').evaluate(node => ({
          hidden: node.hidden, className: node.className, body: document.body.dataset,
          style: getComputedStyle(node).display })));
        throw Error('chat panel did not become visible');
      }
      await page.locator('#chat-input').fill('取り掛かろう');
      await page.locator('#chat-form').evaluate(form => form.requestSubmit());
      await page.getByText('実行結果を確認しました。', { exact: true }).last().waitFor();
      const snapshot = await (await fetch(url + '/api/threads/browser-' + width + '/snapshot')).json();
      assert.equal(snapshot.conversations.length, 1);
      const turnId = snapshot.events.find(event => event.type === 'accepted').request_id;
      const turn = await (await fetch(url + '/api/turns/' + turnId)).json();
      assert.equal(turn.effects[0].status, 'applied');
      await page.locator('#chat-form [type="submit"]:enabled').waitFor();
      await page.locator('#chat-input').fill('予定を追加');
      await page.locator('#chat-form').evaluate(form => form.requestSubmit());
      await page.locator('#chat-form [type="submit"]:enabled').waitFor();
      await page.getByRole('button', { name: /承認|実行する|確認して実行/ }).first().waitFor();
      await page.reload();
      await page.waitForFunction(() => window.PetitAppShell?.activateView);
      await page.evaluate(() => window.PetitAppShell.activateView('chat'));
      await page.getByRole('button', { name: /承認|実行する|確認して実行/ }).first().waitFor();
      await page.getByRole('button', { name: /承認|実行する|確認して実行/ }).first().click();
      await page.getByText('実行結果を確認しました。', { exact: true }).last().waitFor();
      const second = await browser.newContext({ viewport: { width, height: 900 } });
      const secondPage = await second.newPage();
      await secondPage.route('https://**/*', route => route.abort());
      await secondPage.goto(url + '/static/universe.html?thread=browser-' + width);
      await secondPage.waitForFunction(() => window.PetitAppShell?.activateView);
      await secondPage.evaluate(() => window.PetitAppShell.activateView('chat'));
      await secondPage.getByText('取り掛かろう', { exact: true }).waitFor();
      assert.equal(await secondPage.locator('.petit-thread-controls').count(), 1);
      await second.close();
      await context.close();
      console.log('PASS Chromium width=' + width + ': Tool effect, approval restore, explicit same-thread history');
    }
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(() => child.kill());
