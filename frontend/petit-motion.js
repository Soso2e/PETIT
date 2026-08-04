// PETIT Simple View Motion v0.14.1
// View changes use a short, ordinary fade. No shared-element or depth transition.
(() => {
  if (!document.querySelector(".universe-shell") || window.PetitMotion) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let previousView = "";
  let animationFrame = null;

  const activePanel = () => document.querySelector("[data-view-panel].is-active:not([hidden])");
  const activeView = () => activePanel()?.dataset.viewPanel || "";

  const replayViewFade = (panel) => {
    if (!(panel instanceof HTMLElement) || reducedMotion.matches) return;
    panel.classList.remove("petit-view-fade");
    void panel.offsetWidth;
    panel.classList.add("petit-view-fade");
    panel.addEventListener("animationend", () => panel.classList.remove("petit-view-fade"), { once: true });
  };

  const updateActiveView = () => {
    if (animationFrame != null) cancelAnimationFrame(animationFrame);
    animationFrame = requestAnimationFrame(() => {
      animationFrame = null;
      const panel = activePanel();
      const view = panel?.dataset.viewPanel || "";
      if (!panel || !view || view === previousView) return;
      previousView = view;
      replayViewFade(panel);
    });
  };

  const installPanelObserver = () => {
    const main = document.querySelector(".universe-main");
    if (!main) return;
    new MutationObserver(updateActiveView).observe(main, {
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "hidden"],
    });
  };

  const installIndicator = () => {
    const nav = document.querySelector(".view-tabs");
    if (!nav) return;

    let indicator = nav.querySelector(".petit-tab-indicator");
    if (!indicator) {
      indicator = document.createElement("span");
      indicator.className = "petit-tab-indicator";
      indicator.setAttribute("aria-hidden", "true");
      nav.prepend(indicator);
    }

    const update = () => {
      const active = nav.querySelector('.view-tab[data-view].is-active, .view-tab[data-view][aria-selected="true"]');
      if (!(active instanceof HTMLElement)) return;
      const navRect = nav.getBoundingClientRect();
      const rect = active.getBoundingClientRect();
      nav.style.setProperty("--tab-indicator-x", `${rect.left - navRect.left}px`);
      nav.style.setProperty("--tab-indicator-y", `${rect.top - navRect.top}px`);
      nav.style.setProperty("--tab-indicator-width", `${rect.width}px`);
      nav.style.setProperty("--tab-indicator-height", `${rect.height}px`);
      indicator.dataset.ready = "true";
    };

    new MutationObserver(update).observe(nav, {
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "aria-selected", "hidden"],
      childList: true,
    });
    window.addEventListener("resize", update, { passive: true });
    update();
  };

  const installTaskFeedback = () => {
    document.addEventListener("click", (event) => {
      const button = event.target instanceof Element ? event.target.closest(".task-check") : null;
      const row = button?.closest("tr");
      if (!button || !row) return;
      row.classList.add("is-completing");
      window.setTimeout(() => row.classList.remove("is-completing"), 480);
    }, true);
  };

  const transitionToView = (view) => {
    const tab = document.querySelector(`.view-tab[data-view="${CSS.escape(String(view || ""))}"]`);
    if (tab instanceof HTMLButtonElement) tab.click();
    return Promise.resolve(Boolean(tab));
  };

  const transitionTaskToFocus = (source) => {
    const element = source instanceof Element ? source : null;
    const taskId = element?.dataset.taskId
      || element?.closest("[data-task-id]")?.dataset.taskId
      || element?.closest("[data-root-task-id]")?.dataset.rootTaskId;
    if (!taskId || !window.PetitUniverse?.focusTask) return Promise.resolve(false);
    return Promise.resolve(window.PetitUniverse.focusTask(taskId));
  };

  const initialize = () => {
    previousView = activeView();
    installPanelObserver();
    installIndicator();
    installTaskFeedback();
    document.documentElement.dataset.petitMotionReady = "true";
  };

  window.PetitMotion = {
    transitionToView,
    transitionTaskToFocus,
    refresh: updateActiveView,
    cancel: () => undefined,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
