// Activity: read-only projection of PETIT's existing SQLite jobs.
// Does not submit, retry, cancel or acknowledge any job.
(() => {
  "use strict";
  const summarize = (payload) => {
    const allowed = new Set(["queued", "running", "done", "failed"]);
    const jobs = (Array.isArray(payload?.jobs) ? payload.jobs : []).slice(0, 100).map((item) => ({
      id: Number.isSafeInteger(item?.id) ? item.id : 0,
      type: String(item?.type || "unknown").slice(0, 80),
      status: allowed.has(item?.status) ? item.status : "unknown",
      updatedAt: typeof item?.updated_at === "string" ? item.updated_at : null,
      createdAt: typeof item?.created_at === "string" ? item.created_at : null,
      delivered: Boolean(item?.delivered),
    }));
    return { jobs, counts: payload?.counts || {}, excludesCoding: payload?.coding_jobs_included === false };
  };
  const matchesJobId = (job, query) => !query || String(job.id) === query;
  window.PetitActivityJobs = { summarize, matchesJobId };
  const panel = document.querySelector('[data-view-panel="development"]');
  if (!panel) return;
  const section = document.createElement("section");
  section.className = "development-activity";
  section.setAttribute("aria-labelledby", "development-activity-title");
  const header = document.createElement("div");
  header.className = "development-activity__header";
  const title = document.createElement("h2");
  title.id = "development-activity-title";
  title.textContent = "Activity · バックグラウンド";
  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.textContent = "ジョブ状態を更新";
  const filter = document.createElement("select");
  filter.setAttribute("aria-label", "背景ジョブの状態で絞り込む");
  for (const [value, label] of [["all", "すべて"], ["active", "待機・実行中"], ["failed", "失敗"], ["done", "完了"]]) {
    filter.add(new Option(label, value));
  }
  const jobLookup = document.createElement("input");
  jobLookup.type = "search";
  jobLookup.inputMode = "numeric";
  jobLookup.placeholder = "ジョブIDで検索";
  jobLookup.setAttribute("aria-label", "背景ジョブの数値IDを検索");
  jobLookup.maxLength = 16;
  header.append(title, filter, jobLookup, refresh);
  const state = document.createElement("p");
  state.className = "development-state";
  state.setAttribute("role", "status");
  state.setAttribute("aria-live", "polite");
  state.textContent = "未取得";
  const list = document.createElement("ul");
  list.className = "development-activity__list";
  const note = document.createElement("p");
  note.className = "development-note";
  note.textContent = "既存SQLiteジョブの記録。実行中はDB上の状態で、プロセス稼働の保証ではありません。入力・結果本文は表示しません。Coding Jobsは下の別一覧に表示します。";
  section.append(header, state, list, note);
  const firstNote = panel.querySelector(".development-note");
  if (firstNote) firstNote.before(section);
  else panel.append(section);

  const statuses = {
    queued: "実行待ち",
    running: "実行中（DB記録）",
    done: "完了",
    failed: "失敗",
    unknown: "状態不明",
  };
  const kinds = {
    durable_read: "永続Read調査",
    background_research: "情報調査",
    agent_followup: "AIフォローアップ",
  };
  const dateLabel = (value) => {
    const time = Date.parse(value || "");
    return Number.isFinite(time) ? new Date(time).toLocaleString("ja-JP") : "時刻未確認";
  };
  let lastPayload = null;
  const render = (payload) => {
    lastPayload = payload;
    const data = summarize(payload);
    const query = jobLookup.value.trim();
    const visible = data.jobs.filter((job) => matchesJobId(job, query) && (filter.value === "all"
      || (filter.value === "active" && (job.status === "queued" || job.status === "running"))
      || job.status === filter.value));
    list.replaceChildren();
    if (!visible.length) {
      const item = document.createElement("li");
      item.className = "development-activity__empty";
      item.textContent = data.jobs.length ? "該当するジョブはありません（取得済みの最近30件が検索対象です）。" : "最近のバックグラウンドジョブはありません。";
      list.append(item);
      state.textContent = data.jobs.length ? "表示 0件 / 最近 " + data.jobs.length + "件" : "0件";
      return;
    }
    for (const job of visible) {
      const item = document.createElement("li");
      item.className = "development-activity__item";
      const main = document.createElement("div");
      const heading = document.createElement("strong");
      heading.textContent = (kinds[job.type] || job.type) + " · #" + job.id;
      const sub = document.createElement("span");
      sub.textContent = "更新 " + dateLabel(job.updatedAt || job.createdAt)
        + (job.delivered ? " · 結果確認済" : "");
      main.append(heading, sub);
      const badge = document.createElement("span");
      badge.className = "development-activity__status";
      badge.dataset.status = job.status;
      badge.textContent = statuses[job.status] || statuses.unknown;
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "development-activity__copy";
      copy.textContent = "IDをコピー";
      copy.setAttribute("aria-label", "ジョブ " + job.id + " のIDをコピー");
      copy.disabled = !job.id;
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(String(job.id));
          copy.textContent = "コピー済み";
        } catch (_) {
          copy.textContent = "コピー失敗";
        }
      });
      item.append(main, badge, copy);
      list.append(item);
    }
    const n = data.jobs.length;
    const active = data.jobs.filter((j) => j.status === "queued" || j.status === "running").length;
    state.textContent = "表示 " + visible.length + "件 / 最近 " + n + "件 · 待機/実行中 " + active + "件"
      + (data.excludesCoding ? " · Coding Jobsは別一覧" : "");
  };

  let loading = false;
  let loadedAt = 0;
  let lastSuccessfulUpdate = null;
  const freshness = document.createElement("p");
  freshness.className = "development-note";
  freshness.setAttribute("aria-live", "polite");
  freshness.textContent = "最終取得: 未取得";
  state.after(freshness);
  const showFreshness = (failed = false) => {
    freshness.textContent = lastSuccessfulUpdate
      ? "最終取得: " + lastSuccessfulUpdate.toLocaleString("ja-JP") + (failed ? " · 最新状態を取得できませんでした" : "")
      : "最終取得: 未取得" + (failed ? " · 取得失敗" : "");
  };
  const load = async (force = false) => {
    if (loading || (!force && Date.now() - loadedAt < 30000)) return;
    loading = true;
    refresh.disabled = true;
    state.textContent = "状態を更新中…";
    try {
      const response = await fetch("/api/activity/jobs?limit=30", {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error(response.status === 401
        ? "管理者ログインが必要です。" : "Activity取得失敗（HTTP " + response.status + "）");
      render(await response.json());
      loadedAt = Date.now();
      lastSuccessfulUpdate = new Date(loadedAt);
      showFreshness();
    } catch (error) {
      state.textContent = error.message || "Activityを取得できません。";
      showFreshness(true);
    } finally {
      refresh.disabled = false;
      loading = false;
    }
  };

  // Refresh persisted progress only while the Development panel is visible.
  // Never claim that a running DB record proves the worker is alive.
  const poll = () => {
    if (document.visibilityState === "visible" && !panel.hidden) void load(true);
  };
  window.setInterval(poll, 30000);
  document.addEventListener("visibilitychange", poll);
  refresh.addEventListener("click", () => void load(true));
  filter.addEventListener("change", () => { if (lastPayload) render(lastPayload); });
  jobLookup.addEventListener("input", () => { if (lastPayload) render(lastPayload); });
  window.addEventListener("petit:area-change", (event) => {
    if (event.detail?.area === "development") void load();
  });
  window.PetitActivityJobs.reload = () => load(true);
  if (!panel.hidden) void load();
})();
