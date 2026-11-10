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
  const $ = (id) => document.getElementById(id);

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

  function card(box, job, refresh, compact = false) {
    box.replaceChildren();
    box.dataset.job = job.id;
    box.className = "coding-job";
    const route = "/jobs/" + encodeURIComponent(job.id);
    const info = append(box, "p", states[job.status] || job.status);
    info.className = "job-status";
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
    const decide = (path, label, parent = actions) => button(parent, label, async () => {
      await api(route + path, "POST");
      await refresh();
    }, onError);
    if (job.status === "proposed") {
      decide("/approve", "この内容で開発を依頼する");
      decide("/cancel", "キャンセル");
    } else if (active.has(job.status) || job.status === "waiting_approval") {
      decide("/cancel", job.cancel_requested ? "取消要求済み" : "ジョブを止める").disabled = Boolean(job.cancel_requested);
    }
    if (job.status === "ready_for_review" && !compact) decide("/complete", "レビュー完了");
    if (compact) {
      const link = append(box, "a", "Developで開発ジョブを確認");
      link.href = "/static/universe.html?view=development";
    } else {
      const testLabel = { not_run: "未実施", passed: "成功", failed: "失敗" };
      append(box, "p", "コマンド検証 " + (testLabel[job.tests] || "不明") + " / 実アプリ動作 未確認");
      if (job.workspace) {
        button(actions, "変更ファイル・差分を見る", async () => {
          const result = await api(route + "/diff");
          const preview = box.querySelector(".diff") || append(box, "pre", "");
          preview.className = "diff";
          preview.textContent = result.files.join("\n") + "\n\n" + result.diff +
            (result.truncated ? "\n（表示上限で省略）" : "");
        }, onError);
      }
      const details = append(box, "details", "");
      append(details, "summary", "進捗・チェック結果");
      append(details, "pre", job.events.map((event) =>
        [event.created_at, event.kind, event.detail].filter(Boolean).join(" ")).join("\n") +
        "\n" + JSON.stringify(job.checks, null, 2));
    }
    for (const item of job.actions || []) {
      const panel = append(box, "section", "");
      panel.className = "development-action";
      const params = item.parameters;
      append(panel, "h4", "PC操作の確認 · " + operations[item.operation]);
      append(panel, "pre", JSON.stringify({
        対象: params.path, 移動先: params.destination, 作業ファイル: params.source, コマンド: params.argv,
      }, null, 2));
      if (item.status === "proposed" && job.status === "waiting_approval") {
        if (item.operation === "write") {
          button(panel, "書き込み内容を見る", async () => {
            const result = await api(route + "/actions/" + item.id + "/preview");
            const preview = panel.querySelector(".diff") || append(panel, "pre", "");
            preview.className = "diff";
            preview.textContent = result.preview;
          }, onError);
        }
        decide("/actions/" + item.id + "/approve", "このPC操作を許可する", panel);
        decide("/actions/" + item.id + "/reject", "拒否する", panel);
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
  let threadLoading = false;

  function moveComposer(slot, repo = "") {
    slot.append(composer);
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

  function threadCard(parent, data) {
    const latest = data.latest_job;
    const control = append(parent, "button", "");
    control.type = "button";
    control.className = "development-thread-card";
    append(control, "strong", data.title || "名称未設定の開発チャット");
    const meta = append(control, "span", [
      latest?.provider || "CLI未選択",
      statusLabel(latest?.status),
      timestamp(latest?.updated_at || data.created_at),
    ].join(" · "));
    meta.className = "development-muted";
    const preview = append(control, "span", shorten(latest?.latest_message || "まだ開発依頼はありません。"));
    preview.className = "development-thread-preview";
    control.addEventListener("click", () => void openThread(data.thread_id));
  }

  async function loadThreads(repository, target) {
    const response = await api("/threads?repository=" + encodeURIComponent(repository));
    if (!target.isConnected) return;
    target.replaceChildren();
    if (!response.threads.length) {
      empty(target, "開発チャットはまだありません。上の入力欄から始められます。");
      return;
    }
    for (const item of response.threads) threadCard(target, item);
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
        await loadThreads("", $("development-loose-threads"));
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

  function renderJobHistory(items) {
    const list = $("development-thread-history");
    list.replaceChildren();
    if (!items.length) {
      empty(list, "まだ開発依頼がありません。");
      return;
    }
    for (const job of items) {
      const entry = append(list, "article", "");
      entry.className = "development-thread-turn";
      append(entry, "p", job.goal).className = "development-thread-user";
      const reply = append(entry, "div", "");
      reply.className = "development-thread-reply";
      append(reply, "strong", [job.provider || "CLI", statusLabel(job.status)].join(" · "));
      append(reply, "p", job.summary || (job.error ? "エラー: " + job.error : "CLIの結果を確認中です。"));
      append(reply, "small", timestamp(job.updated_at)).className = "development-muted";
      const detail = append(entry, "details", "");
      append(detail, "summary", "ジョブの詳細・差分・承認");
      const area = append(detail, "div", "");
      card(area, job, () => openThread(currentThread.thread_id), false);
    }
  }

  async function openThread(id) {
    if (threadLoading) return;
    threadLoading = true;
    try {
      const data = await api("/threads/" + encodeURIComponent(id));
      currentThread = data;
      currentRepo = data.repository;
      show("thread");
      $("development-thread-title").textContent = data.title || "開発チャット";
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
    } catch (error) { report(error.message); }
    finally { threadLoading = false; }
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
    const input = Object.fromEntries(new FormData(form));
    input.repository = currentView === "home" ? input.repository : currentRepo;
    requestId ||= crypto.randomUUID();
    try {
      if (!currentThread) {
        newThreadId ||= crypto.randomUUID().replace(/-/g, "");
        currentThread = await api("/threads", "POST", {
          thread_id: newThreadId, repository: input.repository, title: input.goal.slice(0, 120),
        });
      }
      const job = await api("/jobs/start", "POST", {
        ...input, thread_id: currentThread.thread_id, request_id: requestId,
        lightweight: input.lightweight === "on",
      });
      requestId = undefined;
      newThreadId = undefined;
      if (form.elements.goal.value === input.goal) form.elements.goal.value = "";
      report("開発を受け付けました: " + statusLabel(job.status));
      await openThread(currentThread.thread_id);
      void refreshWorkspace();
    } catch (error) { report(error.message); }
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
  $("development-back-home").addEventListener("click", () => {
    currentRepo = ""; currentThread = null; newThreadId = undefined;
    show("home"); void refreshWorkspace();
  });
  $("development-back-thread").addEventListener("click", () => {
    const repo = currentThread?.repository || "";
    currentThread = null; newThreadId = undefined;
    if (repo) void openRepository(repo);
    else { currentRepo = ""; show("home"); void refreshWorkspace(); }
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
  const refresh = () => {
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
    if (event.detail?.area === "development") refresh();
  });
  setInterval(() => {
    if (document.hidden || panel.hidden) return;
    void refreshWorkspace();
    if (currentView === "thread" && currentThread) void openThread(currentThread.thread_id);
    void refreshJobs();
    void refreshUsage();
  }, 12000);
  show("home");
  if (!panel.hidden) refresh();
})();
