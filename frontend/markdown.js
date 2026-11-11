/**
 * PETIT Markdown Renderer
 * 軽量・依存ゼロで安全なMarkdownレンダラー
 * XSSサニタイズ、ストリーミング耐性、コードコピー対応
 */
(function (global) {
  "use strict";

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function sanitizeUrl(url) {
    if (!url) return null;
    var trimmed = String(url).trim();
    // http://, https://, 相対パス (/), ハッシュ (#), mailto: のみ許可
    if (/^(?:https?:\/\/|\/|#|mailto:)/i.test(trimmed)) {
      return trimmed;
    }
    return null;
  }

  var PLACEHOLDER_CODE = "\uE000PETITCODE";
  var PLACEHOLDER_INLINE = "\uE000PETITINLINE";
  var PLACEHOLDER_TABLE = "\uE000PETITTABLE";
  var PLACEHOLDER_END = "\uE001";

  function render(text) {
    if (text === null || text === undefined || text === "") {
      return "";
    }

    var src = String(text);

    // 1. フェンスコードブロックを退避
    var codeBlocks = [];
    // ```lang\ncode``` または未完了の ```lang\ncode (ストリーミング対応)
    src = src.replace(/(?:^|\n)```([a-zA-Z0-9_+#.-]*)[ \t]*\r?\n([\s\S]*?)(?:\r?\n```[ \t]*(?:\r?\n|$)|$)/g, function (match, lang, code) {
      var id = PLACEHOLDER_CODE + codeBlocks.length + PLACEHOLDER_END;
      codeBlocks.push({
        lang: (lang || "code").trim(),
        code: escapeHtml(code.replace(/\r?\n$/, ""))
      });
      return "\n\n" + id + "\n\n";
    });

    // 2. 本文全体を安全にエスケープ（HTMLタグは無害化）
    src = escapeHtml(src);

    // 3. インラインコードの退避
    var inlineCodes = [];
    src = src.replace(/`([^`\r\n]+)`/g, function (match, code) {
      var id = PLACEHOLDER_INLINE + inlineCodes.length + PLACEHOLDER_END;
      inlineCodes.push(code); // escapeHtml済み
      return id;
    });

    // 4. GFMテーブルの退避
    var tables = [];
    src = src.replace(/(?:(?:^|\n)\|[^\r\n]+\|[ \t]*(?:\r?\n\|[ \t]*:?[-]+:?[ \t]*\|[^\r\n]*)+(?:\r?\n\|[^\r\n]+\|[ \t]*)*)/g, function (match) {
      var lines = match.trim().split(/\r?\n/).map(function (l) { return l.trim(); }).filter(Boolean);
      if (lines.length < 2) return match;

      var headerLine = lines[0];
      var alignLine = lines[1];
      var rowLines = lines.slice(2);

      // 区切り行の検証
      if (!/^\|(?:[ \t]*:?[-]{2,}:?[ \t]*\|)+$/.test(alignLine)) {
        return match;
      }

      function parseCells(line) {
        var raw = line.replace(/^\|/, "").replace(/\|$/, "");
        return raw.split("|").map(function (c) { return c.trim(); });
      }

      var headerCells = parseCells(headerLine);
      var alignCells = parseCells(alignLine).map(function (a) {
        var hasLeft = a.startsWith(":");
        var hasRight = a.endsWith(":");
        if (hasLeft && hasRight) return "center";
        if (hasRight) return "right";
        if (hasLeft) return "left";
        return "";
      });

      var ths = headerCells.map(function (cell, idx) {
        var align = alignCells[idx] ? ' class="petit-md-align-' + alignCells[idx] + '"' : '';
        return "<th" + align + ">" + renderInline(cell) + "</th>";
      }).join("");

      var trs = rowLines.map(function (line) {
        var cells = parseCells(line);
        var tds = cells.map(function (cell, idx) {
          var align = alignCells[idx] ? ' class="petit-md-align-' + alignCells[idx] + '"' : '';
          return "<td" + align + ">" + renderInline(cell) + "</td>";
        }).join("");
        return "<tr>" + tds + "</tr>";
      }).join("");

      var html = '<div class="petit-md-table-wrap"><table class="petit-md-table">' +
        "<thead><tr>" + ths + "</tr></thead>" +
        (trs ? "<tbody>" + trs + "</tbody>" : "") +
        "</table></div>";

      var id = PLACEHOLDER_TABLE + tables.length + PLACEHOLDER_END;
      tables.push(html);
      return "\n\n" + id + "\n\n";
    });

    // 5. ブロック要素のパース
    var lines = src.split(/\r?\n/);
    var out = [];
    var inList = null; // { type: 'ul'|'ol', level: 0 }
    var inQuote = false;
    var quoteBuffer = [];

    function flushQuote() {
      if (inQuote) {
        out.push('<blockquote class="petit-md-quote">' + renderInline(quoteBuffer.join("<br>")) + "</blockquote>");
        quoteBuffer = [];
        inQuote = false;
      }
    }

    function flushList() {
      if (inList) {
        out.push("</" + inList.type + ">");
        inList = null;
      }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var trimmed = line.trim();

      // 水平線: ---, ***, ___ (3つ以上)
      if (/^(?:---|\*\*\*|___)\s*$/.test(trimmed)) {
        flushQuote();
        flushList();
        out.push('<hr class="petit-md-hr">');
        continue;
      }

      // 見出し: # 〜 ######
      var headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
      if (headingMatch) {
        flushQuote();
        flushList();
        var level = headingMatch[1].length;
        // チャット吹き出しに合わせて h3〜h6 にマッピング
        var tagLevel = Math.min(level + 2, 6);
        var tag = "h" + tagLevel;
        var hClass = "petit-md-h petit-md-h" + level;
        out.push("<" + tag + ' class="' + hClass + '">' + renderInline(headingMatch[2]) + "</" + tag + ">");
        continue;
      }

      // 引用: &gt; (エスケープ前は >)
      var quoteMatch = line.match(/^(?:&gt;|>)[ \t]?(.*)$/);
      if (quoteMatch) {
        flushList();
        inQuote = true;
        quoteBuffer.push(quoteMatch[1]);
        continue;
      } else {
        flushQuote();
      }

      // チェックボックス付きリスト: - [ ] または - [x]
      var taskListMatch = line.match(/^(\s*)(?:[-*+]|&bull;)[ \t]+\[([ xX])\][ \t]+(.+)$/);
      if (taskListMatch) {
        if (!inList || inList.type !== "ul") {
          flushList();
          out.push('<ul class="petit-md-list petit-md-task-list">');
          inList = { type: "ul" };
        }
        var checked = taskListMatch[2].toLowerCase() === "x" ? " checked" : "";
        var checkHtml = '<input type="checkbox" class="petit-md-task-checkbox" disabled' + checked + '> ';
        out.push('<li class="petit-md-task-item">' + checkHtml + renderInline(taskListMatch[3]) + "</li>");
        continue;
      }

      // 箇条書きリスト: - item, * item, + item
      var ulMatch = line.match(/^(\s*)(?:[-*+]|&bull;)[ \t]+(.+)$/);
      if (ulMatch) {
        if (!inList || inList.type !== "ul") {
          flushList();
          out.push('<ul class="petit-md-list">');
          inList = { type: "ul" };
        }
        out.push("<li>" + renderInline(ulMatch[2]) + "</li>");
        continue;
      }

      // 番号付きリスト: 1. item
      var olMatch = line.match(/^(\s*)\d+\.[ \t]+(.+)$/);
      if (olMatch) {
        if (!inList || inList.type !== "ol") {
          flushList();
          out.push('<ol class="petit-md-list petit-md-ol">');
          inList = { type: "ol" };
        }
        out.push("<li>" + renderInline(olMatch[2]) + "</li>");
        continue;
      }

      // リスト終了判定
      if (inList && trimmed === "") {
        flushList();
        continue;
      }

      // プレースホルダー（コードブロックやテーブル）
      if (/^\uE000PETIT(?:CODE|TABLE)\d+\uE001$/.test(trimmed)) {
        flushQuote();
        flushList();
        out.push(trimmed);
        continue;
      }

      // 通常テキストまたは空行
      if (trimmed === "") {
        out.push("");
      } else {
        out.push(renderInline(line));
      }
    }

    flushQuote();
    flushList();

    // 6. 段落と改行の整形
    var finalParts = [];
    var currentParagraph = [];

    function flushParagraph() {
      if (currentParagraph.length > 0) {
        var text = currentParagraph.join("<br>");
        if (text.trim()) {
          finalParts.push('<p class="petit-md-p">' + text + "</p>");
        }
        currentParagraph = [];
      }
    }

    for (var j = 0; j < out.length; j++) {
      var item = out[j];
      if (/^<(?:h[3-6]|blockquote|ul|ol|hr|div)[ >]/.test(item) || /^<\/(?:ul|ol)>$/.test(item) || /^\uE000PETIT/.test(item)) {
        flushParagraph();
        finalParts.push(item);
      } else if (item === "") {
        flushParagraph();
      } else {
        currentParagraph.push(item);
      }
    }
    flushParagraph();

    var result = finalParts.join("\n");

    // 7. インラインコードの復元
    result = result.replace(/\uE000PETITINLINE(\d+)\uE001/g, function (match, index) {
      var code = inlineCodes[Number(index)] || "";
      return '<code class="petit-md-inline-code">' + code + "</code>";
    });

    // 8. テーブルの復元
    result = result.replace(/\uE000PETITTABLE(\d+)\uE001/g, function (match, index) {
      return tables[Number(index)] || "";
    });

    // 9. コードブロックの復元
    result = result.replace(/\uE000PETITCODE(\d+)\uE001/g, function (match, index) {
      var block = codeBlocks[Number(index)];
      if (!block) return "";
      var langLabel = block.lang || "code";
      return '<div class="petit-md-code-block">' +
        '<div class="petit-md-code-header">' +
          '<span class="petit-md-code-lang">' + escapeHtml(langLabel) + '</span>' +
          '<button type="button" class="petit-md-code-copy" data-action="copy-code" title="コードをコピー">コピー</button>' +
        '</div>' +
        '<pre class="petit-md-pre"><code class="petit-md-code language-' + escapeHtml(langLabel) + '">' + block.code + '</code></pre>' +
      '</div>';
    });

    return result;
  }

  // インライン修飾（太字、斜体、取り消し線、リンク）
  function renderInline(str) {
    if (!str) return "";
    var s = str;

    // リンク [text](url)
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (match, label, href) {
      var safeHref = sanitizeUrl(href);
      if (safeHref) {
        return '<a href="' + escapeHtml(safeHref) + '" target="_blank" rel="noopener noreferrer" class="petit-md-link">' + label + '</a>';
      }
      return label + " (" + href + ")";
    });

    // 太字 + 斜体: ***text*** または ___text___
    s = s.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    s = s.replace(/___(.+?)___/g, "<strong><em>$1</em></strong>");

    // 太字: **text** または __text__
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");

    // 斜体: *text* または _text_
    s = s.replace(/\*([^*\r\n]+)\*/g, "<em>$1</em>");
    s = s.replace(/_([^_\r\n]+)_/g, "<em>$1</em>");

    // 取り消し線: ~~text~~
    s = s.replace(/~~(.+?)~~/g, "<del>$1</del>");

    return s;
  }

  // コピーボタンのグローバルイベント設定（1回だけ登録）
  if (typeof document !== "undefined") {
    var listenerAttached = false;
    var initCopyListener = function () {
      if (listenerAttached) return;
      listenerAttached = true;
      document.addEventListener("click", function (event) {
        var target = event.target;
        if (!target || typeof target.closest !== "function") return;
        var button = target.closest(".petit-md-code-copy");
        if (!button) return;

        var block = button.closest(".petit-md-code-block");
        if (!block) return;
        var codeEl = block.querySelector("code");
        if (!codeEl) return;

        var codeText = codeEl.textContent || "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(codeText).then(function () {
            var origText = button.textContent;
            button.textContent = "コピー完了！";
            button.classList.add("is-copied");
            setTimeout(function () {
              button.textContent = origText;
              button.classList.remove("is-copied");
            }, 1800);
          }).catch(function () {
            button.textContent = "失敗";
          });
        }
      });
    };

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initCopyListener);
    } else {
      initCopyListener();
    }
  }

  var PetitMarkdown = {
    render: render,
    escapeHtml: escapeHtml,
    sanitizeUrl: sanitizeUrl,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = PetitMarkdown;
  }
  if (typeof global !== "undefined") {
    global.PetitMarkdown = PetitMarkdown;
  }
})(typeof window !== "undefined" ? window : globalThis);
