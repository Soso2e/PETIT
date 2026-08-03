// PETIT Univ: one navigable 3D task space with a persistent foreground HUD.
(() => {
  const OPEN_EVENT = "petit:univ-open";
  const AREA_EVENT = "petit:area-change";
  const state = {
    yaw: -8,
    pitch: 7,
    zoom: 1,
    panX: 0,
    panY: 0,
    mode: "overview",
    selectedTaskId: null,
    dragging: false,
    pointerId: null,
    lastX: 0,
    lastY: 0,
  };
  let mutationObserver = null;

  const panel = () => document.querySelector('[data-view-panel="universe"]');
  const map = () => document.querySelector("#constellation-grid");
  const viewport = () => document.querySelector(".univ-viewport");
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

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
    if (!graph) return null;
    if (state.selectedTaskId) {
      const escaped = CSS.escape(String(state.selectedTaskId));
      const exact = graph.querySelector(`.universe-task[data-task-id="${escaped}"]`);
      if (exact) return exact;
    }
    return graph.querySelector(".universe-task.is-selected") || null;
  };

  const taskCopy = (task) => ({
    title: task?.querySelector(".universe-task__title")?.textContent?.trim() || "Taskを選択",
    project: task?.closest(".constellation-card")?.querySelector(".constellation-card__heading strong")?.textContent?.trim() || "Core",
  });

  const updateHud = () => {
    const root = panel();
    if (!root) return;
    const task = selectedTask();
    const copy = taskCopy(task);
    const title = root.querySelector("[data-univ-selected-title]");
    const project = root.querySelector("[data-univ-selected-project]");
    const focus = root.querySelector('[data-univ-action="focus"]');
    const manage = root.querySelector('[data-univ-action="manage"]');
    const mode = root.querySelector("[data-univ-mode-label]");
    if (title) title.textContent = copy.title;
    if (project) project.textContent = copy.project;
    if (focus) focus.disabled = !task;
    if (manage) manage.disabled = !task;
    if (mode) mode.textContent = state.mode === "focus" ? "FOCUS" : "OVERVIEW";
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
      frame.setAttribute("aria-label", "Univ 3D task space");
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
          <small data-univ-mode-label>OVERVIEW</small>
        </div>
        <div class="univ-hud__selection" aria-live="polite">
          <span data-univ-selected-project>Core</span>
          <strong data-univ-selected-title>Taskを選択</strong>
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
        <p class="univ-hud__help">Drag to orbit · Wheel / +/- to zoom · Select a star</p>
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
    if (heading) heading.textContent = "One space. Every task.";
    if (copy) copy.textContent = "CoreからProjectとTaskへ移動し、選択・Focus・管理を同じ空間で行います。";
    return frame;
  };

  const decorateDepth = () => {
    const graph = map();
    if (!graph) return;
    graph.classList.add("univ-space");
    graph.querySelectorAll(":scope > .constellation-card").forEach((card, index) => {
      const depth = ((index % 5) - 2) * 76;
      card.style.setProperty("--univ-depth", `${depth}px`);
      card.querySelectorAll(".universe-task").forEach((task, taskIndex) => {
        const taskDepth = 44 + ((taskIndex % 3) * 24);
        task.style.setProperty("--univ-task-depth", `${taskDepth}px`);
      });
    });
    const core = graph.querySelector(":scope > .life-map__core");
    if (core) {
      core.setAttribute("role", "button");
      core.setAttribute("tabindex", "0");
      core.setAttribute("aria-label", "Coreへ戻る");
      const eyebrow = core.querySelector(".eyebrow");
      const title = core.querySelector("strong");
      const hint = core.querySelector("small");
      if (eyebrow) eyebrow.textContent = "YOUR UNIVERSE";
      if (title) title.textContent = "CORE";
      if (hint) hint.textContent = "Reset viewpoint";
    }
    updateHud();
  };

  const resetCamera = ({ keepSelection = false } = {}) => {
    state.yaw = -8;
    state.pitch = 7;
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    state.mode = "overview";
    if (!keepSelection) state.selectedTaskId = null;
    map()?.querySelectorAll(".is-univ-focus-target, .is-univ-focus-family").forEach((node) => {
      node.classList.remove("is-univ-focus-target", "is-univ-focus-family");
    });
    document.body.classList.remove("petit-univ-manage-open");
    applyCamera();
    updateHud();
  };

  const focusTask = (task = selectedTask()) => {
    const graph = map();
    const frame = viewport();
    if (!graph || !frame || !task) return;
    state.selectedTaskId = task.dataset.taskId || state.selectedTaskId;
    state.mode = "focus";
    graph.querySelectorAll(".is-univ-focus-target, .is-univ-focus-family").forEach((node) => {
      node.classList.remove("is-univ-focus-target", "is-univ-focus-family");
    });
    task.classList.add("is-univ-focus-target");
    task.closest(".constellation-card")?.classList.add("is-univ-focus-family");
    state.zoom = clamp(Math.max(state.zoom, 1.2), 0.7, 1.7);
    applyCamera();
    window.requestAnimationFrame(() => {
      const targetRect = task.getBoundingClientRect();
      const frameRect = frame.getBoundingClientRect();
      state.panX += (frameRect.left + frameRect.width / 2) - (targetRect.left + targetRect.width / 2);
      state.panY += (frameRect.top + frameRect.height / 2) - (targetRect.top + targetRect.height / 2);
      applyCamera();
    });
    updateHud();
  };

  const openManagement = () => {
    const task = selectedTask();
    if (!task) return;
    task.click();
    document.body.classList.add("petit-univ-manage-open");
    document.querySelector("#detail-panel")?.focus?.({ preventScroll: true });
  };

  const handleAction = (action) => {
    if (action === "overview" || action === "reset") resetCamera({ keepSelection: action === "reset" });
    if (action === "focus") focusTask();
    if (action === "manage") openManagement();
    if (action === "zoom-in") {
      state.zoom = clamp(state.zoom + 0.12, 0.7, 1.7);
      applyCamera();
    }
    if (action === "zoom-out") {
      state.zoom = clamp(state.zoom - 0.12, 0.7, 1.7);
      applyCamera();
    }
  };

  const bindInteraction = () => {
    const frame = ensureHud();
    const graph = map();
    if (!frame || !graph || frame.dataset.univReady === "true") return;
    frame.dataset.univReady = "true";
    frame.tabIndex = 0;

    frame.addEventListener("click", (event) => {
      const action = event.target.closest("[data-univ-action]")?.dataset.univAction;
      if (action) {
        handleAction(action);
        return;
      }
      const core = event.target.closest(".life-map__core");
      if (core) {
        resetCamera();
        return;
      }
      const task = event.target.closest(".universe-task[data-task-id]");
      if (task) {
        state.selectedTaskId = task.dataset.taskId || null;
        updateHud();
        window.requestAnimationFrame(() => focusTask(task));
      }
    });

    frame.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      if (event.target.closest("button, a, input, select, textarea, .universe-task, .constellation-card__header, .life-map__core")) return;
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
      state.zoom = clamp(state.zoom - (event.deltaY * 0.0012), 0.7, 1.7);
      applyCamera();
    }, { passive: false });

    frame.addEventListener("keydown", (event) => {
      if (event.target.closest?.(".life-map__core") && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        resetCamera();
        return;
      }
      if (event.key === "Escape") resetCamera();
      if (event.key === "ArrowLeft") state.yaw -= 4;
      if (event.key === "ArrowRight") state.yaw += 4;
      if (event.key === "ArrowUp") state.pitch = clamp(state.pitch + 3, -24, 24);
      if (event.key === "ArrowDown") state.pitch = clamp(state.pitch - 3, -24, 24);
      if (event.key === "+" || event.key === "=") state.zoom = clamp(state.zoom + 0.1, 0.7, 1.7);
      if (event.key === "-") state.zoom = clamp(state.zoom - 0.1, 0.7, 1.7);
      if (event.key === "0") resetCamera({ keepSelection: true });
      applyCamera();
    });

    mutationObserver = new MutationObserver(() => window.requestAnimationFrame(decorateDepth));
    mutationObserver.observe(graph, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  };

  const showUniv = ({ mode = "overview", taskId = null } = {}) => {
    document.body.classList.add("petit-univ-active");
    ensureHud();
    decorateDepth();
    if (taskId) state.selectedTaskId = String(taskId);
    if (mode === "focus") focusTask();
    else resetCamera({ keepSelection: true });
  };

  const syncInitialArea = () => {
    window.requestAnimationFrame(() => {
      const root = panel();
      if (!root) return;
      const active = !root.hidden
        && root.getAttribute("aria-hidden") !== "true"
        && window.getComputedStyle(root).display !== "none";
      document.body.classList.toggle("petit-univ-active", active);
    });
  };

  const initialize = () => {
    ensureHud();
    decorateDepth();
    bindInteraction();
    applyCamera();
    syncInitialArea();
    window.addEventListener(OPEN_EVENT, (event) => showUniv(event.detail || {}));
    window.addEventListener(AREA_EVENT, (event) => {
      const active = event.detail?.area === "univ";
      document.body.classList.toggle("petit-univ-active", active);
      if (!active) document.body.classList.remove("petit-univ-manage-open");
    });
  };

  window.PetitUnivSpace = {
    initialize,
    reset: resetCamera,
    focusTask: (taskId) => {
      state.selectedTaskId = taskId ? String(taskId) : null;
      focusTask();
    },
    state: () => ({ ...state }),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
