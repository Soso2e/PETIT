// PETIT Univ: lightweight 3D planet system with Core, task planets, and child satellites.
(() => {
  if (window.PetitUnivSpace?.initialized) return;
  const OPEN_EVENT = "petit:univ-open";
  const AREA_EVENT = "petit:area-change";
  const state = {
    yaw: -7,
    pitch: 6,
    zoom: 1,
    panX: 0,
    panY: 0,
    mode: "overview",
    selectedTaskId: null,
    selectedSystemKey: null,
    dragging: false,
    pointerId: null,
    lastX: 0,
    lastY: 0,
  };

  let mutationObserver = null;
  let decorateQueued = false;

  const panel = () => document.querySelector('[data-view-panel="universe"]');
  const map = () => document.querySelector("#constellation-grid");
  const viewport = () => document.querySelector(".univ-viewport");
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const text = (value, fallback = "") => String(value ?? "").trim() || fallback;

  const taskTitle = (task) => text(task?.querySelector(".universe-task__title")?.textContent, "Task");
  const taskId = (task) => text(task?.dataset.taskId);
  const systemCard = (node) => node?.closest?.(".constellation-card") || null;
  const systemHeader = (card) => card?.querySelector(".constellation-card__header") || null;
  const systemTasks = (card) => Array.from(card?.querySelectorAll(".universe-task[data-task-id]") || []);
  const rootTask = (card) => {
    if (!card) return null;
    const rootId = text(card.dataset.rootTaskId);
    if (rootId) {
      const exact = card.querySelector(`.universe-task[data-task-id="${CSS.escape(rootId)}"]`);
      if (exact) return exact;
    }
    return card.querySelector(".universe-task--root-copy[data-task-id]") || systemTasks(card)[0] || null;
  };
  const childTasks = (card) => {
    const root = rootTask(card);
    return systemTasks(card).filter((task) => task !== root && !task.classList.contains("univ-root-task-copy"));
  };

  const applyCamera = () => {
    const graph = map();
    if (!graph) return;
    graph.style.setProperty("--univ-yaw", `${state.yaw}deg`);
    graph.style.setProperty("--univ-pitch", `${state.pitch}deg`);
    graph.style.setProperty("--univ-zoom", String(state.zoom));
    graph.style.setProperty("--univ-pan-x", `${state.panX}px`);
    graph.style.setProperty("--univ-pan-y", `${state.panY}px`);
    graph.dataset.univMode = state.mode;
  };

  const selectedTask = () => {
    const graph = map();
    if (!graph || !state.selectedTaskId) return null;
    return graph.querySelector(`.universe-task[data-task-id="${CSS.escape(String(state.selectedTaskId))}"]`);
  };

  const setHud = ({ project = "PETIT", title = "Core", description = "中心の惑星から、親タスク惑星と子タスク衛星を見渡します。", canManage = false } = {}) => {
    const root = panel();
    if (!root) return;
    const projectEl = root.querySelector("[data-univ-selected-project]");
    const titleEl = root.querySelector("[data-univ-selected-title]");
    const descriptionEl = root.querySelector("[data-univ-selected-description]");
    const focus = root.querySelector('[data-univ-action="focus"]');
    const manage = root.querySelector('[data-univ-action="manage"]');
    const mode = root.querySelector("[data-univ-mode-label]");
    if (projectEl) projectEl.textContent = project;
    if (titleEl) titleEl.textContent = title;
    if (descriptionEl) descriptionEl.textContent = description;
    if (focus) focus.disabled = !state.selectedSystemKey;
    if (manage) manage.disabled = !canManage;
    if (mode) mode.textContent = state.mode === "focus" ? "PLANET FOCUS" : "CORE OVERVIEW";
  };

  const ensureHud = () => {
    const root = panel();
    const graph = map();
    if (!root || !graph) return null;
    root.classList.add("univ-panel");

    let frame = viewport();
    if (!frame) {
      frame = document.createElement("section");
      frame.className = "univ-viewport";
      frame.setAttribute("aria-label", "Coreを中心とするタスク惑星空間");
      graph.parentNode.insertBefore(frame, graph);
      frame.appendChild(graph);
    }

    if (!frame.querySelector(".univ-hud")) {
      const hud = document.createElement("div");
      hud.className = "univ-hud";
      hud.innerHTML = `
        <div class="univ-hud__brand">
          <span class="eyebrow">PETIT UNIVERSE</span>
          <strong>Univ</strong>
          <small data-univ-mode-label>CORE OVERVIEW</small>
        </div>
        <div class="univ-hud__selection" aria-live="polite">
          <span data-univ-selected-project>PETIT</span>
          <strong data-univ-selected-title>Core</strong>
          <p data-univ-selected-description>中心の惑星から、親タスク惑星と子タスク衛星を見渡します。</p>
          <div>
            <button type="button" data-univ-action="focus" disabled>Focus</button>
            <button type="button" data-univ-action="manage" disabled>管理</button>
          </div>
        </div>
        <div class="univ-hud__controls" aria-label="Univ camera controls">
          <button type="button" data-univ-action="overview" title="Coreへ戻る">Core</button>
          <button type="button" data-univ-action="zoom-out" aria-label="縮小">−</button>
          <button type="button" data-univ-action="zoom-in" aria-label="拡大">＋</button>
          <button type="button" data-univ-action="reset" title="視点をリセット">Reset</button>
        </div>
        <p class="univ-hud__help">Drag: orbit · Wheel: zoom · Planet: focus</p>
      `;
      frame.appendChild(hud);
    }

    if (!document.querySelector(".univ-detail-dismiss")) {
      const dismiss = document.createElement("button");
      dismiss.type = "button";
      dismiss.className = "univ-detail-dismiss";
      dismiss.textContent = "Close";
      dismiss.addEventListener("click", () => document.body.classList.remove("petit-univ-manage-open"));
      document.body.appendChild(dismiss);
    }

    const eyebrow = root.querySelector(".universe-section-head .eyebrow");
    const heading = root.querySelector(".universe-section-head h1");
    const copy = root.querySelector(".universe-section-head p");
    if (eyebrow) eyebrow.textContent = "UNIV";
    if (heading) heading.textContent = "Core / Task Planet / Satellite";
    if (copy) copy.textContent = "Coreを中心に、親タスクを惑星、子タスクを衛星として同じ空間で操作します。";
    return frame;
  };

  const decorateCore = (graph) => {
    const core = graph.querySelector(":scope > .life-map__core");
    if (!core) return;
    core.classList.add("univ-core-planet");
    core.setAttribute("role", "button");
    core.setAttribute("tabindex", "0");
    core.setAttribute("aria-label", "Core overviewへ戻る");
    const eyebrow = core.querySelector(".eyebrow");
    const title = core.querySelector("strong");
    const hint = core.querySelector("small");
    if (eyebrow) eyebrow.textContent = "CENTER PLANET";
    if (title) title.textContent = "CORE";
    if (hint) hint.textContent = "Overview";
  };

  const decorateSystem = (card, index) => {
    const header = systemHeader(card);
    if (!header) return;
    const root = rootTask(card);
    systemTasks(card).forEach((task) => task.classList.remove("univ-root-task-copy", "univ-satellite"));
    const children = childTasks(card);
    const heading = header.querySelector(".constellation-card__heading strong");
    const eyebrow = header.querySelector(".constellation-card__heading .eyebrow");
    const counts = header.querySelector(".constellation-card__counts");

    const originalProject = card.dataset.univProject || text(heading?.textContent, "Project");
    card.dataset.univProject = originalProject;
    card.dataset.univSystemKey = taskId(root) || card.dataset.rootTaskId || `system-${index}`;
    card.dataset.univVariant = String(index % 5);
    card.classList.add("univ-task-system");
    header.classList.add("univ-task-planet");

    const rootTitle = root ? taskTitle(root) : originalProject;
    if (heading) heading.textContent = rootTitle;
    if (eyebrow) eyebrow.textContent = originalProject;
    if (counts) counts.textContent = `${children.length} satellite${children.length === 1 ? "" : "s"}`;
    header.setAttribute("aria-label", `${rootTitle}のタスク惑星を選択`);

    if (root) {
      root.classList.add("univ-root-task-copy");
      root.setAttribute("aria-hidden", "true");
      root.tabIndex = -1;
    }

    children.forEach((task, taskIndex) => {
      const count = Math.max(1, children.length);
      const angle = -90 + ((360 / count) * taskIndex);
      const radius = 84 + ((taskIndex % 2) * 18) + Math.min(20, Math.floor(taskIndex / 6) * 12);
      task.classList.add("univ-satellite");
      task.style.setProperty("--satellite-angle", `${angle}deg`);
      task.style.setProperty("--satellite-radius", `${radius}px`);
      task.style.setProperty("--satellite-depth", `${30 + ((taskIndex % 4) * 14)}px`);
      task.style.setProperty("--satellite-delay", `${(index * 60) + (taskIndex * 45)}ms`);
      task.setAttribute("aria-label", `${taskTitle(task)}。${rootTitle}の子タスク衛星`);
    });
  };

  const decorateScene = () => {
    decorateQueued = false;
    const graph = map();
    if (!graph) return;
    graph.classList.add("univ-space");
    decorateCore(graph);
    graph.querySelectorAll(":scope > .constellation-card").forEach(decorateSystem);
    applyCamera();
  };

  const scheduleDecorate = () => {
    if (decorateQueued) return;
    decorateQueued = true;
    window.requestAnimationFrame(decorateScene);
  };

  const clearFocusClasses = () => {
    map()?.querySelectorAll(".is-univ-focus-family, .is-univ-focus-target").forEach((node) => {
      node.classList.remove("is-univ-focus-family", "is-univ-focus-target");
    });
  };

  const resetCamera = ({ keepSelection = false } = {}) => {
    state.yaw = -7;
    state.pitch = 6;
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    state.mode = "overview";
    if (!keepSelection) {
      state.selectedTaskId = null;
      state.selectedSystemKey = null;
    }
    clearFocusClasses();
    document.body.classList.remove("petit-univ-manage-open");
    applyCamera();
    setHud();
  };

  const centerSystem = (card) => {
    const frame = viewport();
    if (!frame || !card) return;
    state.panX = 0;
    state.panY = 0;
    applyCamera();
    window.requestAnimationFrame(() => {
      const targetRect = card.getBoundingClientRect();
      const frameRect = frame.getBoundingClientRect();
      state.panX = clamp((frameRect.left + frameRect.width / 2) - (targetRect.left + targetRect.width / 2), -520, 520);
      state.panY = clamp((frameRect.top + frameRect.height / 2) - (targetRect.top + targetRect.height / 2), -360, 360);
      applyCamera();
    });
  };

  const focusSystem = (card, target = null) => {
    if (!card) return;
    clearFocusClasses();
    state.mode = "focus";
    state.selectedSystemKey = card.dataset.univSystemKey || card.dataset.rootTaskId || null;
    state.selectedTaskId = target ? taskId(target) : taskId(rootTask(card));
    state.yaw = 0;
    state.pitch = 3;
    state.zoom = target ? 1.42 : 1.34;
    card.classList.add("is-univ-focus-family");
    if (target) target.classList.add("is-univ-focus-target");
    applyCamera();
    centerSystem(card);

    const project = card.dataset.univProject || "Project";
    const planetTitle = text(systemHeader(card)?.querySelector(".constellation-card__heading strong")?.textContent, "Task");
    if (target) {
      setHud({
        project,
        title: taskTitle(target),
        description: `「${planetTitle}」を周回する子タスク衛星です。親タスク惑星と同じ空間で管理します。`,
        canManage: true,
      });
    } else {
      setHud({
        project,
        title: planetTitle,
        description: `親タスク惑星です。周囲の${childTasks(card).length}個の衛星が子タスクです。`,
        canManage: Boolean(rootTask(card)),
      });
    }
  };

  const focusByTaskId = (requestedTaskId, { satellite = false, project = "" } = {}) => {
    const graph = map();
    if (!graph) return;
    scheduleDecorate();
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      let task = requestedTaskId
        ? graph.querySelector(`.universe-task[data-task-id="${CSS.escape(String(requestedTaskId))}"]`)
        : null;
      let card = systemCard(task);
      if (!card && project) {
        card = Array.from(graph.querySelectorAll(":scope > .constellation-card"))
          .find((candidate) => candidate.dataset.univProject === project
            || text(candidate.querySelector(".constellation-card__heading .eyebrow")?.textContent) === project)
          || null;
        task = rootTask(card);
      }
      focusSystem(card, satellite ? task : null);
    }));
  };

  const focusCurrent = () => {
    const graph = map();
    if (!graph || !state.selectedSystemKey) return;
    const card = graph.querySelector(`.constellation-card[data-univ-system-key="${CSS.escape(String(state.selectedSystemKey))}"]`);
    const task = selectedTask();
    focusSystem(card, task?.classList.contains("univ-satellite") ? task : null);
  };

  const openManagement = () => {
    if (!state.selectedTaskId) return;
    document.body.classList.add("petit-univ-manage-open");
    document.querySelector("#detail-panel")?.focus?.({ preventScroll: true });
  };

  const handleAction = (action) => {
    if (action === "overview") resetCamera();
    if (action === "reset") resetCamera({ keepSelection: true });
    if (action === "focus") focusCurrent();
    if (action === "manage") openManagement();
    if (action === "zoom-in") {
      state.zoom = clamp(state.zoom + 0.12, 0.68, 1.72);
      applyCamera();
    }
    if (action === "zoom-out") {
      state.zoom = clamp(state.zoom - 0.12, 0.68, 1.72);
      applyCamera();
    }
  };

  const installSelectionCapture = () => {
    document.addEventListener("click", (event) => {
      const graph = map();
      const target = event.target instanceof Element ? event.target : null;
      if (!graph || !target || !graph.contains(target)) return;

      const core = target.closest(".life-map__core");
      if (core) {
        event.preventDefault();
        event.stopImmediatePropagation();
        resetCamera();
        return;
      }

      const satellite = target.closest(".universe-task[data-task-id]");
      if (satellite && !satellite.classList.contains("univ-root-task-copy")) {
        const alreadySelected = satellite.classList.contains("is-selected") || state.selectedTaskId === taskId(satellite);
        if (alreadySelected) {
          event.preventDefault();
          event.stopImmediatePropagation();
        }
        const requestedTaskId = taskId(satellite);
        state.selectedTaskId = requestedTaskId;
        state.selectedSystemKey = systemCard(satellite)?.dataset.univSystemKey || null;
        focusByTaskId(requestedTaskId, { satellite: true });
        return;
      }

      const header = target.closest(".constellation-card__header");
      if (header) {
        const card = systemCard(header);
        const root = rootTask(card);
        const alreadySelected = header.classList.contains("is-selected") || state.selectedTaskId === taskId(root);
        if (alreadySelected) {
          event.preventDefault();
          event.stopImmediatePropagation();
        }
        const requestedTaskId = taskId(root);
        const project = card?.dataset.univProject || text(header.querySelector(".constellation-card__heading .eyebrow")?.textContent);
        state.selectedTaskId = requestedTaskId;
        state.selectedSystemKey = card?.dataset.univSystemKey || null;
        focusByTaskId(requestedTaskId, { project });
      }
    }, true);
  };

  const bindInteraction = () => {
    const frame = ensureHud();
    const graph = map();
    if (!frame || !graph || frame.dataset.univReady === "true") return;
    frame.dataset.univReady = "true";
    frame.tabIndex = 0;

    frame.addEventListener("click", (event) => {
      const action = event.target.closest("[data-univ-action]")?.dataset.univAction;
      if (action) handleAction(action);
    });

    frame.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      if (event.target.closest("button, a, input, select, textarea, .life-map__core")) return;
      state.dragging = true;
      state.pointerId = event.pointerId;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      frame.setPointerCapture?.(event.pointerId);
      frame.classList.add("is-dragging");
    });

    frame.addEventListener("pointermove", (event) => {
      if (!state.dragging || state.pointerId !== event.pointerId) return;
      const dx = event.clientX - state.lastX;
      const dy = event.clientY - state.lastY;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      state.yaw += dx * 0.11;
      state.pitch = clamp(state.pitch - (dy * 0.09), -24, 24);
      applyCamera();
    });

    const endDrag = (event) => {
      if (state.pointerId !== event.pointerId) return;
      state.dragging = false;
      state.pointerId = null;
      frame.classList.remove("is-dragging");
      frame.releasePointerCapture?.(event.pointerId);
    };
    frame.addEventListener("pointerup", endDrag);
    frame.addEventListener("pointercancel", endDrag);

    frame.addEventListener("wheel", (event) => {
      event.preventDefault();
      state.zoom = clamp(state.zoom - (event.deltaY * 0.0012), 0.68, 1.72);
      applyCamera();
    }, { passive: false });

    frame.addEventListener("keydown", (event) => {
      if (event.key === "Escape") resetCamera();
      if (event.key === "ArrowLeft") state.yaw -= 4;
      if (event.key === "ArrowRight") state.yaw += 4;
      if (event.key === "ArrowUp") state.pitch = clamp(state.pitch + 3, -24, 24);
      if (event.key === "ArrowDown") state.pitch = clamp(state.pitch - 3, -24, 24);
      if (event.key === "+" || event.key === "=") state.zoom = clamp(state.zoom + 0.1, 0.68, 1.72);
      if (event.key === "-") state.zoom = clamp(state.zoom - 0.1, 0.68, 1.72);
      if (event.key === "0") resetCamera({ keepSelection: true });
      applyCamera();
    });

    mutationObserver = new MutationObserver(scheduleDecorate);
    mutationObserver.observe(graph, { childList: true, subtree: true });
  };

  const showUniv = ({ mode = "overview", taskId: requestedTaskId = null } = {}) => {
    document.body.classList.add("petit-univ-active");
    ensureHud();
    scheduleDecorate();
    if (mode === "focus" && requestedTaskId) {
      state.selectedTaskId = String(requestedTaskId);
      window.requestAnimationFrame(() => {
        const task = selectedTask();
        focusSystem(systemCard(task), task?.classList.contains("univ-satellite") ? task : null);
      });
      return;
    }
    resetCamera();
  };

  const syncInitialArea = () => {
    window.requestAnimationFrame(() => {
      const root = panel();
      if (!root) return;
      const active = !root.hidden && root.getAttribute("aria-hidden") !== "true";
      document.body.classList.toggle("petit-univ-active", active);
      if (active) resetCamera();
    });
  };

  const initialize = () => {
    ensureHud();
    bindInteraction();
    installSelectionCapture();
    scheduleDecorate();
    syncInitialArea();
    window.addEventListener(OPEN_EVENT, (event) => showUniv(event.detail || {}));
    window.addEventListener(AREA_EVENT, (event) => {
      const active = event.detail?.area === "univ";
      document.body.classList.toggle("petit-univ-active", active);
      if (!active) document.body.classList.remove("petit-univ-manage-open");
    });
    document.addEventListener("petit:tasks-updated", scheduleDecorate);
  };

  window.PetitUnivSpace = {
    initialize,
    initialized: true,
    reset: resetCamera,
    focusTask: (requestedTaskId) => {
      state.selectedTaskId = requestedTaskId ? String(requestedTaskId) : null;
      const task = selectedTask();
      focusSystem(systemCard(task), task?.classList.contains("univ-satellite") ? task : null);
    },
    state: () => ({ ...state }),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
