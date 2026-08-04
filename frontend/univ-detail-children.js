// PETIT Univ detail: append the selected parent task's child tasks to the existing detail panel.
(() => {
  if (window.PetitUnivDetailChildren?.initialized) return;

  const TASKS_URL = "/api/notifications/tasks?priority=all&limit=500";
  let tasks = [];
  let loading = null;
  let rendering = false;

  const panel = () => document.querySelector("#detail-panel");
  const taskIdOf = (task, index = 0) => String(task?.id || task?.external_id || task?.url || `task-${index}`);
  const normalize = (value) => String(value ?? "").trim();

  const loadTasks = async ({ force = false } = {}) => {
    if (tasks.length && !force) return tasks;
    if (loading) return loading;
    loading = fetch(TASKS_URL, { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
        return tasks;
      })
      .catch(() => tasks)
      .finally(() => { loading = null; });
    return loading;
  };

  const selectedTask = (selectedId) => tasks.find((task, index) => taskIdOf(task, index) === selectedId) || null;

  const childTasksOf = (parent) => {
    if (!parent) return [];
    const parentId = normalize(parent.id);
    const parentExternalId = normalize(parent.external_id);
    const parentKey = taskIdOf(parent, tasks.indexOf(parent));
    return tasks.filter((task, index) => {
      if (taskIdOf(task, index) === parentKey) return false;
      const directIdMatch = parentId && normalize(task.parent_task_id) === parentId;
      const externalMatch = parentExternalId && normalize(task.parent_external_id) === parentExternalId;
      const rootMatch = normalize(task.root_task_id) === parentKey && normalize(task.hierarchy_role) === "child";
      return directIdMatch || externalMatch || rootMatch;
    });
  };

  const priorityLabel = (task) => {
    const value = normalize(task.priority).toLowerCase();
    if (value === "high") return "High";
    if (["mid", "medium"].includes(value)) return "Mid";
    if (value === "low") return "Low";
    return "未設定";
  };

  const focusChild = (task, index) => {
    const id = taskIdOf(task, index);
    const target = document.querySelector(`#constellation-grid [data-task-id="${CSS.escape(id)}"]`);
    if (target instanceof HTMLElement) {
      target.click();
      return;
    }
    window.PetitUnivSpace?.focusTask?.(id);
  };

  const buildSection = (children) => {
    const section = document.createElement("section");
    section.className = "detail-children";
    section.dataset.univDetailChildren = "true";

    const heading = document.createElement("div");
    heading.className = "detail-children__heading";
    const label = document.createElement("span");
    label.textContent = "CHILD TASKS";
    const count = document.createElement("strong");
    count.textContent = `${children.length}件`;
    heading.append(label, count);
    section.appendChild(heading);

    const list = document.createElement("div");
    list.className = "detail-children__list";
    children.forEach((task) => {
      const index = tasks.indexOf(task);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "detail-children__item";
      button.dataset.taskId = taskIdOf(task, index);

      const title = document.createElement("span");
      title.textContent = normalize(task.title) || "名称未設定";
      const meta = document.createElement("small");
      meta.textContent = `${priorityLabel(task)} · ${normalize(task.due_date) || "期限なし"}`;
      button.append(title, meta);
      button.addEventListener("click", () => focusChild(task, index));
      list.appendChild(button);
    });
    section.appendChild(list);
    return section;
  };

  const ensureStyles = () => {
    if (document.querySelector("style[data-univ-detail-children-style]")) return;
    const style = document.createElement("style");
    style.dataset.univDetailChildrenStyle = "true";
    style.textContent = `
      .detail-children { margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(157,180,255,.16); }
      .detail-children__heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }
      .detail-children__heading span { color:rgba(205,217,255,.58); font:500 9px/1 "DM Mono",monospace; letter-spacing:.14em; }
      .detail-children__heading strong { color:rgba(235,240,255,.78); font-size:11px; }
      .detail-children__list { display:grid; gap:8px; }
      .detail-children__item { width:100%; display:grid; gap:3px; padding:10px 12px; border:1px solid rgba(157,180,255,.15); border-radius:13px; color:inherit; text-align:left; background:rgba(12,18,42,.62); cursor:pointer; }
      .detail-children__item:hover,.detail-children__item:focus-visible { outline:none; border-color:rgba(188,205,255,.5); background:rgba(24,34,72,.82); }
      .detail-children__item span { overflow:hidden; font-size:12px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }
      .detail-children__item small { color:rgba(205,217,255,.55); font-size:9px; }
    `;
    document.head.appendChild(style);
  };

  const render = async () => {
    if (rendering) return;
    const detailPanel = panel();
    const selectedId = normalize(detailPanel?.dataset.taskId);
    if (!detailPanel || !selectedId || !detailPanel.querySelector(".detail-panel__content")) return;
    rendering = true;
    try {
      await loadTasks();
      detailPanel.querySelector('[data-univ-detail-children="true"]')?.remove();
      const parent = selectedTask(selectedId);
      const children = childTasksOf(parent);
      if (!children.length) return;
      ensureStyles();
      detailPanel.querySelector(".detail-panel__content")?.appendChild(buildSection(children));
    } finally {
      rendering = false;
    }
  };

  const initialize = () => {
    const detailPanel = panel();
    if (!detailPanel) return;
    const observer = new MutationObserver(() => void render());
    observer.observe(detailPanel, { childList: true });
    document.addEventListener("click", (event) => {
      const target = event.target instanceof Element
        ? event.target.closest("#constellation-grid [data-task-id]")
        : null;
      if (target) window.requestAnimationFrame(() => void render());
    });
    document.addEventListener("petit:tasks-updated", () => {
      void loadTasks({ force: true }).then(() => render());
    });
    void loadTasks().then(() => render());
  };

  window.PetitUnivDetailChildren = { initialized: true, refresh: render };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();
