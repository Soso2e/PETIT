// Home and Focus share one Core-centered task universe.
(() => {
  const FOCUS_EVENT = "petit:core-focus";
  const HOME_EVENT = "petit:core-home";
  let focusTaskId = null;

  const panel = () => document.querySelector('[data-view-panel="universe"]');
  const map = () => document.querySelector("#constellation-grid");

  const ensureCopy = () => {
    const root = panel();
    if (!root) return;
    const eyebrow = root.querySelector(".universe-section-head .eyebrow");
    const title = root.querySelector(".universe-section-head h1");
    const copy = root.querySelector(".universe-section-head p");
    const core = root.querySelector(".life-map__core");
    if (eyebrow) eyebrow.textContent = "HOME / CORE";
    if (title) title.textContent = "Core";
    if (copy) copy.textContent = "Coreを中心に、いま動いているProjectとTaskを眺めます。星を選ぶとFocusします。";
    if (core) {
      const coreEyebrow = core.querySelector(".eyebrow");
      const coreTitle = core.querySelector("strong");
      const coreHint = core.querySelector("small");
      if (coreEyebrow) coreEyebrow.textContent = "YOUR UNIVERSE";
      if (coreTitle) coreTitle.textContent = "CORE";
      if (coreHint) coreHint.textContent = "Home · Select a star to Focus";
    }
  };

  const taskNodeById = (id) => {
    if (!id) return null;
    return map()?.querySelector(`[data-task-id="${CSS.escape(String(id))}"]`) || null;
  };

  const projectNodeForTask = (task) => task?.closest(".constellation-card") || null;

  const setMode = (mode, taskId = null) => {
    const root = panel();
    const graph = map();
    if (!root || !graph) return;
    ensureCopy();

    focusTaskId = mode === "focus" ? taskId : null;
    root.dataset.coreMode = mode;
    graph.classList.toggle("is-core-focus", mode === "focus");
    graph.classList.toggle("is-core-home", mode !== "focus");

    graph.querySelectorAll(".is-core-focus-target, .is-core-focus-family").forEach((node) => {
      node.classList.remove("is-core-focus-target", "is-core-focus-family");
    });

    if (mode !== "focus") return;

    const target = taskNodeById(taskId)
      || graph.querySelector(".universe-task.is-selected")
      || graph.querySelector(".universe-task");
    const family = projectNodeForTask(target)
      || graph.querySelector(".constellation-card.is-selected")
      || graph.querySelector(".constellation-card");

    target?.classList.add("is-core-focus-target");
    family?.classList.add("is-core-focus-family");
    target?.focus?.({ preventScroll: true });
  };

  const focusFromSelection = () => {
    const selected = map()?.querySelector(".universe-task.is-selected, .constellation-card.is-selected .universe-task");
    setMode("focus", selected?.dataset.taskId || focusTaskId);
  };

  const bindGraph = () => {
    const graph = map();
    if (!graph || graph.dataset.coreHomeReady === "true") return;
    graph.dataset.coreHomeReady = "true";
    graph.classList.add("is-core-home");

    graph.addEventListener("click", (event) => {
      const task = event.target.closest(".universe-task[data-task-id]");
      if (!task) return;
      window.requestAnimationFrame(() => setMode("focus", task.dataset.taskId));
    });

    graph.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      window.PetitAppShell?.activateView?.("home");
    });

    const observer = new MutationObserver(() => {
      ensureCopy();
      if (panel()?.dataset.coreMode === "focus") focusFromSelection();
    });
    observer.observe(graph, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  };

  const initialize = () => {
    ensureCopy();
    bindGraph();
    window.addEventListener(HOME_EVENT, () => setMode("home"));
    window.addEventListener(FOCUS_EVENT, (event) => setMode("focus", event.detail?.taskId));
  };

  window.PetitCoreHome = {
    initialize,
    showHome: () => setMode("home"),
    showFocus: (taskId) => setMode("focus", taskId),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
