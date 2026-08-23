// PETIT Notion task sync recovery UI.
// Kept separate from universe-app.js so task sync recovery does not interfere with work-session state handling.
(() => {
  const byId = (id) => document.getElementById(id);
  const taskKey = (task, index = 0) => String(task?.id || task?.external_id || task?.url || `task-${index}`);
  const taskNumericId = (task) => /^\d+$/.test(String(task?.id || "")) ? Number(task.id) : null;
  const priorityOf = (task) => String(task?.priority || "").trim().toLowerCase();
  const isDone = (task) => ["done", "canceled", "cancelled", "chancel", "完了"].includes(String(task?.status || "Ready").trim().toLowerCase());
  const syncClass = (task) => {
    const value = String(task?.sync_status || "synced").toLowerCase();
    return ["pending", "synced", "failed", "conflict"].includes(value) ? value : "synced";
  };
  const priorityRank = (task) => {
    const priority = priorityOf(task);
    if (priority === "high") return 0;
    if (["mid", "medium"].includes(priority)) return 1;
    if (priority === "low") return 2;
    return 3;
  };

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  let feedbackTimer = null;
  const showFeedback = (message) => {
    const feedback = byId("task-feedback");
    const copy = feedback?.querySelector("[data-feedback-copy]");
    if (!feedback || !copy) return;
    if (feedbackTimer) window.clearTimeout(feedbackTimer);
    copy.textContent = message;
    feedback.hidden = false;
    feedbackTimer = window.setTimeout(() => { feedback.hidden = true; }, 4200);
  };

  const refreshUniverse = () => byId("refresh-universe")?.click();

  const ensureRefreshButton = () => {
    const existing = byId("refresh-tasks");
    if (existing) return existing;
    const wrap = document.querySelector(".task-filter-wrap");
    if (!wrap) return null;
    const button = document.createElement("button");
    button.id = "refresh-tasks";
    button.className = "reminder-refresh";
    button.type = "button";
    button.setAttribute("aria-label", "Notionタスクを更新");
    button.textContent = "Notion同期";
    wrap.appendChild(button);
    return button;
  };

  const retryTask = async (task, button) => {
    const id = taskNumericId(task);
    if (id == null) return;
    button.disabled = true;
    try {
      await requestJson(`/api/notifications/tasks/${encodeURIComponent(id)}/sync/retry`, { method: "POST" });
      showFeedback("同期を再試行キューへ戻しました。");
      refreshUniverse();
    } catch (error) {
      showFeedback(`同期を再試行できませんでした: ${error.message}`);
      button.disabled = false;
    }
  };

  const visibleTasks = () => {
    const filter = document.querySelector("[data-filter].is-active")?.dataset.filter === "low" ? "low" : "high";
    return (window.PetitUniverse?.tasks?.() || [])
      .filter((task) => !isDone(task) && priorityOf(task) === filter)
      .sort((left, right) => {
        const priority = priorityRank(left) - priorityRank(right);
        if (priority) return priority;
        return String(left.due_date || "9999-12-31").localeCompare(String(right.due_date || "9999-12-31"), "ja");
      });
  };

  const syncRecoveryControl = (task, sync, location) => {
    if (!task || !["failed", "conflict"].includes(sync)) return null;
    if (sync === "conflict") {
      if (location === "table") {
        const hint = document.createElement("small");
        hint.className = "task-sync-hint";
        hint.textContent = "再編集";
        hint.dataset.taskSyncRecovery = "conflict";
        return hint;
      }
      const action = document.createElement("button");
      action.type = "button";
      action.className = "detail-sync-action";
      action.textContent = "競合を確認して再編集";
      action.title = "Notion側の変更を確認してから編集すると競合を解消できます";
      action.dataset.taskSyncRecovery = "conflict";
      action.addEventListener("click", () => {
        showFeedback("Notion側の変更を確認し、編集して保存すると競合を解消できます。");
      });
      return action;
    }

    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = location === "table" ? "task-sync-retry" : "detail-sync-action";
    retry.textContent = location === "table" ? "再試行" : "同期を再試行";
    retry.title = "失敗したNotion書き込みをキューへ戻します";
    retry.dataset.taskSyncRecovery = "failed";
    retry.setAttribute("aria-label", `${String(task.title || "タスク")}のNotion同期を再試行`);
    retry.addEventListener("click", (event) => {
      event.stopPropagation();
      void retryTask(task, retry);
    });
    return retry;
  };

  const enhanceTable = () => {
    const body = byId("task-table-body");
    if (!body) return;
    const tasks = visibleTasks();
    const rows = Array.from(body.querySelectorAll(":scope > tr"));
    rows.forEach((row, index) => {
      if (row.children.length < 5) return;
      const task = tasks[index];
      if (!task) return;
      const cell = row.children[4];
      const sync = syncClass(task);
      const existing = cell.querySelector("[data-task-sync-recovery]");
      if (existing?.dataset.taskSyncRecovery === sync) return;
      existing?.remove();
      const control = syncRecoveryControl(task, sync, "table");
      if (control) cell.appendChild(control);
    });
  };

  const enhanceDetail = () => {
    const panel = byId("detail-panel");
    const syncEl = panel?.querySelector('[data-detail="sync"]');
    const selectedKey = panel?.dataset.taskId;
    if (!panel || !syncEl || !selectedKey) return;
    const tasks = window.PetitUniverse?.tasks?.() || [];
    const index = tasks.findIndex((task, taskIndex) => taskKey(task, taskIndex) === selectedKey);
    const task = index >= 0 ? tasks[index] : null;
    if (!task) return;

    const sync = syncClass(task);
    const nextText = sync === "synced" ? "" : `同期状態: ${sync}${task.sync_error ? ` · ${task.sync_error}` : ""}`;
    if (syncEl.textContent !== nextText) syncEl.textContent = nextText;
    syncEl.hidden = sync === "synced";

    const existing = panel.querySelector("[data-task-sync-recovery]");
    if (existing?.dataset.taskSyncRecovery === sync) return;
    existing?.remove();
    const control = syncRecoveryControl(task, sync, "detail");
    if (control) syncEl.insertAdjacentElement("afterend", control);
  };

  let scheduled = false;
  const enhance = () => {
    scheduled = false;
    enhanceTable();
    enhanceDetail();
  };
  const scheduleEnhance = () => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(enhance);
  };

  const refreshTasksButton = ensureRefreshButton();
  refreshTasksButton?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
      const result = await requestJson("/api/notifications/tasks/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "incremental" }),
      });
      showFeedback(result.ok
        ? `Notionタスクを更新しました（${result.synced_count ?? 0}件）。`
        : `Notion同期を確認できませんでした: ${result.error || "失敗"}`);
      refreshUniverse();
    } catch (error) {
      showFeedback(`Notionタスクを更新できませんでした: ${error.message}`);
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  });

  document.addEventListener("petit:tasks-updated", scheduleEnhance);
  document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", scheduleEnhance));

  const observer = new MutationObserver(scheduleEnhance);
  const tableBody = byId("task-table-body");
  const detailPanel = byId("detail-panel");
  if (tableBody) observer.observe(tableBody, { childList: true, subtree: true });
  if (detailPanel) observer.observe(detailPanel, { childList: true, subtree: true });
  scheduleEnhance();
})();
