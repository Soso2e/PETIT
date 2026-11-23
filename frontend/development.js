(() => {
  "use strict";
  const states = {
    proposed: "開始前の確認", queued: "順番待ち", running: "CLIが作業中",
    waiting_approval: "PC操作の承認待ち", ready_for_review: "レビュー待ち",
    checks_failed: "チェック失敗", cancelled: "取消済み", failed: "失敗",
    interrupted: "再起動で中断", completed: "レビュー完了",
  };
  const operations = { write: "書き込み", move: "移動", delete: "削除", command: "コマンド実行" };
  const active = new Set(["queued", "running"]);
  const noticed = new Set(["ready_for_review", "failed", "checks_failed", "interrupted"]);
  const $ = (id) => document.getElementById(id);
  const phases = {
    workspace_ready: "作業場所を準備しました",
    workspace_continued: "前回の作業場所を引き継ぎました",
    session_resumed: "CLIの前回セッションを再開します",
    session_restarted: "前回セッションを再開できず、新しいセッションで続けます",
    model_request: "CLIに応答を依頼中…",
    cli_initialized: "CLIが応答を考えています…",
    cli_responding: "CLIから応答を受信中…",
    cli_validating: "CLIの応答を確認中…",
    model_response: "CLIの応答を受け取りました",
    read_file: "ファイルを読み取りました",
    write_file: "作業場所に書き込みました",
    list_pc_dir: "PCフォルダを確認しました",
    search_pc_files: "PCファイルを検索しました",
    read_pc_file: "PCファイルを読み取りました",
    copy_pc_file_to_workspace: "作業場所へコピーしました",
    tool_result: "ツール実行が完了しました",
    resumed_after_approval: "承認された操作を実行して再開しました",
    cli_tool: "CLIがツールを実行中…",
    repository_check: "テスト・検査結果を受け取りました",
  };
  const retryPhases = {
    model_retry_timeout: "CLIが時間内に終了せず、応答を再試行中…",
    model_retry_temporarily_unavailable: "CLIの接続エラーから復旧中…",
    model_retry_invalid_cli_response: "CLIの応答形式を修正して再試行中…",
    model_retry_invalid_cli_protocol: "CLIの応答を再取得中…",
    model_retry_cli_incomplete: "CLIの応答が途中で終了したため、再試行中…",
    model_retry_cli_start_transient: "CLIの起動を再試行中…",
  };

  const progressStreams = new Map();
  function closeProgress(element) {
    progressStreams.get(element)?.close();
    progressStreams.delete(element);
  }

  if (typeof MutationObserver === "function") {
    new MutationObserver(() => {
      for (const element of progressStreams.keys()) {
        if (!element.isConnected) closeProgress(element);
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  function formatEventLine(event) {
    const label = retryPhases[event.kind] || phases[event.kind] || states[event.kind] || event.kind;
    return [event.created_at, label, event.detail].filter(Boolean).join(" · ");
  }

  // Live steps of the CLI: collapsible thinking text and one row per tool call or interim reply.
  function createTrace(host) {
    host.classList.add("development-trace");
    host.hidden = true;
    const thoughtBox = document.createElement("details");
    thoughtBox.className = "development-trace-thought";
    thoughtBox.hidden = true;
    const thoughtLabel = document.createElement("summary");
    const thoughtText = document.createElement("pre");
    thoughtBox.append(thoughtLabel, thoughtText);
    const list = document.createElement("ol");
    list.className = "development-trace-steps";
    host.append(thoughtBox, list);
    let key = "";
    return {
      update(thought, activity, live = true) {
        if (typeof thought === "string") {
          const text = thought.trim();
          thoughtBox.hidden = !text;
          const last = text.split("\n").filter(Boolean).at(-1) || "";
          thoughtLabel.textContent = (live ? "思考中 · " : "思考 · ") + last.slice(0, 90);
          if (thoughtText.textContent !== text) {
            thoughtText.textContent = text;
            thoughtText.scrollTop = thoughtText.scrollHeight;
          }
        }
        if (Array.isArray(activity)) {
          const next = activity.join("\n");
          if (next !== key) {
            key = next;
            const pinned = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
            list.replaceChildren(...activity.map((line) => {
              const row = document.createElement("li");
              const cut = line.indexOf(": ");
              if (cut > 0 && cut < 24) {
                append(row, "span", line.slice(0, cut)).className = "development-trace-kind";
                append(row, "code", line.slice(cut + 2));
              } else {
                append(row, "span", line);
              }
              return row;
            }));
            if (pinned) list.scrollTop = list.scrollHeight;
          }
        }
        list.dataset.live = String(Boolean(live));
        host.hidden = thoughtBox.hidden && !list.children.length;
      },
    };
  }

  function watchProgress(element, job, refresh, options = {}) {
    element.setAttribute("aria-live", "polite");
    const replyBox = options.replyBox || element.closest(".development-thread-reply");
    const trace = options.trace || null;
    const useStreaming = Boolean(options.streamReply && replyBox && window.PetitChatMotion?.createStreamingController);
    const labelFor = ({ status, phase, tool }) => {
      if (status === "running" && tool) return "ツール実行中: " + tool + "…";
      return (status === "running" && (retryPhases[phase] || phases[phase])) || states[status] || "";
    };
    const initialLabel = labelFor({ status: job.status, phase: job.events?.at(-1)?.kind });
    const streamCtrl = (useStreaming && active.has(job.status))
      ? window.PetitChatMotion.createStreamingController(replyBox, initialLabel || "CLIに応答を依頼中…")
      : null;
    const update = (payload) => {
      const next = labelFor(payload);
      if (streamCtrl) {
        if (payload.draft) {
          streamCtrl.updateDraft(payload.draft);
        } else if (next) {
          streamCtrl.setPhase(next);
        }
      } else {
        if (element.textContent !== next) element.textContent = next;
      }
      if (options.onStatus && payload.status) options.onStatus(payload.status);
      if (trace && (payload.thought !== undefined || payload.activity !== undefined)) {
        trace.update(payload.thought, payload.activity);
      }
      if (replyBox && !streamCtrl) replyBox.classList.toggle("is-streaming-status", active.has(payload.status));
    };
    if (!streamCtrl) update({ status: job.status, phase: job.events?.at(-1)?.kind });
    if (!active.has(job.status) || typeof EventSource !== "function") return;
    closeProgress(element);
    const stream = new EventSource("/api/coding/jobs/" + encodeURIComponent(job.id) + "/stream");
    progressStreams.set(element, stream);
    const finishIfDone = (status) => {
      if (!active.has(status)) {
        streamCtrl?.finish();
        if (replyBox) replyBox.classList.remove("is-streaming-status");
        closeProgress(element);
        void refresh();
        return true;
      }
      return false;
    };
    const parseEvent = (event) => {
      try { return JSON.parse(event.data); }
      catch { return null; } // A malformed SSE event must not break later progress updates.
    };
    stream.addEventListener("progress", (event) => {
      const value = parseEvent(event);
      if (value) update(value);
      if (!value) return;
      finishIfDone(value.status);
    });
    stream.addEventListener("draft", (event) => {
      const value = parseEvent(event);
      if (value) update(value);
      if (value) finishIfDone(value.status);
    });
  }

  async function api(path, method = "GET", body) {
    const response = await fetch("/api/coding" + path, {
      method, cache: "no-store", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-PETIT-Request": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "処理を完了できませんでした。");
    }
    return data;
  }

  function append(parent, tag, value) {
    const element = document.createElement(tag);
    element.textContent = value;
    parent.append(element);
    return element;
  }

  function button(parent, label, onClick, onError) {
    const element = append(parent, "button", label);
    element.type = "button";
    element.addEventListener("click", async () => {
      element.disabled = true;
      try { await onClick(); }
      catch (error) { onError(error.message); }
      finally { element.disabled = false; }
    });
    return element;
  }

  function quotaText(item) {
    const percent = (value) => value == null ? "不明" : value + "%";
    return "5時間 " + percent(item?.five_hour) + " / 週次 " + percent(item?.weekly) +
      (item?.estimated ? "（PETIT内の推定）" : "");
  }

  const fileMarks = { added: "A", modified: "M", deleted: "D", file: "·" };
  const fileStatus = { added: "追加", modified: "変更", deleted: "削除", file: "ファイル" };

  function renderDiff(target, entry) {
    const untracked = entry.diff.startsWith("New file: ");
    const lines = entry.diff.replace(/\n$/, "").split("\n");
    const header = /^(diff --git |index |--- |\+\+\+ |new file mode|deleted file mode|old mode|new mode|similarity index|New file: )/;
    let inBody = untracked;
    for (const [index, line] of lines.entries()) {
      if (untracked && index === 0) continue;
      if (!untracked && !inBody) {
        if (line.startsWith("@@")) inBody = true;
        else if (header.test(line)) continue;
      }
      const row = append(target, "span", line || " ");
      row.className = "development-diff-line";
      if (untracked || line.startsWith("+")) row.dataset.kind = "add";
      else if (line.startsWith("-")) row.dataset.kind = "del";
      else if (line.startsWith("@@")) row.dataset.kind = "hunk";
    }
    if (!target.children.length) append(target, "span", entry.binary ? "バイナリファイルのため差分を表示できません。" : "表示できる差分はありません。").className = "development-diff-line";
    if (entry.truncated) append(target, "span", "（表示上限のため以降を省略）").className = "development-diff-line";
  }

  // File list first (which files, how much); a file's diff opens only when its row is clicked.
  function mountChanges(parent, job, onError, auto = false) {
    const section = append(parent, "section", "");
    section.className = "development-changes";
    const head = append(section, "div", "");
    head.className = "development-changes-head";
    append(head, "strong", "変更ファイル");
    const total = append(head, "span", auto ? "読み込み中…" : "");
    total.className = "development-changes-total";
    const list = append(section, "div", "");
    list.className = "development-changes-list";
    const load = async () => {
      const result = await api("/jobs/" + encodeURIComponent(job.id) + "/diff");
      if (!section.isConnected) return;
      const entries = result.entries || result.files.map((path) => ({ path, status: "file", diff: "" }));
      list.replaceChildren();
      opener?.remove();
      if (!entries.length) {
        total.textContent = "変更されたファイルはありません";
        return;
      }
      const sum = (key) => entries.reduce((value, entry) => value + (entry[key] || 0), 0);
      total.replaceChildren(entries.length + " ファイル");
      if (entries.some((entry) => entry.additions != null)) {
        append(total, "span", "+" + sum("additions")).dataset.kind = "add";
        append(total, "span", "−" + sum("deletions")).dataset.kind = "del";
      }
      for (const entry of entries) {
        const item = append(list, "div", "");
        item.className = "development-file";
        const row = append(item, "button", "");
        row.type = "button";
        row.className = "development-file-row";
        row.setAttribute("aria-expanded", "false");
        const mark = append(row, "span", fileMarks[entry.status] || "·");
        mark.className = "development-file-mark";
        mark.dataset.status = entry.status;
        mark.title = fileStatus[entry.status] || entry.status;
        const slash = entry.path.lastIndexOf("/") + 1;
        const name = append(row, "span", "");
        name.className = "development-file-path";
        if (slash) append(name, "span", entry.path.slice(0, slash)).className = "development-file-dir";
        append(name, "strong", entry.path.slice(slash));
        const stat = append(row, "span", "");
        stat.className = "development-file-stat";
        if (entry.additions != null) {
          append(stat, "span", "+" + entry.additions).dataset.kind = "add";
          append(stat, "span", "−" + entry.deletions).dataset.kind = "del";
        }
        if (!entry.diff && !entry.binary) { row.disabled = true; continue; }
        append(row, "span", "›").className = "development-file-chevron";
        let pane;
        row.addEventListener("click", () => {
          if (!pane) {
            pane = append(item, "pre", "");
            pane.className = "development-file-diff";
            renderDiff(pane, entry);
            pane.hidden = true;
          }
          pane.hidden = !pane.hidden;
          row.setAttribute("aria-expanded", String(!pane.hidden));
        });
      }
    };
    let opener = null;
    if (auto) load().catch((error) => { total.textContent = ""; onError(error.message); });
    else opener = button(head, "変更ファイルを見る", load, onError);
    return section;
  }

  function notifyIsland() {
    void window.PetitIslandStatus?.refresh?.();
  }

  function card(box, job, refresh, compact = false, external = false) {
    box.replaceChildren();
    box.dataset.job = job.id;
    box.className = "coding-job";
    const route = "/jobs/" + encodeURIComponent(job.id);
    const info = append(box, "p", states[job.status] || job.status);
    info.className = "job-status";
    if (compact || !box.closest(".development-thread-turn")) watchProgress(info, job, refresh);
    append(box, "h3", job.goal);
    const selection = job.selection;
    append(box, "p", [job.repository || "PC全体", selection?.label || job.provider, job.model,
      selection?.effort, selection ? quotaText(selection.quota) : ""].filter(Boolean).join(" / "));
    if (job.base_commit) append(box, "p", "開始コミット " + job.base_commit.slice(0, 12));
    if (job.workspace) append(box, "p", "作業場所 " + job.workspace + (job.branch ? " / " + job.branch : ""));
    if (job.error) append(box, "p", job.error);
    if (job.summary) append(box, "p", job.summary);
    const actions = append(box, "div", "");
    actions.className = "actions";
    const notice = append(box, "p", "");
    notice.setAttribute("role", "status");
    const onError = (message) => { notice.textContent = message; };
    const decide = (path, label, parent = actions, className = "") => {
      const btn = button(parent, label, async () => {
        await api(route + path, "POST");
        notifyIsland();
        await refresh();
      }, onError);
      if (className) btn.className = className;
      return btn;
    };
    if (job.status === "proposed") {
      decide("/approve", "この内容で開発を依頼する");
      decide("/cancel", "キャンセル");
    } else if (active.has(job.status) || job.status === "waiting_approval") {
      decide("/cancel", job.cancel_requested ? "取消要求済み" : "ジョブを止める").disabled = Boolean(job.cancel_requested);
    }
    if (job.status === "ready_for_review" && !compact && !external) {
      button(actions, "レビュー完了", async () => {
        await api(route + "/complete", "POST");
        notifyIsland();
        await refresh();
      }, onError);
    }
    if (compact) {
      const link = append(box, "a", "Developで開発ジョブを確認");
      link.href = "/static/universe.html?view=development";
    } else {
      const testLabel = { not_run: "未実施", not_verified: "CLIの報告を参照", passed: "成功", failed: "失敗" };
      const staticChecks = job.checks?.static;
      const staticLabel = Array.isArray(staticChecks) ? "Core静的チェック " +
        (staticChecks.every(check => check.ok) ? "成功" : "失敗") + " / " : "";
      append(box, "p", staticLabel + "コマンド検証 " + (testLabel[job.tests] || "不明") + " / 実アプリ動作 未確認");
      if (job.workspace && !external) mountChanges(box, job, onError);
      const details = append(box, "details", "");
      append(details, "summary", "進捗・チェック結果");
      append(details, "pre", job.events.map(formatEventLine).join("\n") +
        "\n" + JSON.stringify(job.checks, null, 2));
    }
    for (const item of job.actions || []) {
      const panel = append(box, "section", "");
      const isPending = item.status === "proposed" && job.status === "waiting_approval";
      panel.className = isPending ? "development-action development-action--pending" : "development-action";
      const params = item.parameters;
      append(panel, "h4", (isPending ? "⚠️ PC操作の承認が必要です · " : "PC操作の確認 · ") + operations[item.operation]);
      const summary = item.operation === "command"
        ? { 実行フォルダ: params.path, コマンド: (params.argv || []).join(" ") }
        : { 対象: params.path, 移動先: params.destination, 作業ファイル: params.source };
      append(panel, "pre", JSON.stringify(summary, null, 2));
      if (isPending) {
        if (item.operation === "command" && item.whitelist_candidate) {
          const hint = append(panel, "p", `「今後も許可」を選ぶと、種別 (${item.whitelist_candidate}) がホワイトリストに追加され、次回から確認なしで実行されます。`);
          hint.className = "development-action-hint";
        }
        if (item.operation === "write") {
          const previewBtn = button(panel, "書き込み内容を見る", async () => {
            const result = await api(route + "/actions/" + item.id + "/preview");
            const preview = panel.querySelector(".diff") || append(panel, "pre", "");
            preview.className = "diff";
            preview.textContent = result.preview;
          }, onError);
          previewBtn.className = "development-btn";
        }
        const btnWrap = append(panel, "div", "");
        btnWrap.className = "development-action-buttons";
        decide("/actions/" + item.id + "/approve", "今回だけ許可して実行", btnWrap, "development-btn development-btn--primary");
        if (item.operation === "command") {
          decide("/actions/" + item.id + "/approve_always", "今後も許可して実行（ホワイトリストに追加）", btnWrap, "development-btn development-btn--whitelist");
        }
        decide("/actions/" + item.id + "/reject", "拒否する", btnWrap, "development-btn development-btn--danger");
      } else {
        const actionState = { proposed: "準備中", running: "実行中", applied: "実行済み", rejected: "拒否・取消",
          expired: "期限切れ", unknown: "結果不明・要確認" };
        append(panel, "p", actionState[item.status] || item.status);
      }
    }
  }

  const mounted = new Map();

  function attachProposal(parent, id) {
    if (!/^[a-f0-9]{32}$/.test(id || "")) return;
    const box = append(parent, "section", "");
    const route = "/jobs/" + id;
    let timer, signature;
    async function refresh() {
      clearTimeout(timer);
      try {
        const job = await api(route);
        if (!box.isConnected) return;
        const next = JSON.stringify(job);
        if (signature !== next) { signature = next; card(box, job, refresh, true); }
        if (active.has(job.status) || ["proposed", "waiting_approval"].includes(job.status)) {
          timer = setTimeout(refresh, document.hidden ? 15000 : 3000);
        }
        const list = $("development-jobs");
        if (list && !list.closest("[hidden]")) void refreshJobs();
      } catch (error) { box.textContent = error.message; }
    }
    void refresh();
  }

  window.PetitDevelopment = { attachProposal };
  const form = $("development-request");
  if (!form) return;
  const devPromptBox = (form.elements.goal && window.PetitChatMotion)
    ? window.PetitChatMotion.createPromptBox({
        form,
        textarea: form.elements.goal,
        submitBtn: form.querySelector('[type="submit"]'),
        minHeight: 84,
        maxHeight: 220,
        enableMorph: false,
      })
    : null;
  let justSubmittedThreadId = null;
  const composer = $("development-composer");
  const folders = $("development-roots");
  const notice = $("development-job-notice");
  const panel = form.closest("[data-view-panel]");
  const legacy = $("development-legacy-jobs");
  const advanced = $("development-advanced");
  const jobs = $("development-jobs");
  const levels = {
    home: $("development-home"), repo: $("development-repo-view"), thread: $("development-thread-view"),
  };
  const report = (message) => { notice.textContent = message || ""; };
  const timestamp = (value) => {
    const date = Date.parse(value || "");
    return Number.isFinite(date) ? new Date(date).toLocaleString("ja-JP") : "時刻不明";
  };
  const statusLabel = (status) => states[status] || status || "未開始";
  const shorten = (value, limit = 140) => String(value || "").slice(0, limit);
  const empty = (parent, message) => parent.replaceChildren(append(document.createDocumentFragment(), "p", message));
  let repositories = [];
  let currentView = "home";
  let currentRepo = "";
  let currentThread = null;
  let requestId;
  let newThreadId;
  let updatingJobs = false;
  let updatingUsage = false;
  let lastUsage = 0;
  let workspaceLoading = false;
  let threadRequestSeq = 0;

  function moveComposer(slot, repo = "") {
    if (composer.parentElement !== slot) {
      slot.append(composer);
    }
    form.elements.repository.value = repo;
    form.elements.repository.disabled = currentView === "thread" || currentView === "repo";
    if (currentView === "thread") {
      form.querySelector('[type="submit"]').textContent = "この会話で続ける";
    } else {
      form.querySelector('[type="submit"]').textContent = "開発を始める";
    }
  }

  function show(view) {
    currentView = view;
    for (const [name, element] of Object.entries(levels)) element.hidden = name !== view;
    const slot = view === "home" ? $("development-home-compose")
      : view === "repo" ? $("development-repo-compose") : $("development-thread-compose");
    moveComposer(slot, view === "home" ? "" : currentRepo);
  }

  const attentionPriority = {
    waiting_approval: 0, running: 1, queued: 2, proposed: 3, ready_for_review: 4, checks_failed: 5,
  };
  const VISIBLE_THREAD_LIMIT = 5;
  const expandedThreadGroups = new Set();
  const isActiveThread = (item) => active.has(item?.latest_job?.status);

  function partitionVisibleThreads(threads, { limit = VISIBLE_THREAD_LIMIT, hoistActive = true } = {}) {
    const items = Array.isArray(threads) ? threads : [];
    if (hoistActive) {
      const activeItems = [];
      const restItems = [];
      for (const item of items) {
        if (isActiveThread(item)) activeItems.push(item);
        else restItems.push(item);
      }
      const remainingSlots = Math.max(0, limit - activeItems.length);
      return {
        visible: [...activeItems, ...restItems.slice(0, remainingSlots)],
        overflow: restItems.slice(remainingSlots),
      };
    }
    const visible = [];
    const overflow = [];
    for (const item of items) {
      if (visible.length < limit || isActiveThread(item)) visible.push(item);
      else overflow.push(item);
    }
    return { visible, overflow };
  }

  function renderCollapsibleThreadList(threads, target, options = {}) {
    if (!target || !target.isConnected) return;
    target.replaceChildren();
    const { visible, overflow } = partitionVisibleThreads(threads, {
      limit: VISIBLE_THREAD_LIMIT,
      hoistActive: options.hoistActive !== false,
    });
    for (const item of visible) threadCard(target, item, options);
    if (!overflow.length) return;

    const groupKey = options.groupKey || target.id || "";
    const details = append(target, "details", "");
    details.className = "development-threads-more";
    if (groupKey && expandedThreadGroups.has(groupKey)) details.open = true;

    const summary = append(details, "summary", "");
    const label = append(summary, "span", "");
    const countBadge = append(summary, "span", overflow.length + "件");
    countBadge.className = "development-threads-more-count";
    const syncSummary = () => {
      label.textContent = details.open ? "過去のスレッドを折りたたむ" : "過去のスレッドを表示";
    };
    syncSummary();
    details.addEventListener("toggle", () => {
      if (groupKey) {
        if (details.open) expandedThreadGroups.add(groupKey);
        else expandedThreadGroups.delete(groupKey);
      }
      syncSummary();
    });

    const list = append(details, "div", "");
    list.className = "development-thread-list development-threads-more-list";
    for (const item of overflow) threadCard(list, item, options);
  }

  function repoLabel(repository) {
    if (!repository) return "PC全体";
    const found = repositories.find((item) => item.path === repository);
    if (found?.name) return found.name;
    const parts = String(repository).split(/[\\/]/).filter(Boolean);
    return parts.at(-1) || repository;
  }

  const triageLabels = { review_later: "あとで確認", completed: "完了" };
  let activeContextMenu = null;

  function svgIcon(pathData) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.9");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "development-context-icon");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", pathData);
    svg.appendChild(path);
    return svg;
  }

  function closeThreadContextMenu() {
    if (!activeContextMenu) return;
    const { backdrop, menu, cleanup } = activeContextMenu;
    activeContextMenu = null;
    cleanup();
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (reduced) {
      backdrop.remove();
      menu.remove();
      return;
    }
    backdrop.dataset.closing = "true";
    menu.dataset.closing = "true";
    window.setTimeout(() => {
      backdrop.remove();
      menu.remove();
    }, 150);
  }

  async function mutateThread(threadId, method, body) {
    return api("/threads/" + encodeURIComponent(threadId), method, body);
  }

  function openThreadContextMenu(data, anchor = {}) {
    closeThreadContextMenu();
    const triage = data.triage_status || "active";
    const backdrop = document.createElement("div");
    backdrop.className = "development-context-backdrop";

    const menu = document.createElement("div");
    menu.className = "development-context-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", (data.title || "開発チャット") + "の操作メニュー");

    const header = append(menu, "div", "");
    header.className = "development-context-header";
    const titleEl = append(header, "span", data.title || "名称未設定の開発チャット");
    titleEl.className = "development-context-title";
    const subEl = append(header, "span", [
      repoLabel(data.repository),
      statusLabel(data.latest_job?.status),
    ].filter(Boolean).join(" · "));
    subEl.className = "development-context-sub";

    const list = append(menu, "div", "");
    list.className = "development-context-list";

    let itemIndex = 0;
    const addMenuItem = ({ label, iconPath, active = false, danger = false, onSelect }) => {
      const btn = append(list, "button", "");
      btn.type = "button";
      btn.className = "development-context-item" + (danger ? " development-context-item--danger" : "");
      btn.setAttribute("role", "menuitem");
      btn.style.setProperty("--item-index", String(itemIndex++));
      if (active) btn.dataset.active = "true";
      btn.appendChild(svgIcon(iconPath));
      const textSpan = append(btn, "span", label);
      btn.addEventListener("click", () => void onSelect(btn, textSpan));
      return btn;
    };

    const refreshAfterAction = async () => {
      if (currentThread?.thread_id === data.thread_id) {
        await openThread(data.thread_id);
      }
      await refreshWorkspace();
    };

    const isReviewLater = triage === "review_later";
    addMenuItem({
      label: isReviewLater ? "あとで確認を外す" : "あとで確認",
      iconPath: "M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z",
      active: isReviewLater,
      onSelect: async () => {
        closeThreadContextMenu();
        try {
          await mutateThread(data.thread_id, "PATCH", {
            triage_status: isReviewLater ? "active" : "review_later",
          });
          await refreshAfterAction();
        } catch (error) { report(error.message); }
      },
    });

    const isCompleted = triage === "completed";
    addMenuItem({
      label: isCompleted ? "未完了に戻す" : "完了",
      iconPath: "M20 6 9 17l-5-5",
      active: isCompleted,
      onSelect: async () => {
        closeThreadContextMenu();
        try {
          await mutateThread(data.thread_id, "PATCH", {
            triage_status: isCompleted ? "active" : "completed",
          });
          await refreshAfterAction();
        } catch (error) { report(error.message); }
      },
    });

    addMenuItem({
      label: "スレッド名変更",
      iconPath: "M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z",
      onSelect: () => {
        list.replaceChildren();
        const form = append(list, "form", "");
        form.className = "development-context-rename";
        const input = append(form, "input", "");
        input.type = "text";
        input.maxLength = 160;
        input.placeholder = "スレッドのタイトル";
        input.value = data.title || "";
        const actions = append(form, "div", "");
        actions.className = "development-context-rename-actions";
        const cancelBtn = append(actions, "button", "キャンセル");
        cancelBtn.type = "button";
        cancelBtn.addEventListener("click", closeThreadContextMenu);
        const saveBtn = append(actions, "button", "保存");
        saveBtn.type = "submit";
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          saveBtn.disabled = true;
          try {
            await mutateThread(data.thread_id, "PATCH", { title: input.value });
            closeThreadContextMenu();
            await refreshAfterAction();
          } catch (error) {
            saveBtn.disabled = false;
            report(error.message);
          }
        });
        window.setTimeout(() => { input.focus(); input.select(); }, 20);
      },
    });

    const divider = append(list, "div", "");
    divider.className = "development-context-divider";

    let confirmDelete = false;
    addMenuItem({
      label: "削除",
      iconPath: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6",
      danger: true,
      onSelect: async (btn, textSpan) => {
        if (!confirmDelete) {
          confirmDelete = true;
          btn.dataset.confirm = "true";
          textSpan.textContent = "もう一度押して削除";
          return;
        }
        closeThreadContextMenu();
        if (anchor.card?.isConnected) anchor.card.dataset.removing = "true";
        try {
          await mutateThread(data.thread_id, "DELETE");
          if (currentThread?.thread_id === data.thread_id) {
            currentThread = null;
            newThreadId = undefined;
            show(currentRepo ? "repo" : "home");
          }
          window.setTimeout(() => void refreshWorkspace(), 180);
        } catch (error) {
          if (anchor.card?.isConnected) delete anchor.card.dataset.removing;
          report(error.message);
        }
      },
    });

    document.body.append(backdrop, menu);

    const rect = menu.getBoundingClientRect();
    const cardRect = anchor.card?.getBoundingClientRect?.();
    const rawX = typeof anchor.x === "number" && anchor.x > 0
      ? anchor.x - rect.width * 0.5
      : (cardRect ? cardRect.left + cardRect.width * 0.5 - rect.width * 0.5 : 16);
    const rawY = typeof anchor.y === "number" && anchor.y > 0
      ? anchor.y + 10
      : (cardRect ? cardRect.bottom + 8 : 64);
    const left = Math.max(12, Math.min(rawX, window.innerWidth - rect.width - 12));
    const fitsBelow = rawY + rect.height + 12 <= window.innerHeight;
    const top = fitsBelow
      ? Math.max(12, rawY)
      : Math.max(12, (typeof anchor.y === "number" && anchor.y > 0 ? anchor.y : (cardRect?.top || window.innerHeight * 0.5)) - rect.height - 10);
    menu.style.left = left + "px";
    menu.style.top = top + "px";
    const originX = typeof anchor.x === "number" && anchor.x > 0 ? Math.max(12, Math.min(rect.width - 12, anchor.x - left)) : rect.width * 0.5;
    menu.style.setProperty("--menu-origin-x", originX + "px");
    menu.style.setProperty("--menu-origin-y", fitsBelow ? "0%" : "100%");

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeThreadContextMenu();
      }
    };
    const onResize = () => closeThreadContextMenu();
    backdrop.addEventListener("click", closeThreadContextMenu);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);

    activeContextMenu = {
      backdrop,
      menu,
      cleanup: () => {
        window.removeEventListener("keydown", onKeyDown);
        window.removeEventListener("resize", onResize);
      },
    };
    const firstItem = menu.querySelector(".development-context-item");
    firstItem?.focus({ preventScroll: true });
  }

  function attachThreadLongPress(control, data) {
    let pressTimer = 0;
    let holdVisualTimer = 0;
    let startX = 0;
    let startY = 0;
    let suppressClick = false;

    const clearTimers = () => {
      if (pressTimer) { window.clearTimeout(pressTimer); pressTimer = 0; }
      if (holdVisualTimer) { window.clearTimeout(holdVisualTimer); holdVisualTimer = 0; }
      delete control.dataset.pressing;
    };

    control.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      clearTimers();
      suppressClick = false;
      startX = event.clientX;
      startY = event.clientY;
      holdVisualTimer = window.setTimeout(() => {
        control.dataset.pressing = "true";
      }, 110);
      pressTimer = window.setTimeout(() => {
        clearTimers();
        suppressClick = true;
        control.dataset.popped = "true";
        window.setTimeout(() => { delete control.dataset.popped; }, 380);
        navigator.vibrate?.(12);
        openThreadContextMenu(data, { x: startX, y: startY, card: control });
      }, 470);
    });

    control.addEventListener("pointermove", (event) => {
      if (!pressTimer) return;
      if (Math.hypot(event.clientX - startX, event.clientY - startY) > 10) {
        clearTimers();
      }
    });

    control.addEventListener("pointerup", clearTimers);
    control.addEventListener("pointercancel", clearTimers);
    control.addEventListener("pointerleave", clearTimers);

    control.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      clearTimers();
      openThreadContextMenu(data, { x: event.clientX, y: event.clientY, card: control });
    });

    control.addEventListener("keydown", (event) => {
      if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
        event.preventDefault();
        openThreadContextMenu(data, { card: control });
      }
    });

    control.addEventListener("click", (event) => {
      if (suppressClick) {
        event.preventDefault();
        event.stopImmediatePropagation();
        suppressClick = false;
      }
    }, true);
  }

  function threadCard(parent, data, options = {}) {
    const latest = data.latest_job;
    const status = latest?.status || "";
    const triage = data.triage_status || "active";
    const isRunning = active.has(status);
    const needsAttention = Object.hasOwn(attentionPriority, status);
    const control = append(parent, "button", "");
    control.type = "button";
    control.className = "development-thread-card";
    if (isRunning) {
      control.dataset.active = "true";
      control.dataset.status = status;
    } else if (needsAttention) {
      control.dataset.attention = "true";
      control.dataset.status = status;
    }
    if (triage !== "active") {
      control.dataset.triage = triage;
    }
    const head = append(control, "div", "");
    head.className = "development-thread-card-head";
    append(head, "strong", data.title || "名称未設定の開発チャット");
    if (isRunning || needsAttention || triageLabels[triage]) {
      const badges = append(head, "div", "");
      badges.className = "development-thread-badges";
      if (triageLabels[triage]) {
        const triageBadge = append(badges, "span", triageLabels[triage]);
        triageBadge.className = "development-triage-badge";
        triageBadge.dataset.triage = triage;
      }
      if (isRunning) {
        const activeBadge = append(badges, "span", statusLabel(status));
        activeBadge.className = "development-active-badge";
        activeBadge.dataset.status = status;
      } else if (needsAttention) {
        const badge = append(badges, "span", statusLabel(status));
        badge.className = "development-attention-badge";
        badge.dataset.status = status;
      }
    }
    const meta = append(control, "span", [
      options.showRepository ? repoLabel(data.repository) : null,
      latest?.provider || "CLI未選択",
      statusLabel(latest?.status),
      timestamp(latest?.updated_at || data.created_at),
    ].filter(Boolean).join(" · "));
    meta.className = "development-muted";
    const preview = append(control, "span", shorten(latest?.latest_message || "まだ開発依頼はありません。"));
    preview.className = "development-thread-preview";
    attachThreadLongPress(control, data);
    control.addEventListener("click", () => void openThread(data.thread_id));
  }

  function renderAttentionThreads(threads) {
    const section = $("development-attention-section");
    const target = $("development-attention-threads");
    const count = $("development-attention-count");
    if (!section || !target) return;
    const items = (threads || [])
      .filter((item) => Object.hasOwn(attentionPriority, item.latest_job?.status))
      .sort((a, b) => {
        const diff = attentionPriority[a.latest_job.status] - attentionPriority[b.latest_job.status];
        if (diff !== 0) return diff;
        const ta = Date.parse(a.latest_job?.updated_at || a.created_at || "") || 0;
        const tb = Date.parse(b.latest_job?.updated_at || b.created_at || "") || 0;
        return tb - ta;
      });
    target.replaceChildren();
    section.hidden = items.length === 0;
    if (count) count.textContent = items.length ? items.length + "件" : "";
    renderCollapsibleThreadList(items, target, { showRepository: true, groupKey: "attention", hoistActive: false });
  }

  function renderThreadList(threads, target, groupKey = "") {
    if (!target || !target.isConnected) return;
    target.replaceChildren();
    if (!threads.length) {
      empty(target, "開発チャットはまだありません。上の入力欄から始められます。");
      return;
    }
    renderCollapsibleThreadList(threads, target, { groupKey: groupKey || target.id || "" });
  }

  async function loadThreads(repository, target) {
    const response = await api("/threads?repository=" + encodeURIComponent(repository));
    renderThreadList(response.threads, target, "repo:" + repository);
  }

  function renderRepositories() {
    const list = $("development-repositories");
    list.replaceChildren();
    $("development-repository-count").textContent = repositories.length + "件";
    if (!repositories.length) {
      empty(list, "登録済みフォルダはありません。下の「管理・旧ジョブ履歴・診断」から追加できます。");
      return;
    }
    for (const root of repositories) {
      const control = append(list, "button", "");
      control.type = "button";
      control.className = "development-repository-card";
      const heading = append(control, "strong", root.name || root.path);
      const arrow = append(heading, "span", " ›");
      arrow.setAttribute("aria-hidden", "true");
      append(control, "span", shorten(root.path, 160)).className = "development-muted";
      const parts = [
        root.mode === "git" ? "Git" : "フォルダ",
        root.branch || (root.error ? "取得失敗" : "ブランチ不明"),
        root.changed == null ? "変更 未確認" : "変更 " + root.changed + "件",
        "会話 " + root.thread_count + "件",
      ];
      if ((root.extra_folders || []).length) {
        parts.push("追加フォルダ " + root.extra_folders.length + "件");
      }
      append(control, "span", parts.join(" · ")).className = "development-repository-meta";
      if (root.latest_job) append(control, "span",
        shorten(root.latest_job.summary || root.latest_job.goal, 120) +
        " / " + statusLabel(root.latest_job.status)).className = "development-thread-preview";
      if (root.error) append(control, "span", root.error).className = "development-muted";
      control.disabled = Boolean(root.error);
      control.addEventListener("click", () => void openRepository(root.path));
    }
  }

  async function refreshWorkspace() {
    if (workspaceLoading) return;
    workspaceLoading = true;
    try {
      const snapshot = await api("/workspaces");
      repositories = snapshot.repositories || [];
      renderRepositories();
      if (currentView === "home") {
        const all = await api("/threads");
        renderAttentionThreads(all.threads);
        renderThreadList(all.threads.filter((item) => !item.repository), $("development-loose-threads"), "loose");
      } else if (currentView === "repo") {
        renderCurrentRepository();
        await loadThreads(currentRepo, $("development-repo-threads"));
      }
    } catch (error) { report(error.message); }
    finally { workspaceLoading = false; }
  }

  function renderCurrentRepository() {
    const root = repositories.find((item) => item.path === currentRepo);
    $("development-repo-title").textContent = root?.name || "開発ワークスペース";
    $("development-nav-repo").textContent = root?.name || "";
    if (!root) {
      $("development-repo-status").textContent = "登録先が見つかりません。";
      return;
    }
    const recent = root.latest_job;
    $("development-repo-status").textContent = [
      root.path, root.mode === "git" ? "ブランチ " + (root.branch || "不明") : "Git未設定",
      root.changed == null ? "変更 未確認" : "変更 " + root.changed + "件",
      recent ? "最後の依頼 " + statusLabel(recent.status) + "（" + timestamp(recent.updated_at) + "）" : "開発依頼はまだありません",
      "確認 " + timestamp(root.observed_at),
    ].join(" · ");
    renderRepositoryExtras(root);
  }

  function renderRepositoryExtras(root) {
    const extras = root?.extra_folders || [];
    const count = $("development-repo-extra-count");
    if (count) count.textContent = extras.length ? extras.length + "件" : "なし";
    const list = $("development-repo-extra-list");
    if (!list) return;
    list.replaceChildren();
    if (!extras.length) {
      empty(list, "このリポジトリに紐付けた追加フォルダはありません。");
      return;
    }
    for (const extra of extras) {
      const row = append(list, "li", "");
      append(row, "span", extra.path + (extra.error ? " · " + extra.error : ""));
      button(row, "外す", async () => {
        await api("/config/root/extra", "DELETE", { repository: root.path, path: extra.path });
        report("追加フォルダの紐付けを外しました。");
        await refreshConfig();
        await refreshWorkspace();
      }, report);
    }
  }

  async function openRepository(path) {
    currentRepo = path;
    currentThread = null;
    newThreadId = undefined;
    show("repo");
    renderCurrentRepository();
    try { await loadThreads(path, $("development-repo-threads")); }
    catch (error) { report(error.message); }
  }

  function renderReplyBody(message, job) {
    if (job.summary) {
      if (window.PetitMarkdown?.renderTo) {
        window.PetitMarkdown.renderTo(message, job.summary);
      } else {
        message.textContent = job.summary;
      }
      return;
    }
    if (job.error) {
      message.classList.add("development-thread-error");
      message.textContent = "エラー: " + job.error;
      return;
    }
    message.textContent = states[job.status] || "";
  }

  // One tap continues a stopped job in the same thread; the CLI session resumes when the Core can.
  const stoppedGoal = "前回の作業が途中で止まりました。作業ファイルとGitの状態を確認し、前回の依頼の続きから進めてください。";
  const resumeGoals = {
    interrupted: stoppedGoal, failed: stoppedGoal, cancelled: stoppedGoal,
    checks_failed: "前回の変更で静的チェックが失敗しました。原因を確認して修正してください。",
  };

  function buildTurnElement(job, latest = false) {
    const entry = document.createElement("article");
    entry.className = "development-thread-turn";
    entry.dataset.jobId = job.id;
    entry.dataset.jobStatus = job.status;
    entry.dataset.jobSig = JSON.stringify([
      job.status, job.summary || "", job.error || "", job.updated_at || "",
      (job.actions || []).map((a) => a.status),
    ]);
    append(entry, "p", job.goal).className = "development-thread-user";
    const reply = append(entry, "div", "");
    reply.className = "development-thread-reply";
    const metaRow = append(reply, "div", "");
    metaRow.className = "development-thread-reply-meta";
    const metaLabel = append(metaRow, "strong", [job.provider || "CLI", statusLabel(job.status)].join(" · "));
    const onStatus = (status) => { metaLabel.textContent = [job.provider || "CLI", statusLabel(status)].join(" · "); };
    append(metaRow, "small", timestamp(job.updated_at)).className = "development-muted";
    const streamHost = append(reply, "div", "");
    streamHost.className = "development-thread-stream";
    const message = append(streamHost, "div", "");
    message.className = "message-body development-thread-body";
    const trace = createTrace(append(reply, "div", ""));
    const refreshThread = () => {
      if (currentView === "thread" && currentThread) return openThread(currentThread.thread_id);
    };
    if (active.has(job.status)) {
      watchProgress(message, job, refreshThread, { replyBox: streamHost, trace, streamReply: true, onStatus });
    } else {
      renderReplyBody(message, job);
      const traces = (job.events || []).filter((ev) => ev.detail && ev.kind !== "cli_failure");
      if (traces.length) {
        const traceDetails = append(reply, "details", "");
        traceDetails.className = "development-thread-trace-details";
        append(traceDetails, "summary", "実行過程・途中応答（" + traces.length + "件）");
        createTrace(append(traceDetails, "div", "")).update(undefined, traces.map((ev) =>
          ev.kind === "cli_tool" ? ev.detail : (retryPhases[ev.kind] || phases[ev.kind] || ev.kind) + ": " + ev.detail), false);
      }
    }
    const review = job.status === "ready_for_review";
    if (review) {
      // The decision stays visible: no need to open the details to finish a review.
      const panel = append(entry, "section", "");
      panel.className = "development-review";
      const bar = append(panel, "div", "");
      bar.className = "development-review-bar";
      const text = append(bar, "div", "");
      append(text, "strong", "レビュー待ち");
      append(text, "span", "変更内容を確認して、問題なければ完了にしてください。");
      const notice = document.createElement("p");
      notice.className = "development-review-notice";
      notice.setAttribute("role", "status");
      const onError = (value) => { notice.textContent = value; };
      const done = button(bar, "レビュー完了", async () => {
        await api("/jobs/" + encodeURIComponent(job.id) + "/complete", "POST");
        notifyIsland();
        await refreshThread();
      }, onError);
      done.className = "development-primary";
      if (job.workspace) mountChanges(panel, job, onError, true);
      panel.append(notice);
    }
    if (latest && resumeGoals[job.status] && currentThread) {
      const bar = append(entry, "div", "");
      bar.className = "development-review-bar development-resume";
      const text = append(bar, "div", "");
      append(text, "strong", statusLabel(job.status));
      append(text, "span", "同じ会話・同じモデル設定で続きを依頼します。");
      const notice = document.createElement("p");
      notice.className = "development-review-notice";
      notice.setAttribute("role", "status");
      const resumeId = crypto.randomUUID();
      button(bar, "続きから再開", async () => {
        const threadId = currentThread.thread_id;
        await api("/jobs/start", "POST", {
          request_id: resumeId, repository: currentThread.repository, goal: resumeGoals[job.status],
          thread_id: threadId, model_key: job.selection?.model_key || "auto",
          effort: job.selection?.effort || "medium",
        });
        justSubmittedThreadId = threadId;
        await refreshThread();
      }, (value) => { notice.textContent = value; }).className = "development-primary";
      entry.append(notice);
    }
    const detail = append(entry, "details", "");
    detail.className = "development-thread-details";
    if (job.status === "waiting_approval") {
      detail.dataset.attention = "true";
      detail.open = true;
    }
    append(detail, "summary", job.status === "waiting_approval" ? "PC操作の承認が必要です" : "詳細・進捗");
    const area = append(detail, "div", "");
    card(area, job, () => openThread(currentThread.thread_id), false, review);
    return entry;
  }

  function renderJobHistory(items) {
    const list = $("development-thread-history");
    if (!items.length) {
      list.replaceChildren();
      empty(list, "まだ開発依頼がありません。");
      return;
    }
    const existingById = new Map(
      Array.from(list.children)
        .filter((el) => el.dataset?.jobId)
        .map((el) => [el.dataset.jobId, el])
    );
    const sameOrder =
      existingById.size === items.length &&
      items.every((job, idx) => list.children[idx]?.dataset?.jobId === job.id);

    if (sameOrder) {
      for (const job of items) {
        const currentEl = existingById.get(job.id);
        const nextSig = JSON.stringify([
          job.status, job.summary || "", job.error || "", job.updated_at || "",
          (job.actions || []).map((a) => a.status),
        ]);
        const isStreamingNow = active.has(job.status) && progressStreams.has(currentEl?.querySelector(".development-thread-body"));
        if (isStreamingNow || currentEl?.dataset.jobSig === nextSig) {
          continue;
        }
        const replacement = buildTurnElement(job, job === items.at(-1));
        currentEl.replaceWith(replacement);
      }
    } else {
      list.replaceChildren(...items.map((job, index) => buildTurnElement(job, index === items.length - 1)));
    }

    if (justSubmittedThreadId && justSubmittedThreadId === currentThread?.thread_id) {
      justSubmittedThreadId = null;
      const lastTurn = list.lastElementChild;
      if (lastTurn && window.PetitChatMotion) {
        const userEl = lastTurn.querySelector(".development-thread-user");
        const replyEl = lastTurn.querySelector(".development-thread-reply");
        if (userEl) window.PetitChatMotion.animateMessageIn(userEl, true);
        if (replyEl) window.PetitChatMotion.animateMessageIn(replyEl, false);
      }
      lastTurn?.scrollIntoView?.({ behavior: "smooth", block: "end" });
    }
  }

  async function openThread(id) {
    const reqSeq = ++threadRequestSeq;
    const threadChanged = currentThread?.thread_id !== id;
    try {
      const data = await api("/threads/" + encodeURIComponent(id));
      if (reqSeq !== threadRequestSeq) return;
      currentThread = data;
      currentRepo = data.repository;
      show("thread");
      if (threadChanged) $("development-thread-rename-form").hidden = true;
      $("development-thread-title").textContent = data.title || "開発チャット";
      $("development-nav-thread").textContent = data.title || "開発チャット";
      const parent = repositories.find((item) => item.path === data.repository);
      $("development-back-thread").textContent = "← " + (parent?.name || (data.repository ? "リポジトリ" : "一覧"));
      const waiting = data.jobs.filter((job) => noticed.has(job.status)).map((job) => job.id);
      if (waiting.length && !panel.hidden) window.PetitIslandStatus?.acknowledgeReviews?.(waiting);
      const latest = data.jobs[data.jobs.length - 1];
      $("development-thread-meta").textContent = [
        data.repository || "リポジトリなし", latest?.provider || "CLI未選択",
        latest ? statusLabel(latest.status) : "未開始",
      ].join(" · ");
      renderJobHistory(data.jobs);
      const attachPanel = $("development-thread-attach");
      attachPanel.hidden = Boolean(data.repository) || !repositories.some((item) => !item.error);
      const select = $("development-thread-attach-repo");
      select.replaceChildren();
      for (const root of repositories.filter((item) => !item.error)) {
        select.add(new Option(root.name + " (" + root.path + ")", root.path));
      }
    } catch (error) {
      if (reqSeq === threadRequestSeq) report(error.message);
    }
  }

  async function refreshJobs() {
    if (!legacy.open || !advanced.open || updatingJobs) return;
    updatingJobs = true;
    try {
      const result = await api("/jobs");
      for (const [id, element] of mounted) {
        if (!result.jobs.some((job) => job.id === id)) {
          element.remove(); mounted.delete(id);
        }
      }
      if (!result.jobs.length) {
        jobs.textContent = "過去の開発ジョブはありません。";
        return;
      }
      if (!mounted.size) jobs.replaceChildren();
      for (const job of [...result.jobs].reverse()) {
        const signature = JSON.stringify(job);
        let box = mounted.get(job.id);
        if (!box) {
          box = document.createElement("article");
          mounted.set(job.id, box);
          jobs.prepend(box);
        }
        if (signature !== box.jobSignature) {
          box.jobSignature = signature;
          card(box, job, refreshJobs);
        }
      }
    } catch (error) { report(error.message); }
    finally { updatingJobs = false; }
  }

  async function refreshUsage() {
    if (!advanced.open || updatingUsage || Date.now() - lastUsage < 60000) return;
    updatingUsage = true;
    try {
      const response = await api("/usage");
      $("development-usage").textContent = Object.values(response.models).map((item) =>
        item.label + " " + quotaText(item) + (item.available ? "" : " · 利用可否を確認")).join(" ｜ ");
      lastUsage = Date.now();
    } catch (error) { report(error.message); }
    finally { updatingUsage = false; }
  }

  function renderConfig(data) {
    const selected = form.elements.repository.value;
    const select = form.elements.repository;
    select.replaceChildren(new Option("指定なし（PC内の全ファイルを見る）", ""));
    for (const root of data.repositories.filter((item) => !item.error)) {
      select.add(new Option(root.name + (root.mode === "git" ? "（Git）" : "（フォルダ）"), root.path));
    }
    select.value = currentView === "home" ? selected : currentRepo;
    const model = form.elements.model_key;
    const modelValue = model.value;
    model.replaceChildren(new Option("自動（残量優先）", "auto"),
      ...data.models.map((item) => new Option(item.label, item.key)));
    model.value = modelValue || "auto";
    const list = $("development-root-list");
    list.replaceChildren();
    for (const root of data.repositories) {
      const row = append(list, "li", root.path + (root.error ? " · " + root.error : ""));
      if (root.source === "environment") append(row, "small", " サーバー設定");
      else button(row, "登録を外す", async () => {
        await api("/config/root", "DELETE", { path: root.path });
        await refreshConfig();
        await refreshWorkspace();
      }, report);
      if ((root.extra_folders || []).length) {
        const sub = append(row, "ul", "");
        sub.className = "development-extra-sublist";
        for (const extra of root.extra_folders) {
          const extraRow = append(sub, "li", extra.path + (extra.error ? " · " + extra.error : ""));
          button(extraRow, "外す", async () => {
            await api("/config/root/extra", "DELETE", { repository: root.path, path: extra.path });
            await refreshConfig();
            await refreshWorkspace();
          }, report);
        }
      }
    }
  }

  async function refreshConfig() {
    try { renderConfig(await api("/config")); }
    catch (error) { report(error.message); }
  }

  form.addEventListener("input", () => { requestId = undefined; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector('[type="submit"]');
    if (submit.disabled) return;
    submit.disabled = true;
    devPromptBox?.setStatus("think", "開発ジョブを送信中…");
    const input = Object.fromEntries(new FormData(form));
    input.repository = currentView === "home" ? input.repository : currentRepo;
    requestId ||= crypto.randomUUID();
    try {
      if (!currentThread) {
        newThreadId ||= crypto.randomUUID().replace(/-/g, "");
        currentThread = await api("/threads", "POST", {
          thread_id: newThreadId, repository: input.repository, title: "",
        });
      }
      const job = await api("/jobs/start", "POST", {
        ...input, thread_id: currentThread.thread_id, request_id: requestId,
        lightweight: input.lightweight === "on",
      });
      requestId = undefined;
      newThreadId = undefined;
      if (form.elements.goal.value === input.goal) {
        form.elements.goal.value = "";
        devPromptBox?.fit();
      }
      justSubmittedThreadId = currentThread.thread_id;
      const submittedThreadId = currentThread.thread_id;
      devPromptBox?.setStatus("done", "開発ジョブを開始しました", 2.0);
      report("開発を受け付けました: " + statusLabel(job.status));
      await openThread(submittedThreadId);
      void refreshWorkspace();
      if (!currentThread?.title) {
        setTimeout(() => {
          if (currentThread?.thread_id === submittedThreadId && !currentThread.title) {
            void openThread(submittedThreadId);
            void refreshWorkspace();
          }
        }, 1800);
      }
    } catch (error) {
      devPromptBox?.setStatus("error", error.message || "送信に失敗しました", 3.0);
      report(error.message);
    }
    finally { submit.disabled = false; }
  });

  folders.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/config/root", "POST", { path: folders.elements.path.value.trim() });
      folders.reset();
      report("フォルダを登録しました。");
      await refreshConfig();
      await refreshWorkspace();
    } catch (error) { report(error.message); }
  });
  const extraForm = $("development-repo-extra-form");
  if (extraForm) {
    extraForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!currentRepo) return;
      try {
        await api("/config/root/extra", "POST", {
          repository: currentRepo,
          path: extraForm.elements.path.value.trim(),
        });
        extraForm.reset();
        report("追加フォルダを紐付けました。");
        await refreshConfig();
        await refreshWorkspace();
      } catch (error) { report(error.message); }
    });
  }
  const goHome = () => {
    currentRepo = ""; currentThread = null; newThreadId = undefined;
    show("home"); void refreshWorkspace();
  };
  $("development-back-home").addEventListener("click", goHome);
  $("development-nav-home").addEventListener("click", goHome);
  $("development-back-thread").addEventListener("click", () => {
    const repo = currentThread?.repository || "";
    currentThread = null; newThreadId = undefined;
    if (repo) void openRepository(repo);
    else { currentRepo = ""; show("home"); void refreshWorkspace(); }
  });
  $("development-thread-rename").addEventListener("click", () => {
    if (!currentThread) return;
    const form = $("development-thread-rename-form");
    form.hidden = !form.hidden;
    if (!form.hidden) {
      const input = $("development-thread-rename-input");
      input.value = currentThread.title || "";
      input.focus();
    }
  });
  $("development-thread-rename-cancel").addEventListener("click", () => {
    $("development-thread-rename-form").hidden = true;
  });
  $("development-thread-rename-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentThread) return;
    const input = $("development-thread-rename-input");
    try {
      const response = await fetch("/api/threads/" + encodeURIComponent(currentThread.thread_id), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: input.value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "タイトルを更新できませんでした。");
      currentThread.title = data.title;
      $("development-thread-title").textContent = data.title || "開発チャット";
      $("development-nav-thread").textContent = data.title || "開発チャット";
      $("development-thread-rename-form").hidden = true;
      void refreshWorkspace();
    } catch (error) { report(error.message); }
  });
  $("development-thread-attach-button").addEventListener("click", async () => {
    if (!currentThread) return;
    try {
      const root = $("development-thread-attach-repo").value;
      const result = await api("/threads/" + encodeURIComponent(currentThread.thread_id) +
        "/repository", "POST", { repository: root });
      currentThread.repository = result.repository;
      currentRepo = result.repository;
      await openThread(currentThread.thread_id);
      void refreshWorkspace();
    } catch (error) { report(error.message); }
  });
  async function openJobThread(jobId) {
    try {
      const all = await api("/threads");
      const threads = all.threads || [];
      const exact = jobId ? threads.find((item) => item.latest_job?.id === jobId) : null;
      const fallback = exact
        || threads.find((item) => item.latest_job?.status === "running")
        || threads.find((item) => Object.hasOwn(attentionPriority, item.latest_job?.status));
      if (fallback) await openThread(fallback.thread_id);
    } catch (error) { report(error.message); }
  }
  window.PetitDevelopment = { attachProposal, openThread, openJobThread };

  // A notification links to its thread with ?dev_thread=<id>; open it once and drop the parameter.
  const openLinkedThread = () => {
    const url = new URL(window.location.href);
    const id = url.searchParams.get("dev_thread");
    if (!id) return;
    url.searchParams.delete("dev_thread");
    window.history.replaceState(window.history.state, "", url);
    void openThread(id);
  };
  // Opening Develop renews the CLI quota cache behind the scenes, so the first request does not wait for the probes.
  let lastWarm = 0;
  const warmUsage = () => {
    if (Date.now() - lastWarm < 60000) return;
    lastWarm = Date.now();
    void api("/usage").catch(() => {});
  };
  const refresh = () => {
    warmUsage();
    void refreshConfig();
    void refreshWorkspace();
    void refreshJobs();
    void refreshUsage();
    if (currentView === "thread" && currentThread) void openThread(currentThread.thread_id);
  };
  $("development-refresh").addEventListener("click", refresh);
  advanced.addEventListener("toggle", () => {
    if (advanced.open) { void refreshJobs(); void refreshUsage(); }
  });
  legacy.addEventListener("toggle", () => { if (legacy.open) void refreshJobs(); });
  window.addEventListener("petit:area-change", (event) => {
    if (event.detail?.area === "development") { refresh(); openLinkedThread(); }
  });
  setInterval(() => {
    if (document.hidden || panel.hidden) return;
    void refreshWorkspace();
    if (currentView === "thread" && currentThread) void openThread(currentThread.thread_id);
    void refreshJobs();
    void refreshUsage();
  }, 12000);
  show("home");
  if (!panel.hidden) { refresh(); openLinkedThread(); }
})();
