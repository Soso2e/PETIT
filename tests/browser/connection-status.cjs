// Run: node tests/browser/connection-status.cjs (uses the Desktop Playwright install).
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../../desktop/node_modules/playwright');
const root = path.resolve(__dirname, '../../frontend');
const output = process.env.PETIT_QA_OUTPUT || path.join(require('node:os').tmpdir(), 'petit-connection-status-qa');
fs.mkdirSync(output, { recursive: true });
const serviceNames = ['LM Studio', 'Notion', 'Google Calendar (ICS)', 'GitHub', 'Linkraft', 'AivisSpeech', 'BRAIN'];
const ids = ['lmstudio', 'notion', 'calendar', 'github', 'linkraft', 'aivis', 'brain'];
const services = serviceNames.map((name, index) => ({ id: ids[index], name, connection_status: index === 4 ? 'unconfigured' : 'unverified',
  sync_status: index === 1 ? 'error' : index === 4 ? 'unconfigured' : index === 2 ? 'stale' : null,
  failed_count: index === 1 ? 1 : 0, conflict_count: index === 1 ? 1 : 0,
  error: index === 1 ? 'Notion API HTTP 403。連携への共有を確認してください。' : null,
  can_check: index !== 4, operations: index === 1 ? [
    { id: 1, task_id: 11, title: '音声機能修正 <img src=x onerror=alert(1)>', operation: 'update', status: 'failed', attempts: 3, max_attempts: 5, last_error: 'Notion API 403 Forbidden', error_code: '403', last_attempt_at: '2026-10-13T01:00:00Z', next_attempt_at: '2026-10-13T02:00:00Z' },
    { id: 2, task_id: 12, title: '親子関係修正', operation: 'update', status: 'conflict', attempts: 1, max_attempts: 5, last_error: 'Notion側にも更新があります。' }
  ] : [] }));
