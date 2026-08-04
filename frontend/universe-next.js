// PETIT Universe enhancements: Life-first task hierarchy, zoom, and spatial motion.
(() => {
  const ZOOM = { min: 0.82, max: 1.22, step: 0.1, storage: "petit_universe_zoom" };
  const state = {
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
  const constellationGrid = byId("constellation-grid");
  const taskTableBody = byId("task-table-body");
  const zoomLabel = byId("focus-zoom-label");

  const text = (value) => String(value ?? "").trim();
  const taskId = (task) => String(task?.id || task?.external_id || "");
  const rootTitle = (task) => text(task?.root_title || task?.project_title || task?.title);
  const isRoot = (task) => task?.hierarchy_role === "root" || !task?.parent_task_id;

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  const loadCatalog = async () => {
    try {
      const sharedTasks = window.PetitUniverse?.tasks?.() || [];
      if (sharedTasks.length) {
        state.tasks = sharedTasks;
        scheduleDecorate();
        return;
      }
      const data = await requestJson("/api/notifications/tasks?priority=all&limit=500");
      state.tasks = data.tasks || [];
      scheduleDecorate();
    } catch (error) {
      console.warn("PETIT task hierarchy load failed", error);
    }
  };

  const findTask = ({ id = "", title = "", root = "", due = "" } = {}) => {
    if (id) {
      const exact = state.tasks.find((task) => taskId(task) === String(id));
      if (exact) return exact;
    }
    const matches = state.tasks.filter((task) => {
      if (title && text(task.title) !== title) return false;
      if (root && rootTitle(task) !== root) return false;
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
        root: text(cells[3]?.dataset.rootTitle || ""),
      });
      state.selectedTaskId = task ? taskId(task) : null;
      return;
    }

    const universeTask = target.closest(".universe-task");
    if (universeTask) {
      const task = findTask({ id: universeTask.dataset.taskId || "" }) || findTask({
        title: text(universeTask.querySelector(".universe-task__title")?.textContent),
        root: text(universeTask.closest(".constellation-card")?.querySelector(".constellation-card__heading strong")?.textContent),
      });
      state.selectedTaskId = task ? taskId(task) : null;
    }
  };

  const currentDetailTask = () => {
    const displayedId = detailPanel?.dataset.taskId || "";
    const displayed = findTask({ id: displayedId });
    if (displayed) {
      state.selectedTaskId = taskId(displayed);
      return displayed;
    }
    const remembered = findTask({ id: state.selectedTaskId || "" });
    if (remembered) return remembered;
    const title = text(detailPanel?.querySelector('[data-detail="title"]')?.textContent);
    return findTask({ title });
  };

  const parentCandidates = (task) => state.tasks.filter((candidate) => {
    if (!isRoot(candidate)) return false;
    if (taskId(candidate) === taskId(task)) return false;
    if (task.source === "notion" && (!candidate.external_id || candidate.source !== "notion")) return false;
    return true;
  });

  const decorateDetail = () => {
    const select = detailPanel?.querySelector('[data-action="parent"]');
    const applyButton = detailPanel?.querySelector('[data-action="parent-apply"]');
    const help = detailPanel?.querySelector("[data-parent-help]");
    if (!(select instanceof HTMLSelectElement) || !(applyButton instanceof HTMLButtonElement) || !help || select.dataset.ready === "1") return;
    const task = currentDetailTask();
    if (!task) return;

    state.selectedTaskId = taskId(task);
    const parentLabel = detailPanel.querySelector('[data-detail="project"]');
    if (parentLabel) {
      const nextLabel = isRoot(task) ? "Life直下" : text(task.parent_title) || "Life直下";
      if (parentLabel.textContent !== nextLabel) parentLabel.textContent = nextLabel;
    }

    select.replaceChildren();
    const life = document.createElement("option");
    life.value = "";
    life.textContent = "Life直下";
    select.appendChild(life);

    parentCandidates(task).forEach((candidate) => {
      const option = document.createElement("option");
      option.value = taskId(candidate);
      option.textContent = candidate.title;
      select.appendChild(option);
    });
    select.value = String(task.parent_task_id || "");
    select.dataset.originalValue = select.value;
    applyButton.disabled = true;

    const lockedParent = Boolean(task.has_children);
    select.disabled = lockedParent;
    const nextHelp = lockedParent
      ? "このタスクは子タスクを持つ親です。親子階層は2段までに制限しています。"
      : task.source === "notion"
        ? "Life直下のNotionタスクを選び、「親Taskを変更」で保存します。"
        : "Life直下または別の親Taskを選び、明示的に保存します。";
    if (help.textContent !== nextHelp) help.textContent = nextHelp;
    select.dataset.ready = "1";
    select.addEventListener("click", (event) => event.stopPropagation());
  };

  const decorateNodes = () => {
    const selectedRoot = text(byId("focus-project-name")?.textContent);
    let visibleChildren = 0;
    taskNodes?.querySelectorAll(".space-node").forEach((node, index) => {
      const task = findTask({ id: node.dataset.taskId || "" });
      const idxStr = String(index);
      if (node.style.getPropertyValue("--node-index") !== idxStr) {
        node.style.setProperty("--node-index", idxStr);
      }
      if (task && isRoot(task) && rootTitle(task) === selectedRoot) {
        if (!node.classList.contains("hierarchy-root-duplicate")) {
          node.classList.add("hierarchy-root-duplicate");
        }
        if (node.getAttribute("aria-hidden") !== "true") {
          node.setAttribute("aria-hidden", "true");
        }
      } else {
        if (node.classList.contains("hierarchy-root-duplicate")) {
          node.classList.remove("hierarchy-root-duplicate");
        }
        if (node.hasAttribute("aria-hidden")) {
          node.removeAttribute("aria-hidden");
        }
        visibleChildren += 1;
      }
    });
    const empty = byId("focus-empty");
    if (empty) {
      const shouldHide = visibleChildren > 0;
      if (empty.hidden !== shouldHide) empty.hidden = shouldHide;
    }
  };

  const decorateLife = () => {
    constellationGrid?.querySelectorAll(".constellation-card").forEach((card) => {
      const heading = text(card.querySelector(".constellation-card__heading strong")?.textContent);
      const root = state.tasks.find((task) => isRoot(task) && text(task.title) === heading);
      if (!root) return;
      const hasChildren = Boolean(root.has_children);
      if (card.classList.contains("constellation-card--parent") !== hasChildren) {
        card.classList.toggle("constellation-card--parent", hasChildren);
      }
      if (card.classList.contains("constellation-card--single") !== !hasChildren) {
        card.classList.toggle("constellation-card--single", !hasChildren);
      }

      const eyebrow = card.querySelector(".eyebrow");
      if (eyebrow) {
        const nextEyebrow = hasChildren ? "LIFE DIRECT · PARENT TASK" : "LIFE DIRECT · TASK";
        if (eyebrow.textContent !== nextEyebrow) eyebrow.textContent = nextEyebrow;
      }

      const children = state.tasks.filter((task) => Number(task.parent_task_id) === Number(root.id));
      const counts = card.querySelector(".constellation-card__counts");
      if (counts) {
        const nextCounts = hasChildren ? `${children.length} Child Task` : "単独Task";
        if (counts.textContent !== nextCounts) counts.textContent = nextCounts;
      }

      card.querySelectorAll(".universe-task").forEach((row) => {
        const title = text(row.querySelector(".universe-task__title")?.textContent);
        const task = state.tasks.find((item) => rootTitle(item) === heading && text(item.title) === title);
        if (!task) return;
        const taskIsRoot = isRoot(task);
        if (row.classList.contains("universe-task--root-copy") !== taskIsRoot) {
          row.classList.toggle("universe-task--root-copy", taskIsRoot);
        }
        if (row.classList.contains("universe-task--child") !== !taskIsRoot) {
          row.classList.toggle("universe-task--child", !taskIsRoot);
        }
      });
    });

    const groups = new Set(state.tasks.filter(isRoot).map((task) => taskId(task))).size;
    const children = state.tasks.filter((task) => !isRoot(task)).length;
    const summary = byId("universe-summary");
    if (summary) {
      const nextSummary = `Life · ${groups} Task · ${children} Child`;
      if (summary.textContent !== nextSummary) summary.textContent = nextSummary;
    }
  };

  const decorateTaskTable = () => {
    taskTableBody?.querySelectorAll("tr").forEach((row) => {
      const cells = row.querySelectorAll("td");
      if (cells.length < 4) return;
      const title = text(row.querySelector(".task-table__title")?.textContent);
      const due = text(row.querySelector(".task-table__due")?.textContent).replace("—", "");
      const task = findTask({ title, due });
      if (!task) return;
      const nextText = isRoot(task) ? "Life直下" : text(task.parent_title) || "Life直下";
      if (cells[3].textContent !== nextText) cells[3].textContent = nextText;
      const nextRoot = rootTitle(task);
      if (cells[3].dataset.rootTitle !== nextRoot) cells[3].dataset.rootTitle = nextRoot;
      const childClass = !isRoot(task);
      if (row.classList.contains("task-row--child") !== childClass) {
        row.classList.toggle("task-row--child", childClass);
      }
    });
  };

  const decorateAll = () => {
    stopObserving();
    try {
      decorateDetail();
      decorateNodes();
      decorateLife();
      decorateTaskTable();
    } finally {
      startObserving();
    }
  };

  let isDecoratingScheduled = false;
  let activeObservers = [];

  const startObserving = () => {
    stopObserving();
    const targets = [
      detailPanel,
      taskNodes,
      constellationGrid,
      taskTableBody,
    ].filter(Boolean);

    activeObservers = targets.map((element) => {
      const observer = new MutationObserver(() => scheduleDecorate());
      observer.observe(element, { childList: true });
      return observer;
    });
  };

  const stopObserving = () => {
    activeObservers.forEach((obs) => obs.disconnect());
    activeObservers = [];
  };

  const scheduleDecorate = () => {
    if (isDecoratingScheduled) return;
    isDecoratingScheduled = true;
    queueMicrotask(() => {
      isDecoratingScheduled = false;
      decorateAll();
    });
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

  document.addEventListener("click", rememberTaskFromClick, true);
  document.addEventListener("petit:tasks-updated", (event) => {
    const tasks = event.detail?.tasks;
    if (!Array.isArray(tasks)) return;
    state.tasks = tasks;
    scheduleDecorate();
  });
  startObserving();

  document.documentElement.dataset.universeMotion = "ready";
  applyZoom(state.zoom, { persist: false });
  installZoom();
  installParallax();
  void loadCatalog();
})();
