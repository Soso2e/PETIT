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
    let timer;
    let signature;
    async function refresh() {
      clearTimeout(timer);
      try {
        const job = await api(route);
        if (!box.isConnected) return;
        const next = JSON.stringify(job);
        if (signature !== next) {
          signature = next;
          card(box, job, refresh, true);
        }
        if (active.has(job.status) || ["proposed", "waiting_approval"].includes(job.status)) {
          timer = setTimeout(refresh, document.hidden ? 15000 : 3000);
        }
        const list = $("development-jobs");
        if (list && !list.closest("[hidden]")) void refreshJobs();
      } catch (error) {
        box.textContent = error.message;
      }
    }
    void refresh();
  }

  window.PetitDevelopment = { attachProposal };
  const form = $("development-request");
  if (!form) return;
  const folders = $("development-roots");
  const jobs = $("development-jobs");
  const notice = $("development-job-notice");
  const panel = form.closest("[data-view-panel]");
  const report = (message) => { notice.textContent = message; };
  let requestId;
  let updatingJobs = false;
  let updatingUsage = false;
  let lastUsage = 0;
  let repositories = [];

  async function refreshJobs() {
    if (!jobs || updatingJobs) return;
    updatingJobs = true;
    try {
      const result = await api("/jobs");
      for (const [id, element] of mounted) {
        if (!result.jobs.some((job) => job.id === id)) {
          element.remove();
          mounted.delete(id);
        }
      }
      if (!result.jobs.length) {
        jobs.textContent = "開発の依頼はまだありません。";
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
    if (updatingUsage || Date.now() - lastUsage < 60000) return;
    updatingUsage = true;
    try {
      const result = await api("/usage");
      $("development-usage").textContent = Object.values(result.models).map((item) =>
        item.label + " " + quotaText(item) + (item.available ? "" : " · 利用可否を確認")).join(" ｜ ");
      lastUsage = Date.now();
    } catch (error) { report(error.message); }
    finally { updatingUsage = false; }
  }

  function renderConfig(data) {
    repositories = data.repositories;
    const select = form.elements.repository;
    const selected = select.value;
    select.replaceChildren(new Option("指定なし（PC内の全ファイルを見る）", ""));
    for (const root of repositories.filter((item) => !item.error)) {
      select.add(new Option(root.path + (root.mode === "git" ? "（Git）" : "（フォルダ）"), root.path));
    }
    if (repositories.some((root) => !root.error && root.path === selected)) select.value = selected;
    const model = form.elements.model_key;
    const modelValue = model.value;
    model.replaceChildren(new Option("自動（残量優先）", "auto"), ...data.models.map((item) => new Option(item.label, item.key)));
    model.value = modelValue || "auto";
    const list = $("development-root-list");
    list.replaceChildren();
    for (const root of repositories) {
      const row = append(list, "li", root.path + (root.error ? " · " + root.error : ""));
      if (root.source === "environment") append(row, "small", " サーバー設定");
      else button(row, "登録を外す", async () => {
        await api("/config/root", "DELETE", { path: root.path }).then(renderConfig);
        report("フォルダの登録を外しました。");
        void window.PetitDevelopmentHub?.reload();
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
    requestId ||= crypto.randomUUID();
    try {
      await api("/jobs/start", "POST", { ...input, request_id: requestId, lightweight: input.lightweight === "on" });
      requestId = undefined;
      if (form.elements.goal.value === input.goal) form.elements.goal.value = "";
      report("開発ジョブを受け付けました。");
      await refreshJobs();
    } catch (error) { report(error.message); }
    finally { submit.disabled = false; }
  });
  folders.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      renderConfig(await api("/config/root", "POST", { path: folders.elements.path.value.trim() }));
      folders.reset();
      report("フォルダを登録しました。");
      void window.PetitDevelopmentHub?.reload();
    } catch (error) { report(error.message); }
  });
  const refresh = () => { void refreshConfig(); void refreshJobs(); void refreshUsage(); };
  $("development-refresh").addEventListener("click", () => { lastUsage = 0; refresh(); });
  window.addEventListener("petit:area-change", (event) => {
    if (event.detail?.area === "development") refresh();
  });
  setInterval(() => {
    if (!document.hidden && !panel.hidden) {
      void refreshJobs();
      void refreshUsage();
    }
  }, 3000);
  if (!panel.hidden) refresh();
})();
