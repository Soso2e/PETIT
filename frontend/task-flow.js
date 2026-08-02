// PETIT parent-task flow: keep hierarchy edits and child creation inside Focus.
(() => {
  const state = {
    tasks: [],
    selectedTaskId: null,
    loading: false,
  };

  const byId = (id) => document.getElementById(id);
  const text = (value) => String(value ?? "").trim();
  const taskId = (task) => String(task?.id || task?.external_id || "");
  const isRoot = (task) => task?.hierarchy_role === "root" || !task?.parent_task_id;
  const rootTitle = (task) => text(task?.root_title || task?.project_title || task?.title);

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  const showFeedback = (message) => {
    const feedback = byId("task-feedback");
    const copy = feedback?.querySelector("[data-feedback-copy]");
    const action = feedback?.querySelector("[data-feedback-action]");
    if (!feedback || !copy) return;
    copy.textContent = message;
    if (action) action.hidden = true;
    feedback.hidden = false;
    window.setTimeout(() => { feedback.hidden = true; }, 5200);
  };

  const loadCatalog = async () => {
    if (state.loading) return;
    state.loading = true;
    try {
      const sharedTasks = window.PetitUniverse?.tasks?.() || [];
      if (sharedTasks.length) {
        state.tasks = sharedTasks;
        decorateDetail();
        return;
      }
      const data = await requestJson("/api/notifications/tasks?priority=all&limit=500");
      state.tasks = Array.isArray(data.tasks) ? data.tasks : [];
      decorateDetail();
    } catch (error) {
      console.warn("PETIT task flow catalog load failed", error);
    } finally {
      state.loading = false;
    }
  };

  const findTask = ({ id = "", title = "", root = "" } = {}) => {
    if (id) {
      const exact = state.tasks.find((task) => taskId(task) === String(id));
      if (exact) return exact;
    }
    const matches = state.tasks.filter((task) => {
      if (title && text(task.title) !== title) return false;
      if (root && rootTitle(task) !== root) return false;
      return true;
    });
    return matches[0] || null;
  };

  const rememberTaskFromClick = (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const node = target.closest(".space-node[data-task-id]");
    if (node) {
      state.selectedTaskId = node.dataset.taskId || null;
      return;
    }
    const universeTask = target.closest(".universe-task");
    if (universeTask) {
      const task = findTask({ id: universeTask.dataset.taskId || "" }) || findTask({
        title: text(universeTask.querySelector(".universe-task__title")?.textContent),
        root: text(universeTask.closest(".constellation-card")?.querySelector(".constellation-card__heading strong")?.textContent),
      });
      state.selectedTaskId = task ? taskId(task) : null;
      return;
    }
    const row = target.closest("#task-table-body tr");
    if (row) {
      const task = findTask({ title: text(row.querySelector(".task-table__title")?.textContent) });
      state.selectedTaskId = task ? taskId(task) : null;
    }
  };

  const currentDetailTask = () => {
    const displayedId = byId("detail-panel")?.dataset.taskId || "";
    const displayed = findTask({ id: displayedId });
    if (displayed) {
      state.selectedTaskId = taskId(displayed);
      return displayed;
    }
    const remembered = findTask({ id: state.selectedTaskId || "" });
    if (remembered) return remembered;
    const title = text(byId("detail-panel")?.querySelector('[data-detail="title"]')?.textContent);
    const task = findTask({ title });
    if (task) state.selectedTaskId = taskId(task);
    return task;
  };

  const activateView = (view) => {
    if (window.PetitAppShell?.activateView) {
      window.PetitAppShell.activateView(view);
      return;
    }
    document.querySelector(`[data-view="${view}"]`)?.click();
  };

  const refreshAndFocusTask = async (id) => {
    if (window.PetitUniverse?.refreshAndFocusTask) {
      const focused = await window.PetitUniverse.refreshAndFocusTask(id);
      state.tasks = window.PetitUniverse.tasks?.() || state.tasks;
      state.selectedTaskId = String(id || "") || null;
      return focused;
    }
    await loadCatalog();
    activateView("focus");
    return false;
  };

  const changeParent = async (task, select, applyButton) => {
    const help = select.closest(".detail-parent-field")?.querySelector("[data-parent-help]");
    const parentId = text(select.value);
    const moveToLife = !parentId;
    const parent = moveToLife ? null : findTask({ id: parentId });
    if (!moveToLife && !parent) return;
    if (parentId === text(task.parent_task_id)) {
      applyButton.disabled = true;
      if (help) help.textContent = "現在の親Taskから変更はありません。";
      return;
    }

    select.disabled = true;
    applyButton.disabled = true;
    applyButton.dataset.busy = "true";
    applyButton.textContent = "適用中…";
    if (help) help.textContent = moveToLife
      ? "Life直下へ戻しています…"
      : `「${parent.title}」へ移動しています…`;
    try {
      const data = await requestJson(`/api/notifications/tasks/${encodeURIComponent(taskId(task))}/parent`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(moveToLife
          ? { move_to_life: true }
          : { parent_task_id: Number(parent.id) }),
      });
      const destination = data.parent?.title || text(task.title);
      showFeedback(moveToLife
        ? `「${text(task.title)}」をLife直下へ戻し、そのTaskへ移動しました。`
        : `「${text(task.title)}」を「${destination}」の子タスクにし、親Taskへ移動しました。`);
      await refreshAndFocusTask(taskId(task));
    } catch (error) {
      if (help) help.textContent = error.message;
      showFeedback(`親子関係を変更できませんでした: ${error.message}`);
      select.disabled = false;
      select.value = String(task.parent_task_id || "");
    } finally {
      applyButton.dataset.busy = "false";
      applyButton.textContent = "親Taskを変更";
      if (document.contains(applyButton)) {
        select.disabled = Boolean(task.has_children);
        applyButton.disabled = true;
      }
    }
  };

  const handleParentSelection = (event) => {
    const select = event.target instanceof Element
      ? event.target.closest('[data-action="parent"]')
      : null;
    if (!(select instanceof HTMLSelectElement)) return;
    const task = currentDetailTask();
    if (!task) return;
    event.stopImmediatePropagation();
    const field = select.closest(".detail-parent-field");
    const applyButton = field?.querySelector('[data-action="parent-apply"]');
    const help = field?.querySelector("[data-parent-help]");
    if (!(applyButton instanceof HTMLButtonElement)) return;
    const changed = text(select.value) !== text(task.parent_task_id);
    applyButton.disabled = !changed;
    if (help) {
      const parent = findTask({ id: text(select.value) });
      help.textContent = changed
        ? (parent ? `「${text(parent.title)}」の子タスクに変更します。まだ保存されていません。` : "Life直下へ戻します。まだ保存されていません。")
        : "現在の親Taskから変更はありません。";
    }
  };

  const handleParentApply = (event) => {
    const applyButton = event.target instanceof Element
      ? event.target.closest('[data-action="parent-apply"]')
      : null;
    if (!(applyButton instanceof HTMLButtonElement) || applyButton.disabled) return;
    const select = applyButton.closest(".detail-parent-field")?.querySelector('[data-action="parent"]');
    const task = currentDetailTask();
    if (!(select instanceof HTMLSelectElement) || !task) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    void changeParent(task, select, applyButton);
  };

  const createChildComposer = (task) => {
    const section = document.createElement("section");
    section.className = "detail-child-create";
    section.dataset.parentTaskId = taskId(task);
    section.innerHTML = `
      <div class="detail-child-create__head">
        <div><span class="eyebrow">CHILD TASK</span><strong>この親Taskに小タスクを追加</strong></div>
        <small>追加後も、この親TaskのFocusに留まります。</small>
      </div>
      <form data-child-form>
        <div class="detail-child-create__fields">
          <input name="title" type="text" maxlength="200" autocomplete="off" placeholder="小タスク名" aria-label="小タスク名" required />
          <select name="priority" aria-label="優先度">
            <option value="High">High</option>
            <option value="Mid">Mid</option>
            <option value="Low">Low</option>
          </select>
        </div>
        <button type="submit">追加してFocusに表示</button>
      </form>
      <div class="detail-child-create__status" data-child-status>親Taskを分けずに、ここへ実行単位を追加できます。</div>
    `;
    return section;
  };

  const submitChild = async (form, task) => {
    const input = form.querySelector('input[name="title"]');
    const priority = form.querySelector('select[name="priority"]');
    const button = form.querySelector('button[type="submit"]');
    const status = form.closest(".detail-child-create")?.querySelector("[data-child-status]");
    const title = text(input?.value);
    if (!title) return;

    if (button) button.disabled = true;
    if (input) input.disabled = true;
    if (priority) priority.disabled = true;
    if (status) status.textContent = "小タスクを追加しています…";
    try {
      const data = await requestJson(`/api/notifications/tasks/${encodeURIComponent(taskId(task))}/children`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          priority: text(priority?.value) || "High",
        }),
      });
      if (input) input.value = "";
      const childId = taskId(data.task);
      state.selectedTaskId = childId || state.selectedTaskId;
      showFeedback(`「${title}」を「${text(task.title)}」の小タスクとして追加しました。`);
      await refreshAndFocusTask(childId);
    } catch (error) {
      if (status) status.textContent = error.message;
      showFeedback(`小タスクを追加できませんでした: ${error.message}`);
    } finally {
      if (button) button.disabled = false;
      if (input) input.disabled = false;
      if (priority) priority.disabled = false;
    }
  };

  const decorateDetail = () => {
    const detail = byId("detail-panel")?.querySelector(".detail-panel__content");
    if (!detail) return;
    const task = currentDetailTask();
    const existing = detail.querySelector(".detail-child-create");
    if (!task || !isRoot(task)) {
      existing?.remove();
      return;
    }
    if (existing?.dataset.parentTaskId === taskId(task)) return;
    existing?.remove();
    const composer = createChildComposer(task);
    const primaryActions = detail.querySelector(".detail-actions--primary");
    detail.insertBefore(composer, primaryActions || null);
    composer.querySelector("[data-child-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      void submitChild(event.currentTarget, task);
    });
  };

  const initialize = () => {
    document.addEventListener("click", rememberTaskFromClick, true);
    document.addEventListener("click", handleParentApply, true);
    document.addEventListener("change", handleParentSelection, true);
    document.addEventListener("petit:tasks-updated", (event) => {
      const tasks = event.detail?.tasks;
      if (!Array.isArray(tasks)) return;
      state.tasks = tasks;
      queueMicrotask(decorateDetail);
    });
    const detailPanel = byId("detail-panel");
    if (detailPanel) {
      new MutationObserver(() => queueMicrotask(decorateDetail)).observe(detailPanel, {
        childList: true,
        subtree: true,
      });
    }
    void loadCatalog();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
