// Unified Development Hub: the Coding Job status projection.
// An Activity entry is a persisted record, not a verified live process.
(() => {
  "use strict";

  const summarize = (payload) => {
    const statuses = new Set([
      "proposed", "queued", "running", "ready_for_review", "checks_failed",
      "completed", "failed", "cancelled", "interrupted",
    ]);
    return {
      initialized: payload?.initialized === true,
      jobs: (Array.isArray(payload?.jobs) ? payload.jobs : []).slice(0, 100).map((row) => ({
        id: String(row?.id || "").slice(0, 64),
        taskId: Number.isSafeInteger(row?.task_id) ? row.task_id : null,
        status: statuses.has(row?.status) ? row.status : "unknown",
        provider: row?.provider === "codex" ? "Codex" : row?.provider === "antigravity_cli" ? "Antigravity CLI" : "不明",
        updatedAt: typeof row?.updated_at === "string" ? row.updated_at : null,
      })),
    };
  };
  window.PetitCodingActivity = { summarize };

  const panel = document.querySelector('[data-view-panel="development"]');
  if (!panel) return;
  const section = document.createElement("section");
  section.className = "development-activity";
  section.setAttribute("aria-labelledby", "development-coding-title");
  const header = document.createElement("div");
  header.className = "development-activity__header";
  const title = document.createElement("h2");
  title.textContent = "Coding Jobs · 開発エージェント";
  title.id = "development-coding-title";
  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.textContent = "開発ジョブを更新";
  header.append(title, refresh);
  const state = document.createElement("p");
  state.className = "development-state";
  state.setAttribute("role", "status");
  state.setAttribute("aria-live", "polite");
  state.textContent = "未取得";
  const list = document.createElement("ul");
  list.className = "development-activity__list";
  const link = document.createElement("a");
  link.href = "/static/development.html";
  link.textContent = "開発タスクの詳細・承認・差分を開く";
  link.className = "development-activity__link";
  const note = document.createElement("p");
  note.className = "development-note";
  note.textContent = "Coding Jobの保存済み状態を表示します。目的・パス・生成コードはActivityに含めません。実行中はプロセス生存の保証ではありません。";
  section.append(header, state, list, link, note);
  const original = panel.querySelector(".development-activity");
  if (original) original.after(section);
  else panel.append(section);

  const labels = {
    proposed: "確認待ち",
    queued: "実行待ち",
    running: "実行中（DB記録）",
    ready_for_review: "差分レビュー待ち",
    checks_failed: "静的チェック失敗",
    completed: "レビュー完了",
    failed: "失敗",
    cancelled: "取消済み",
    interrupted: "中断",
    unknown: "未確認",
  };
  const timeLabel = (value) => {
    const timestamp = Date.parse(value || "");
    return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString("ja-JP") : "時刻未確認";
  };
  const render = (raw) => {
    const data = summarize(raw);
    list.replaceChildren();
    if (!data.jobs.length) {
      const item = document.createElement("li");
      item.className = "development-activity__empty";
      item.textContent = data.initialized ? "開発エージェントの依頼履歴はまだありません。" :
        "Coding Jobはまだ初期化されていません。開発タスク画面から設定できます。";
      list.append(item);
      state.textContent = data.initialized ? "0件" : "未初期化";
      return;
    }
    for (const job of data.jobs) {
      const item = document.createElement("li");
      item.className = "development-activity__item";
      const meta = document.createElement("div");
      const heading = document.createElement("strong");
      heading.textContent = job.provider + " · " + job.id.slice(0, 8);
      const updated = document.createElement("span");
      updated.textContent = (job.taskId ? "Task #" + job.taskId + " · " : "") + "更新 " + timeLabel(job.updatedAt);
      meta.append(heading, updated);
      const badge = document.createElement("span");
      badge.className = "development-activity__status";
      badge.dataset.status = job.status;
      badge.textContent = labels[job.status];
      item.append(meta, badge);
      list.append(item);
    }
    const active = data.jobs.filter((job) => ["proposed", "queued", "running", "ready_for_review"].includes(job.status)).length;
    state.textContent = "最近 " + data.jobs.length + "件 · 進行・確認待ち " + active + "件";
  };
  let loading = false;
  let refreshedAt = 0;
  const load = async (force = false) => {
    if (loading || (!force && Date.now() - refreshedAt < 30000)) return;
    loading = true;
    refresh.disabled = true;
    state.textContent = "開発ジョブを取得中…";
    try {
      const response = await fetch("/api/coding/activity?limit=30", {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error(response.status === 401
        ? "管理者ログインが必要です。" : "Coding Job取得失敗（HTTP " + response.status + "）");
      render(await response.json());
      refreshedAt = Date.now();
    } catch (error) {
      state.textContent = error.message || "Coding Jobを取得できません。";
    } finally {
      refresh.disabled = false;
      loading = false;
    }
  };
  refresh.addEventListener("click", () => void load(true));
  window.addEventListener("petit:area-change", (event) => {
    if (event.detail?.area === "development") void load();
  });
  window.PetitCodingActivity.reload = () => load(true);
  if (!panel.hidden) void load();
})();
