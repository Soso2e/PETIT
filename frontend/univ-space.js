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

  const touchPoints = new Map();
  const coarsePointer = window.matchMedia("(pointer: coarse)");
  let pinchStartDistance = 0;
  let pinchStartZoom = 1;
  let mutationObserver = null;
  let decorateQueued = false;

  const panel = () => document.querySelector('[data-view-panel="universe"]');
  const map = () => document.querySelector("#constellation-grid");
  const viewport = () => document.querySelector(".univ-viewport");
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const text = (value, fallback = "") => String(value ?? "").trim() || fallback;

  const isPanelActive = () => {
    const root = panel();
    return root && !root.hidden && root.getAttribute("aria-hidden") !== "true";
  };

  const systemNode = (element) => element?.closest?.(".univ-task-system") || null;
  const planetNode = (system) => system?.querySelector(".univ-task-planet") || null;
  const satelliteNodes = (system) => Array.from(system?.querySelectorAll(".univ-satellite") || []);

  const applyCamera = () => {
    if (!isPanelActive()) return;
    const graph = map();
    if (!graph) return;
    graph.style.setProperty("--univ-yaw", `${state.yaw}deg`);
    graph.style.setProperty("--univ-pitch", `${state.pitch}deg`);
    graph.style.setProperty("--inv-yaw", `${-state.yaw}deg`);
    graph.style.setProperty("--inv-pitch", `${-state.pitch}deg`);
    graph.style.setProperty("--univ-zoom", String(state.zoom));
    graph.style.setProperty("--univ-pan-x", `${state.panX}px`);
    graph.style.setProperty("--univ-pan-y", `${state.panY}px`);
    graph.dataset.univMode = state.mode;
  };

  const selectedTask = () => {
    const graph = map();
    if (!graph || !state.selectedTaskId) return null;
    return graph.querySelector(`[data-task-id="${CSS.escape(String(state.selectedTaskId))}"]`);
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

  const installTouchStyles = () => {
    if (!coarsePointer.matches || document.querySelector("#petit-univ-touch-styles")) return;
    const style = document.createElement("style");
    style.id = "petit-univ-touch-styles";
    style.textContent = `
      @media (pointer: coarse) {
        .univ-hud button,
        .univ-detail-dismiss {
          min-width: 44px;
          min-height: 44px;
        }
        .univ-hud__controls button:nth-child(2),
        .univ-hud__controls button:nth-child(3) {
          width: 44px;
        }
      }
    `;
    document.head.appendChild(style);
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
            <button type="button" data-univ-action="manage" disabled>詳細</button>
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

    const help = frame.querySelector(".univ-hud__help");
    if (help && coarsePointer.matches) help.textContent = "Tap: focus · Drag: orbit · Pinch: zoom";
    installTouchStyles();

    if (!document.querySelector(".univ-detail-dismiss")) {
      const dismiss = document.createElement("button");
      dismiss.type = "button";
      dismiss.className = "univ-detail-dismiss";
      dismiss.textContent = "閉じる";
      dismiss.addEventListener("click", () => document.body.classList.remove("petit-univ-manage-open"));
      document.body.appendChild(dismiss);
    }

    const eyebrow = root.querySelector(".universe-section-head .eyebrow");
    const heading = root.querySelector(".universe-section-head h1");
    const copy = root.querySelector(".universe-section-head p");
    if (eyebrow) eyebrow.textContent = "UNIV";
    if (heading) heading.textContent = "Core / Planet / Satellite";
    if (copy) copy.textContent = "中心惑星Core、親タスク惑星、子タスク衛星からなる空間で直接操作・フォーカスできます。";
    return frame;
  };

  const decorateScene = () => {
    decorateQueued = false;
    if (!isPanelActive()) return;
    const graph = map();
    if (!graph) return;
    graph.classList.add("univ-space");
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

  const centerSystem = (system) => {
    const frame = viewport();
    if (!frame || !system) return;
    state.panX = 0;
    state.panY = 0;
    applyCamera();
    window.requestAnimationFrame(() => {
      const targetRect = system.getBoundingClientRect();
      const frameRect = frame.getBoundingClientRect();
      state.panX = clamp((frameRect.left + frameRect.width / 2) - (targetRect.left + targetRect.width / 2), -520, 520);
      state.panY = clamp((frameRect.top + frameRect.height / 2) - (targetRect.top + targetRect.height / 2), -360, 360);
      applyCamera();
    });
  };

  const focusSystem = (system, target = null) => {
    if (!system) return;
    clearFocusClasses();
    state.mode = "focus";
    state.selectedSystemKey = system.dataset.rootTaskId || system.dataset.univProject || null;
    state.selectedTaskId = target ? target.dataset.taskId : planetNode(system)?.dataset.taskId;
    state.yaw = 0;
    state.pitch = 3;
    state.zoom = target ? 1.42 : 1.34;
    system.classList.add("is-univ-focus-family");
    if (target) target.classList.add("is-univ-focus-target");
    applyCamera();
    centerSystem(system);

    const project = system.dataset.univProject || "Project";
    const planetTitle = text(planetNode(system)?.querySelector("strong")?.textContent, project);
    if (target) {
      const targetTitle = text(target.querySelector(".universe-task__title")?.textContent, "子タスク");
      setHud({
        project,
        title: targetTitle,
        description: `「${planetTitle}」を周回する子タスク衛星です。`,
        canManage: true,
      });
    } else {
      setHud({
        project,
        title: planetTitle,
        description: `親タスク惑星です。周囲の${satelliteNodes(system).length}個の衛星が子タスクです。`,
        canManage: Boolean(planetNode(system)?.dataset.taskId),
      });
    }
  };

  const focusByTaskId = (requestedTaskId, { satellite = false, project = "" } = {}) => {
    const graph = map();
    if (!graph) return;
    scheduleDecorate();
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      let task = requestedTaskId
        ? graph.querySelector(`[data-task-id="${CSS.escape(String(requestedTaskId))}"]`)
        : null;
      let system = systemNode(task);
      if (!system && project) {
        system = Array.from(graph.querySelectorAll(":scope > .univ-task-system"))
          .find((candidate) => candidate.dataset.univProject === project)
          || null;
        task = planetNode(system);
      }
      focusSystem(system, satellite ? task : null);
    }));
  };

  const focusCurrent = () => {
    const graph = map();
    if (!graph || !state.selectedSystemKey) return;
    const system = graph.querySelector(`.univ-task-system[data-root-task-id="${CSS.escape(String(state.selectedSystemKey))}"]`)
      || graph.querySelector(`.univ-task-system[data-univ-project="${CSS.escape(String(state.selectedSystemKey))}"]`);
    const task = selectedTask();
    focusSystem(system, task?.classList.contains("univ-satellite") ? task : null);
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
      if (!isPanelActive()) return;
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

      const satellite = target.closest(".univ-satellite[data-task-id]");
      if (satellite) {
        const requestedTaskId = satellite.dataset.taskId;
        state.selectedTaskId = requestedTaskId;
        state.selectedSystemKey = systemNode(satellite)?.dataset.rootTaskId || systemNode(satellite)?.dataset.univProject || null;
        focusByTaskId(requestedTaskId, { satellite: true });
        return;
      }

      const planet = target.closest(".univ-task-planet");
      if (planet) {
        const system = systemNode(planet);
        const requestedTaskId = planet.dataset.taskId;
        const project = system?.dataset.univProject || "";
        state.selectedTaskId = requestedTaskId;
        state.selectedSystemKey = system?.dataset.rootTaskId || project;
        focusByTaskId(requestedTaskId, { project });
      }
    }, true);
  };

  const touchDistance = () => {
    const points = Array.from(touchPoints.values());
    if (points.length !== 2) return 0;
    return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  };

  const stopDrag = (frame, pointerId = null) => {
    state.dragging = false;
    state.pointerId = null;
    frame.classList.remove("is-dragging");
    if (pointerId != null) frame.releasePointerCapture?.(pointerId);
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
      if (!isPanelActive() || event.button !== 0) return;

      if (event.pointerType === "touch") {
        touchPoints.set(event.pointerId, { x: event.clientX, y: event.clientY });
        frame.setPointerCapture?.(event.pointerId);
        if (touchPoints.size === 2) {
          stopDrag(frame);
          pinchStartDistance = touchDistance();
          pinchStartZoom = state.zoom;
          return;
        }
        if (touchPoints.size > 2) return;
      }

      if (event.target.closest("button, a, input, select, textarea, .life-map__core")) return;
      state.dragging = true;
      state.pointerId = event.pointerId;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      frame.setPointerCapture?.(event.pointerId);
      frame.classList.add("is-dragging");
    });

    frame.addEventListener("pointermove", (event) => {
      if (event.pointerType === "touch" && touchPoints.has(event.pointerId)) {
        touchPoints.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (touchPoints.size === 2) {
          const distance = touchDistance();
          if (distance && pinchStartDistance) {
            state.zoom = clamp(pinchStartZoom * (distance / pinchStartDistance), 0.68, 1.72);
            applyCamera();
          }
          return;
        }
      }

      if (!state.dragging || state.pointerId !== event.pointerId) return;
      const dx = event.clientX - state.lastX;
      const dy = event.clientY - state.lastY;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      const yawSensitivity = event.pointerType === "touch" ? 0.075 : 0.11;
      const pitchSensitivity = event.pointerType === "touch" ? 0.06 : 0.09;
      state.yaw += dx * yawSensitivity;
      state.pitch = clamp(state.pitch - (dy * pitchSensitivity), -24, 24);
      applyCamera();
    });

    const endPointer = (event) => {
      if (event.pointerType === "touch") {
        touchPoints.delete(event.pointerId);
        if (touchPoints.size < 2) {
          pinchStartDistance = 0;
          pinchStartZoom = state.zoom;
        }
      }
      if (state.pointerId === event.pointerId) stopDrag(frame, event.pointerId);
      else frame.releasePointerCapture?.(event.pointerId);
    };
    frame.addEventListener("pointerup", endPointer);
    frame.addEventListener("pointercancel", endPointer);

    frame.addEventListener("wheel", (event) => {
      if (!isPanelActive()) return;
      event.preventDefault();
      state.zoom = clamp(state.zoom - (event.deltaY * 0.0012), 0.68, 1.72);
      applyCamera();
    }, { passive: false });

    frame.addEventListener("keydown", (event) => {
      if (!isPanelActive()) return;
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
  };

  const showUniv = ({ mode = "overview", taskId: requestedTaskId = null } = {}) => {
    document.body.classList.add("petit-univ-active");
    ensureHud();
    scheduleDecorate();
    if (mode === "focus" && requestedTaskId) {
      state.selectedTaskId = String(requestedTaskId);
      window.requestAnimationFrame(() => {
        const task = selectedTask();
        focusSystem(systemNode(task), task?.classList.contains("univ-satellite") ? task : null);
      });
      return;
    }
    resetCamera();
  };

  const syncInitialArea = () => {
    window.requestAnimationFrame(() => {
      const active = isPanelActive();
      document.body.classList.toggle("petit-univ-active", active);
      if (active) resetCamera();
    });
  };

  const initialize = () => {
    ensureHud();
    bindInteraction();
    installSelectionCapture();
    window.addEventListener("petit:universe-rendered", scheduleDecorate);
    syncInitialArea();
    window.addEventListener(OPEN_EVENT, (event) => showUniv(event.detail || {}));
    window.addEventListener(AREA_EVENT, (event) => {
      const active = event.detail?.area === "univ" || isPanelActive();
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
      focusSystem(systemNode(task), task?.classList.contains("univ-satellite") ? task : null);
    },
    state: () => ({ ...state }),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();