const calls = [];
let failSnapshot = false;
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://fixture');
  if (url.pathname.startsWith('/api/')) {
    calls.push([req.method, url.pathname]);
    res.setHeader('Content-Type', 'application/json');
    if (url.pathname === '/api/connections') {
      if (failSnapshot) { res.writeHead(503); res.end('{}'); return; }
      res.end(JSON.stringify({ services, generated_at: '2026-10-13T03:00:00Z' })); return;
    }
    if (url.pathname.endsWith('/check')) { res.end(JSON.stringify(services[0])); return; }
    if (url.pathname.endsWith('/retry')) {
      services[1].operations[0].status = 'pending'; services[1].operations[0].attempts = 0;
      res.end('{"queued":true}'); return;
    }
    if (url.pathname.endsWith('/conflict')) {
      res.end(JSON.stringify(req.method === 'POST' ? { message: '選択を反映しました。' } : {
        local: { title: '親子関係修正', status: 'Yet' }, remote: { title: '親子関係修正', status: 'Done' }, revision: 'revision1'
      })); return;
    }
    res.end('{}'); return;
  }
  if (url.pathname === '/') {
    res.setHeader('Content-Type', 'text/html');
    res.end(`<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>接続診断fixture</title>
      <link rel="stylesheet" href="/universe.css"><link rel="stylesheet" href="/petit-ui-system.css"><link rel="stylesheet" href="/connection-status.css">
      <body><button id="sync-pill">同期失敗あり</button><button data-open-connections>接続ステータスを開く</button><button id="refresh-universe">更新</button>
      <script src="/task-sync-recovery.js"></script><script src="/connection-status.js"></script></body></html>`); return;
  }
  if (url.pathname === '/full') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end(fs.readFileSync(path.join(root, 'universe.html'))); return;
  }
  if (url.pathname === '/service-worker.js') { res.writeHead(404); res.end(); return; }
  const file = path.join(root, url.pathname.replace(/^\/static\//, '/').slice(1));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : 'application/javascript');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PETIT_TEST_BROWSER_PATH || undefined });
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => console.error('Browser error:', error.message));
    await page.route('https://**', route => route.abort());
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      const before = calls.length;
      await page.locator('#sync-pill').click();
      await page.locator('.connection-service').last().waitFor();
      assert.equal(await page.locator('.connection-service').count(), 7);
      assert.deepEqual(calls.slice(before), [['GET', '/api/connections']]);
      await page.locator('[data-service="notion"] summary').click();
      await page.locator('text=Notion API 403 Forbidden').waitFor();
      assert.equal(await page.locator('.connection-dialog img').count(), 0);
      assert.match(await page.locator('[data-service="notion"]').innerText(), /3\/5回/);
      const dimensions = await page.locator('.connection-dialog').evaluate(el => ({ client: el.clientWidth, scroll: el.scrollWidth, right: el.getBoundingClientRect().right }));
      assert.ok(dimensions.scroll <= dimensions.client + 1, `horizontal overflow at ${width}`);
      assert.ok(dimensions.right <= width, `offscreen dialog at ${width}`);
      await page.screenshot({ path: path.join(output, `${width}.png`) });
      await page.locator('.connection-dialog').press('Escape');
      assert.equal(await page.locator('#sync-pill').evaluate(el => el === document.activeElement), true);
      await page.locator('[data-open-connections]').click();
      await page.locator('.connection-service').last().waitFor();
      await page.locator('.connection-dialog').press('Escape');
    }
    await page.locator('[data-open-connections]').click();
    await page.locator('[data-service="notion"] summary').click();
    await page.getByRole('button', { name: 'このタスクを再試行' }).click();
    await page.getByRole('status').filter({ hasText: '再試行キュー' }).waitFor();
    assert.equal(calls.filter(([method, url]) => method === 'POST' && url.endsWith('/retry')).length, 1);
    await page.getByRole('button', { name: '競合を比較して解消' }).click();
    await page.getByRole('button', { name: 'PETIT側を残して再同期' }).waitFor();
    assert.equal(await page.locator('.connection-dialog').count(), 0);
    assert.equal(await page.locator('.task-conflict-dialog').count(), 1);
    await page.getByRole('button', { name: 'PETIT側を残して再同期' }).click();
    await page.getByRole('status').filter({ hasText: '選択を反映' }).waitFor();
    await page.locator('.task-conflict-dialog').press('Escape');
    await page.locator('#sync-pill').click();
    await page.locator('[data-service="lmstudio"] summary').click();
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/lmstudio/check')),
      page.locator('[data-service="lmstudio"]').getByRole('button', { name: '接続確認', exact: true }).click()
    ]);
    assert.equal(calls.filter(([method, url]) => method === 'POST' && url.endsWith('/check')).length, 1);
    failSnapshot = true;
    await page.getByRole('button', { name: '保存済み状態を更新' }).click();
    await page.getByRole('status').filter({ hasText: 'HTTP 503' }).waitFor();
    assert.equal(await page.locator('.connection-service').count(), 7);
    await page.screenshot({ path: path.join(output, 'mobile.png') });
    failSnapshot = false;
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`http://127.0.0.1:${server.address().port}/full?renderer=css`);
    await page.waitForFunction(() => window.PetitConnections && window.PetitAppShell?.activateView);
    await page.locator('[data-shell-target="settings"]').click();
    await page.locator('[data-open-connections]').click();
    await page.locator('.connection-service').last().waitFor();
    assert.equal(await page.locator('.connection-service').count(), 7);
    await page.locator('[data-service="notion"] summary').click();
    await page.waitForTimeout(250); // Wait for the existing dialog entry animation before visual QA.
    await page.screenshot({ path: path.join(output, 'full-desktop.png') });
    await page.locator('.connection-dialog').press('Escape');
    await page.locator('[data-rail-sync]').press('Enter');
    await page.locator('.connection-service').last().waitFor();
    console.log('PASS: 1440/390/320px, both entry points, read-only opening, XSS-safe details, single retry, existing conflict resolution, explicit check, partial outage, Escape/focus.');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
