// Real browser + official SDK + real LM Studio. Only synthetic data.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const port = 8877;
const url = `http://127.0.0.1:${port}`;
const child = spawn(process.env.PETIT_TEST_PYTHON || 'python',
  ['-m', 'uvicorn', 'tests.antigravity_ui_server:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'error'],
  { cwd: path.join(__dirname, '..'), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
let errors = '';
child.stderr.on('data', chunk => { errors += chunk; });
async function main() {
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    try { ready = (await fetch(url + '/api/threads')).ok; } catch {}
    if (ready) break;
    if (child.exitCode !== null) throw Error('test server exited: ' + errors.slice(-700));
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  assert(ready, 'test server unavailable');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const results = [];
  try {
    for (const [width, source] of [[1440, 'web'], [390, 'desktop']]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      if (source === 'desktop') await context.addInitScript(() => { window.petitWorkspace = { desktop: true }; });
      const page = await context.newPage();
      page.on('pageerror', error => console.error('pageerror: ' + error.message));
      await page.route('https://**/*', route => route.abort());
      await page.goto(url + '/static/universe.html?thread=sdk-browser-' + width);
      await page.waitForFunction(() => window.PetitAppShell?.activateView);
      await page.evaluate(() => window.PetitAppShell.activateView('chat'));
      await page.waitForFunction(() => window.PETIT_SESSION && window.PetitUniverse);
      await page.waitForFunction(() => window.PetitUniverse.tasks().some(task => task.title === 'sdk-browser-fixture'));
      await page.locator('#chat-form [type="submit"]:enabled').waitFor();
      await page.locator('#chat-input').fill('petit_read_toolでget_tasksを呼び、取得したタスク名だけをそのまま答えて。引数JSONは{}。');
      const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/chat'), { timeout: 100000 });
      await page.locator('#chat-form').evaluate(form => form.requestSubmit());
      const chatResult = await (await responsePromise).json();
      assert.equal(chatResult.status, 'completed', JSON.stringify(chatResult));
      try {
        await page.locator('.message--assistant').filter({ hasText: 'sdk-browser-fixture' }).last().waitFor({ timeout: 10000 });
      } catch (error) {
        await page.screenshot({ path: path.join(__dirname, '../reports/antigravity-ui-debug.png') });
        console.error(JSON.stringify(await page.evaluate(() => ({
          assistant: [...document.querySelectorAll('.message--assistant')].map(node => ({ text: node.textContent, visible: !!node.offsetParent })),
          bodyText: document.body.innerText.slice(-1400)
        }))));
        throw error;
      }
      const snapshot = await (await fetch(url + '/api/threads/sdk-browser-' + width + '/snapshot')).json();
      assert.equal(snapshot.thread.source, source);
      const requestId = snapshot.events.find(event => event.type === 'accepted').request_id;
      const result = await (await fetch(url + '/api/turns/' + requestId)).json();
      assert.equal(result.status, 'completed');
      assert.equal(result.model_route.provider, 'antigravity_sdk');
      assert.equal(result.model_route.inference_provider, 'lm_studio');
      assert(result.used_tools.some(tool => tool.name === 'get_tasks'));
      assert.equal(result.effects.length, 0);
      await page.getByText('最新の依頼', { exact: true }).click();
      await page.locator('.petit-thread-controls pre').filter({ hasText: 'antigravity_sdk' }).waitFor();
      await page.reload();
      await page.waitForFunction(() => window.PetitAppShell?.activateView);
      await page.evaluate(() => window.PetitAppShell.activateView('chat'));
      await page.locator('.message--assistant').filter({ hasText: 'sdk-browser-fixture' }).last().waitFor();
      results.push({ width, source, status: result.status, provider: result.model_route.provider,
        used_tools: result.used_tools.map(tool => tool.name), model_route: result.model_route });
      await context.close();
    }
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(__dirname, '../reports/antigravity-sdk-browser-live.json'),
    JSON.stringify({ synthetic_data_only: true, browser: 'real_chromium', sdk: 'real', inference: 'real_lm_studio',
      desktop_source_adapter_only: true, packaged_desktop_verified: false, results }, null, 2) + '\n');
  console.log('PASS real Chromium 1440/390px: SDK Read Tool, saved history, backend diagnostics; desktop source adapter only');
}
main().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(() => child.kill());
