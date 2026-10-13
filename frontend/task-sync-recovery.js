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

  const openConflict = async (taskId = null) => {
    const previousFocus = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.className = "task-conflict-dialog";
    const heading = document.createElement("h2"); heading.textContent = "Notion同期競合を解消";
    const status = document.createElement("p"); status.setAttribute("role", "status");
    const content = document.createElement("div");
    const close = document.createElement("button"); close.type = "button"; close.textContent = "閉じる";
    close.onclick = () => dialog.close();
    dialog.append(heading, status, content, close); document.body.append(dialog);
    dialog.addEventListener("close", () => { dialog.remove(); previousFocus?.focus(); });
    dialog.showModal();
    const compare = async (id) => {
      status.textContent = "Notionの最新状態を取得中…"; content.replaceChildren();
      try {
        const data = await requestJson(`/api/notifications/tasks/${id}/sync/conflict`);
        if (!dialog.open) return;
        heading.textContent = `同期競合：${data.local.title || data.remote.title || "タスク"}`;
        status.textContent = "差分のある項目を表示しています。PETIT側は未同期の変更をNotionへ再送します。";
        const table = document.createElement("table");
        const labels = { title: "名前", status: "状態", due_date: "期限", priority: "優先度", area: "分野", reason: "メモ", done_date: "完了日", parent_external_ids: "親ページ", project_external_ids: "プロジェクト" };
        const row = (...values) => { const tr = document.createElement("tr"); for (const value of values) { const td = document.createElement("td"); td.textContent = value; tr.append(td); } return tr; };
        const header = document.createElement("tr");
        for (const label of ["項目", "PETIT", "Notion"]) { const th = document.createElement("th"); th.scope = "col"; th.textContent = label; header.append(th); }
        table.append(header);
        const display = (value) => Array.isArray(value) ? value.join(", ") || "なし" : value == null || value === "" ? "なし" : String(value);
        for (const key of Object.keys(labels)) {
          if (JSON.stringify(data.local[key] ?? null) === JSON.stringify(data.remote[key] ?? null)) continue;
          const tr = row(labels[key], display(data.local[key]), display(data.remote[key]));
          tr.classList.add("has-difference");
          if (key === "parent_external_ids" && data.parent_titles) {
            tr.children[1].textContent = display(data.parent_titles.local);
            tr.children[2].textContent = display(data.parent_titles.remote);
          }
          table.append(tr);
        }
        content.append(table);
        const consequence = document.createElement("p");
        consequence.className = "task-conflict-consequence";
        consequence.textContent = "PETIT側を残すと再同期を予約します。Notionへの反映は別途確認が必要です。Notion側を採用すると、このタスクの未同期の変更を取り下げます。";
        content.append(consequence);
        if (table.children.length === 1) status.textContent = "現在の値に差分はありません。未同期の変更を再送するか、Notion側を採用して取り下げるか選べます。";
        for (const [choice, label] of [["petit", "PETIT側を残して再同期"], ["notion", "Notion側を採用（未同期の変更を取り下げる）"]]) {
          const button = document.createElement("button"); button.type = "button"; button.textContent = label;
          button.onclick = async () => {
            for (const action of content.querySelectorAll("button")) action.disabled = true;
            status.textContent = "選択を反映中…";
            try {
              const result = await requestJson(`/api/notifications/tasks/${id}/sync/conflict`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ choice, revision: data.revision }) });
              status.textContent = result.message; content.replaceChildren(); refreshUniverse();
            } catch (error) {
              status.textContent = error.message;
              const reload = document.createElement("button"); reload.type = "button"; reload.textContent = "最新の差分を再確認"; reload.onclick = () => void compare(id); content.append(reload);
            }
          };
          content.append(button);
        }
      } catch (error) { status.textContent = error.message; }
    };
    if (taskId != null) { await compare(taskId); return; }
    status.textContent = "競合中のタスクを取得中…";
    try {
      const data = await requestJson("/api/notifications/tasks/sync/conflicts");
      if (!dialog.open) return;
      status.textContent = data.tasks.length ? "比較するタスクを選んでください。" : "同期競合はありません。";
      for (const task of data.tasks) {
        const button = document.createElement("button"); button.type = "button"; button.textContent = task.title;
        button.onclick = () => void compare(task.id); content.append(button);
      }
    } catch (error) { status.textContent = error.message; }
  };

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
        const hint = document.createElement("button");
        hint.type = "button";
        hint.className = "task-sync-hint";
        hint.textContent = "競合を解消";
        hint.addEventListener("click", (event) => { event.stopPropagation(); void openConflict(taskNumericId(task)); });
        hint.dataset.taskSyncRecovery = "conflict";
        return hint;
      }
      const action = document.createElement("button");
      action.type = "button";
      action.className = "detail-sync-action";
      action.textContent = "競合を比較して解消";
      action.title = "PETITとNotionの差分を比較して採用する側を選びます";
      action.dataset.taskSyncRecovery = "conflict";
      action.addEventListener("click", () => {
        void openConflict(taskNumericId(task));
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
  if (refreshTasksButton) {
    const button = document.createElement("button"); button.type = "button"; button.className = "reminder-refresh";
    button.textContent = "同期競合を確認"; button.onclick = () => void openConflict();
    refreshTasksButton.after(button);
  }
  document.addEventListener("click", (event) => {
    if (event.target.closest?.("#sync-pill, [data-rail-sync]") && event.target.textContent.includes("競合")) void openConflict();
  });
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
