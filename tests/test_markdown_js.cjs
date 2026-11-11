const assert = require("node:assert/strict");
const test = require("node:test");
const PetitMarkdown = require("../frontend/markdown.js");

test("Markdown: basic text and paragraphs", () => {
  const input = "こんにちは。\nPETITです。";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes("<p class=\"petit-md-p\">"));
  assert.ok(output.includes("こんにちは。<br>PETITです。"));
});

test("Markdown: headings from h1 to h4", () => {
  const input = "# タイトル1\n## タイトル2\n### タイトル3\n#### タイトル4";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('<h3 class="petit-md-h petit-md-h1">タイトル1</h3>'));
  assert.ok(output.includes('<h4 class="petit-md-h petit-md-h2">タイトル2</h4>'));
  assert.ok(output.includes('<h5 class="petit-md-h petit-md-h3">タイトル3</h5>'));
  assert.ok(output.includes('<h6 class="petit-md-h petit-md-h4">タイトル4</h6>'));
});

test("Markdown: bold, italic, and strikethrough", () => {
  const input = "**太字** と *斜体* と ~~取り消し~~ と ***太字斜体***";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes("<strong>太字</strong>"));
  assert.ok(output.includes("<em>斜体</em>"));
  assert.ok(output.includes("<del>取り消し</del>"));
  assert.ok(output.includes("<strong><em>太字斜体</em></strong>"));
});

test("Markdown: inline code", () => {
  const input = "設定ファイルは `config.json` です。";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('<code class="petit-md-inline-code">config.json</code>'));
});

test("Markdown: fenced code blocks with language", () => {
  const input = "```python\ndef hello():\n    print('world')\n```";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('class="petit-md-code-block"'));
  assert.ok(output.includes('class="petit-md-code-lang">python</span>'));
  assert.ok(output.includes("def hello():\n    print(&#39;world&#39;)"));
  assert.ok(output.includes('data-action="copy-code"'));
});

test("Markdown: streaming unclosed code block", () => {
  const input = "```javascript\nconst a = 1;";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('class="petit-md-code-block"'));
  assert.ok(output.includes("const a = 1;"));
});

test("Markdown: lists (unordered and ordered)", () => {
  const input = "- リンゴ\n- バナナ\n- オレンジ\n\n1. 最初\n2. 次";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('<ul class="petit-md-list">'));
  assert.ok(output.includes("<li>リンゴ</li>"));
  assert.ok(output.includes('<ol class="petit-md-list petit-md-ol">'));
  assert.ok(output.includes("<li>最初</li>"));
});

test("Markdown: task checkboxes", () => {
  const input = "- [ ] 未完了タスク\n- [x] 完了タスク";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('class="petit-md-task-checkbox" disabled> 未完了タスク'));
  assert.ok(output.includes('class="petit-md-task-checkbox" disabled checked> 完了タスク'));
});

test("Markdown: blockquote", () => {
  const input = "> これは引用です。\n> 二行目の引用。";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('<blockquote class="petit-md-quote">これは引用です。<br>二行目の引用。</blockquote>'));
});

test("Markdown: horizontal rule", () => {
  const input = "前\n---\n後";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('<hr class="petit-md-hr">'));
});

test("Markdown: table rendering", () => {
  const input = "| 項目 | 値 |\n| --- | --- |\n| A | 100 |\n| B | 200 |";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes('<table class="petit-md-table">'));
  assert.ok(output.includes("<th>項目</th>"));
  assert.ok(output.includes("<td>100</td>"));
});

test("Markdown: XSS sanitization prevents script injection", () => {
  const malicious = '<script>alert("xss")</script><img src="x" onerror="evil()"><iframe src="x"></iframe>';
  const output = PetitMarkdown.render(malicious);
  assert.ok(!output.includes("<script>"));
  assert.ok(output.includes("&lt;script&gt;"));
  assert.ok(!output.includes("<img"));
  assert.ok(output.includes("&lt;img"));
  assert.ok(!output.includes("<iframe"));
});

test("Markdown: XSS in links prevents javascript: URI", () => {
  const maliciousLink = '[クリック](javascript:alert(1)) [正常リンク](https://example.com)';
  const output = PetitMarkdown.render(maliciousLink);
  assert.ok(!output.includes('href="javascript:'));
  assert.ok(output.includes('href="https://example.com"'));
  assert.ok(output.includes('target="_blank" rel="noopener noreferrer"'));
});

test("Markdown: multiple code blocks preserve content and markdown characters inside", () => {
  const input = "最初のコード:\n```python\n# コメント\nprint('hello')\n```\n次のコード:\n```javascript\n// comment\nconst x = [1, 2, 3];\n```";
  const output = PetitMarkdown.render(input);
  assert.ok(output.includes("print(&#39;hello&#39;)"));
  assert.ok(output.includes("# コメント")); // コードブロック内の # が h3 に化けないこと
  assert.ok(!output.includes('<h3 class="petit-md-h petit-md-h1">コメント</h3>'));
  assert.ok(output.includes("const x = [1, 2, 3];"));
});

test("Markdown: empty and falsy input returns empty string", () => {
  assert.equal(PetitMarkdown.render(""), "");
  assert.equal(PetitMarkdown.render(null), "");
  assert.equal(PetitMarkdown.render(undefined), "");
});

test("Markdown: frontend assets include markdown.css and markdown.js in html files", () => {
  const fs = require("node:fs");
  const path = require("node:path");

  const universeHtml = fs.readFileSync(path.join(__dirname, "..", "frontend", "universe.html"), "utf8");
  assert.ok(universeHtml.includes("/static/markdown.css"), "universe.html must include markdown.css");
  assert.ok(universeHtml.includes("/static/markdown.js"), "universe.html must include markdown.js");

  const desktopHtml = fs.readFileSync(path.join(__dirname, "..", "frontend", "desktop", "index.html"), "utf8");
  assert.ok(desktopHtml.includes("/static/markdown.css"), "desktop/index.html must include markdown.css");
  assert.ok(desktopHtml.includes("/static/markdown.js"), "desktop/index.html must include markdown.js");

  const legacyHtml = fs.readFileSync(path.join(__dirname, "..", "frontend", "legacy.html"), "utf8");
  assert.ok(legacyHtml.includes("/static/markdown.css"), "legacy.html must include markdown.css");
  assert.ok(legacyHtml.includes("/static/markdown.js"), "legacy.html must include markdown.js");
});

test("Markdown: universe-app.js and app.js use PetitMarkdown for assistant messages", () => {
  const fs = require("node:fs");
  const path = require("node:path");

  const universeAppJs = fs.readFileSync(path.join(__dirname, "..", "frontend", "universe-app.js"), "utf8");
  assert.ok(universeAppJs.includes("window.PetitMarkdown.render"), "universe-app.js must render markdown for assistant");
  assert.ok(universeAppJs.includes("petit-markdown"), "universe-app.js must add petit-markdown class");

  const appJs = fs.readFileSync(path.join(__dirname, "..", "frontend", "app.js"), "utf8");
  assert.ok(appJs.includes("window.PetitMarkdown.render"), "app.js must render markdown for assistant");
  assert.ok(appJs.includes("petit-markdown"), "app.js must add petit-markdown class");
});
