// Run against tests.vision_ui_server, never a production Core.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('../desktop/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PETIT_TEST_BROWSER_CHANNEL || 'chrome' });
  const output = path.resolve('storage/vision-ui');
  fs.mkdirSync(output, { recursive: true });
  try {
    for (const surface of ['universe', 'desktop/index', 'legacy']) {
      for (const width of [390, 1440]) {
        const page = await browser.newPage({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
        const cspErrors = [];
        page.on('console', (message) => { if (message.text().includes('Content Security Policy')) cspErrors.push(message.text()); });
        await page.route('**/api/**', async (route) => {
          const pathname = new URL(route.request().url()).pathname;
          if (pathname.startsWith('/api/attachments') || pathname === '/api/chat') return route.continue();
          let data = {};
          if (pathname === '/api/health') data = { chat_model: { server_ok: true, label: 'Fixture' }, agent_model: { server_ok: true, label: 'Fixture' } };
          if (pathname.startsWith('/api/conversations')) data = { conversations: [] };
          if (pathname === '/api/universe') data = { tasks: [], projects: [], planets: [] };
          return route.fulfill({ json: data });
        });
        await page.goto(`http://127.0.0.1:18763/static/${surface}.html?view=chat`);
        if (surface === 'universe') await page.locator('[data-view-panel="chat"]').waitFor({ state: 'visible' });
        if (surface === 'legacy') {
          const tab = page.locator('[data-app-nav="chat"]');
          if (await tab.count()) await tab.click();
        }
        const picker = page.locator('.chat-attachments input');
        await picker.waitFor({ state: 'attached' });
        // Hidden legacy panels can be selected by their existing nav. Fixture-only fallback.
        if (!(await page.locator('.chat-attachments').isVisible())) await page.evaluate(() => {
          const panel = document.querySelector('#chat-form').closest('[hidden]');
          if (panel) panel.hidden = false;
          document.querySelector('#chat-form').closest('.app-view')?.classList.add('is-active');
        });
        await picker.setInputFiles(path.resolve('tests/fixtures/vision/steam-statistics.png'));
        await page.getByText('画像を添付しました。送信すると解析します。', { exact: true }).waitFor({ timeout: 10000 }).catch(async (error) => {
          console.error(surface, await page.locator('.chat-attachments').textContent());
          throw error;
        });
        assert.equal(await page.locator('.chat-attachments img').evaluate((img) => img.naturalWidth > 0), true);
        const input = page.locator('#input, #chat-input').first();
        await input.fill('simulate-failure');
        const failed = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/chat');
        await page.locator('#chat-form [type="submit"]').click();
        assert.equal((await (await failed).json()).error, 'テスト用の画像解析エラー');
        await page.locator('#chat-form [type="submit"]:enabled').waitFor();
        assert.equal(await page.locator('.chat-attachments img').count(), 1, 'failure preserves selected image');
        await input.fill('');
        const success = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/chat');
        await page.locator('#chat-form [type="submit"]').click();
        const result = await (await success).json();
        assert.equal(result.error, null);
        assert.match(result.reply, /UIテスト画像/);
        await page.locator('#chat-form [type="submit"]:enabled').waitFor();
        assert.equal(await page.locator('.chat-attachments img').count(), 0);
        await picker.setInputFiles(path.resolve('tests/fixtures/vision/steam-statistics.png'));
        await page.getByText('画像を添付しました。送信すると解析します。', { exact: true }).waitFor();
        await page.locator('.chat-attachments button[aria-label$="を削除"]').click();
        await page.waitForFunction(() => window.PetitChatAttachments.ids().length === 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        const screenshot = `${surface.replace('/', '-')}-${width}.png`;
        await page.screenshot({ path: path.join(output, screenshot) });
        assert.deepEqual(cspErrors.filter((error) => error.includes('blob:')), []);
        console.log(`PASS ${surface} ${width}: image-only, failure/retry, preview, deletion, no horizontal overflow`);
        await page.close();
      }
    }
  } finally { await browser.close(); }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
