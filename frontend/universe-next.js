// PETIT Universe enhancements: Project classification, zoom, and spatial motion.
(() => {
  const ALL_LABEL = "All";
  const ZOOM = { min: 0.82, max: 1.22, step: 0.1, storage: "petit_universe_zoom" };
  const state = {
    projects: [],
    tasks: [],
    selectedTaskId: null,
    zoom: Number(localStorage.getItem(ZOOM.storage)) || 1,
    pinching: false,
    pinchDistance: 0,
    pinchZoom: 1,
  };

  const byId = (id) => document.getElementById(id);
  const orbit = byId("orbit");
  const detailPanel = byId("detail-panel");
  const taskNodes = byId("task-nodes");
  const zoomLabel = byId("focus-zoom-label");

  const text = (value) => String(value ?? "").trim();
  const taskId = (task) => String(task?.id || task?.external_id || "");
  const taskProject = (task) => text(task?.project_title || task?.project_name) || ALL_LABEL;

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
    window.setTimeout(() => { feedback.hidden = true; }, 4400);
  };

  const loadCatalog = async () => {
    const [taskResult, projectResult] = await Promise.allSettled([
      requestJson("/api/notifications/tasks?priority=all&limit=500"),
      requestJson("/api/notifications/projects"),
    ]);
    if (taskResult.status === "fulfilled") state.tasks = taskResult.value.tasks || [];
    if (projectResult.status === "fulfilled") state.projects = projectResult.value.projects || [];
    decorateDetail();
  };

  const findTask = ({ id = "", title = "", project = "", due = "" } = {}) => {
    if (id) {
      const exact = state.tasks.find((task) => taskId(task) === String(id));
      if (exact) return exact;
    }
    const matches = state.tasks.filter((task) => {
      if (title && text(task.title) !== title) return false;
      if (project && taskProject(task) !== project) return false;
      if (due && text(task.due_date) !== due) return false;
      return true;
    });
    return matches.length === 1 ? matches[0] : matches[0] || null;
  };

  const rememberTaskFromClick = (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const node = target.closest(".space-node[data-task-id]");
    if (node) {
      state.selectedTaskId = node.dataset.taskId || null;
      return;
    }

    const tableRow = target.closest("#task-table-body tr");
    if (tableRow) {
      const cells = tableRow.querySelectorAll("td");
      const task = findTask({
        title: text(tableRow.querySelector(".task-table__title")?.textContent),
        due: text(tableRow.querySelector(".task-table__due")?.textContent).replace("—", ""),
        project: text(cells[3]?.textContent),
      });
      state.selectedTaskId = task ? taskId(task) : null;
      return;
    }

    const universeTask = target.closest(".universe-task");
    if (universeTask) {
      const task = findTask({
        title: text(universeTask.querySelector(".universe-task__title")?.textContent),
        project: text(universeTask.closest(".constellation-card")?.querySelector(".constellation-card__heading strong")?.textContent),
      });
      state.selectedTaskId = task ? taskId(task) : null;
    }
  };

  const currentDetailTask = () => {
    const remembered = findTask({ id: state.selectedTaskId || "" });
    if (remembered) return remembered;
    const title = text(detailPanel?.querySelector('[data-detail="title"]')?.textContent);
    const project = text(detailPanel?.querySelector('[data-detail="project"]')?.textContent);
    return findTask({ title, project });
  };

  const projectOption = (project, task) => {
    const option = document.createElement("option");
    option.value = String(project.id);
    option.textContent = project.name;
    option.disabled = task.source === "notion" && !project.notion_linked;
    if (option.disabled) option.textContent += "（Notion未連携）";
    return option;
  };

  const assignProject = async (task, select, help) => {
    const projectId = select.value;
    const project = state.projects.find((item) => String(item.id) === projectId);
    if (!project || projectId === String(task.project_id || "")) return;
    select.disabled = true;
    help.textContent = `「${project.name}」へ移動しています…`;
    try {
      await requestJson(`/api/notifications/tasks/${encodeURIComponent(taskId(task))}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, resolve_notification: false }),
      });
      state.selectedTaskId = taskId(task);
      showFeedback(`「${text(task.title) || "タスク"}」を「${project.name}」へ分類しました。`);
      await loadCatalog();
      byId("refresh-universe")?.click();
    } catch (error) {
      help.textContent = error.message;
      showFeedback(`Projectを変更できませんでした: ${error.message}`);
      select.disabled = false;
      select.value = String(task.project_id || "");
    }
  };

  const decorateDetail = () => {
    const select = detailPanel?.querySelector('[data-action="project"]');
    const help = detailPanel?.querySelector("[data-project-help]");
    if (!(select instanceof HTMLSelectElement) || !help || select.dataset.ready === "1") return;
    const task = currentDetailTask();
    if (!task) return;

    state.selectedTaskId = taskId(task);
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = `${ALL_LABEL}（Project未設定）`;
    all.disabled = true;
    select.appendChild(all);

    state.projects.forEach((project) => select.appendChild(projectOption(project, task)));
    select.value = String(task.project_id || "");
    select.disabled = !state.projects.some((project) => !(task.source === "notion" && !project.notion_linked));
    help.textContent = task.source === "notion"
      ? "確認済みNotion Projectだけ選択できます。変更はSQLiteへ即時反映され、Notionへ同期されます。"
      : "既存Projectを選ぶと、このTaskをそのProjectへ移動します。";
    select.dataset.ready = "1";
    select.addEventListener("click", (event) => event.stopPropagation());
    select.addEventListener("change", () => assignProject(task, select, help));
  };

  const zoomLevel = () => (state.zoom < 0.94 ? "far" : (state.zoom > 1.08 ? "near" : "normal"));

  const applyZoom = (value, { persist = true } = {}) => {
    state.zoom = Math.min(ZOOM.max, Math.max(ZOOM.min, Number(value) || 1));
    orbit?.style.setProperty("--universe-zoom", state.zoom.toFixed(2));
    if (orbit) orbit.dataset.zoomLevel = zoomLevel();
    if (zoomLabel) zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
    byId("focus-zoom-out")?.toggleAttribute("disabled", state.zoom <= ZOOM.min + 0.001);
    byId("focus-zoom-in")?.toggleAttribute("disabled", state.zoom >= ZOOM.max - 0.001);
    if (persist) localStorage.setItem(ZOOM.storage, String(state.zoom));
  };

  const pinchDistance = (touches) => {
    if (touches.length < 2) return 0;
    return Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY);
  };

  const installZoom = () => {
    byId("focus-zoom-out")?.addEventListener("click", () => applyZoom(state.zoom - ZOOM.step));
    byId("focus-zoom-in")?.addEventListener("click", () => applyZoom(state.zoom + ZOOM.step));
    byId("focus-zoom-reset")?.addEventListener("click", () => applyZoom(1));
    if (!orbit) return;

    orbit.addEventListener("touchstart", (event) => {
      if (event.touches.length !== 2) return;
      state.pinching = true;
      state.pinchDistance = pinchDistance(event.touches);
      state.pinchZoom = state.zoom;
    }, { passive: true });
    orbit.addEventListener("touchmove", (event) => {
      if (!state.pinching || event.touches.length !== 2) return;
      const distance = pinchDistance(event.touches);
      if (!distance || !state.pinchDistance) return;
      event.preventDefault();
      applyZoom(state.pinchZoom * (distance / state.pinchDistance), { persist: false });
    }, { passive: false });
    orbit.addEventListener("touchend", () => {
      if (!state.pinching) return;
      state.pinching = false;
      localStorage.setItem(ZOOM.storage, String(state.zoom));
    }, { passive: true });
  };

  const installParallax = () => {
    const card = document.querySelector(".orbit-card");
    if (!card || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    card.addEventListener("pointermove", (event) => {
      if (event.pointerType === "touch") return;
      const rect = card.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
      const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
      card.style.setProperty("--orbit-parallax-x", `${x * 10}px`);
      card.style.setProperty("--orbit-parallax-y", `${y * 8}px`);
    });
    card.addEventListener("pointerleave", () => {
      card.style.setProperty("--orbit-parallax-x", "0px");
      card.style.setProperty("--orbit-parallax-y", "0px");
    });
  };

  const decorateNodes = () => {
    taskNodes?.querySelectorAll(".space-node").forEach((node, index) => {
      node.style.setProperty("--node-index", String(index));
    });
  };

  document.addEventListener("click", rememberTaskFromClick, true);
  new MutationObserver(() => queueMicrotask(decorateDetail)).observe(detailPanel, { childList: true, subtree: true });
  new MutationObserver(decorateNodes).observe(taskNodes, { childList: true });

  document.documentElement.dataset.universeMotion = "ready";
  applyZoom(state.zoom, { persist: false });
  installZoom();
  installParallax();
  decorateNodes();
  void loadCatalog();
})();
