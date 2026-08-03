// Shared PETIT application shell for Universe UI.
(() => {
  const HOME_VIEW = "universe";
  const ASSET_VERSION = window.PETIT_ASSET_VERSION || "0.11.0";
  const PRIMARY_VIEWS = [
    { view: "home", target: "universe", label: "Home" },
    { view: "focus", target: "universe", label: "Focus" },
    { view: "tasks", target: "tasks", label: "Tasks" },
    { view: "chat", target: "chat", label: "PETIT" },
  ];
  const VIEW_ALIASES = {
    home: "universe",
    petit: "chat",
    projects: "universe",
    reminders: "reminders",
  };

  const clickPanelTrigger = (view) => {
    const target = document.querySelector(`[data-view="${view}"]`);
    if (target) target.click();
  };

  const activateView = (view) => {
    const area = view === "focus" ? "focus" : (view === "home" || view === "universe" ? "home" : view);
    const resolved = VIEW_ALIASES[view] || view;
    const panelView = area === "focus" ? "universe" : resolved;
    clickPanelTrigger(panelView);

    window.requestAnimationFrame(() => {
      if (area === "focus") {
        window.dispatchEvent(new CustomEvent("petit:core-focus"));
      } else if (area === "home") {
        window.dispatchEvent(new CustomEvent("petit:core-home"));
      }
      syncActiveState(area);
    });
  };

  const loadStylesheet = (href, marker) => {
    if (document.querySelector(`link[data-petit-module="${marker}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `${href}?v=${ASSET_VERSION}`;
    link.dataset.petitModule = marker;
    document.head.appendChild(link);
  };

  const loadScript = (src, marker) => {
    if (document.querySelector(`script[data-petit-module="${marker}"]`)) return;
    const script = document.createElement("script");
    script.src = `${src}?v=${ASSET_VERSION}`;
    script.async = false;
    script.dataset.petitModule = marker;
    document.head.appendChild(script);
  };

  const installUniverseModules = () => {
    loadStylesheet("/static/today.css", "today-style");
    if (!document.querySelector('[data-view-panel="universe"]')) return;
    loadStylesheet("/static/life-map.css", "life-map-style");
    loadStylesheet("/static/life-transition.css", "life-transition-style");
    loadStylesheet("/static/task-flow.css", "task-flow-style");
    loadStylesheet("/static/petit-galaxy.css", "galactic-spatial-style");
    loadStylesheet("/static/petit-four-area-shell.css", "four-area-shell-style");
    loadStylesheet("/static/core-home.css", "core-home-style");
    loadScript("/static/life-map.js", "life-map-script");
    loadScript("/static/task-flow.js", "task-flow-script");
    loadScript("/static/core-home.js", "core-home-script");
  };

  const relabelNavigation = (nav) => {
    const buttons = new Map(
      Array.from(nav.querySelectorAll("[data-view]")).map((button) => [button.dataset.view, button]),
    );
    const source = {
      home: buttons.get("today") || buttons.get("universe"),
      focus: buttons.get("focus"),
      tasks: buttons.get("tasks"),
      chat: buttons.get("chat"),
    };

    PRIMARY_VIEWS.forEach(({ view, label }) => {
      const button = source[view];
      if (!button) return;
      button.hidden = false;
      button.textContent = label;
      button.dataset.primaryArea = view;
      button.dataset.shellArea = view;
      nav.appendChild(button);
    });

    Array.from(buttons.values()).forEach((button) => {
      button.hidden = !Object.values(source).includes(button);
    });

    nav.addEventListener("click", (event) => {
      const button = event.target.closest("[data-shell-area]");
      if (!button) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      activateView(button.dataset.shellArea);
    }, true);
  };

  const createDesktopRail = () => {
    if (document.querySelector(".petit-area-rail")) return;
    const rail = document.createElement("aside");
    rail.className = "petit-area-rail";
    rail.setAttribute("aria-label", "PETIT主要領域");

    const brand = document.createElement("a");
    brand.className = "petit-area-rail__brand";
    brand.href = "/";
    brand.innerHTML = '<img src="/static/branding/icon_logo.png" alt=""><span><strong>PETIT</strong><small data-petit-version></small></span>';
    rail.appendChild(brand);

    const railNav = document.createElement("nav");
    railNav.className = "petit-area-rail__nav";
    PRIMARY_VIEWS.forEach(({ view, label }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.railView = view;
      button.textContent = label;
      button.addEventListener("click", () => activateView(view));
      railNav.appendChild(button);
    });
    rail.appendChild(railNav);

    const shortcuts = document.createElement("div");
    shortcuts.className = "petit-area-rail__shortcuts";
    shortcuts.innerHTML = `
      <button type="button" data-shell-target="home">Projects</button>
      <button type="button" data-shell-target="reminders">Reminders</button>
      <button type="button" data-shell-target="chat">Settings</button>
    `;
    shortcuts.querySelectorAll("[data-shell-target]").forEach((button) => {
      button.addEventListener("click", () => activateView(button.dataset.shellTarget));
    });
    rail.appendChild(shortcuts);
    document.body.appendChild(rail);
  };

  const syncActiveState = (view) => {
    const area = view === "universe" ? "home" : view;
    document.querySelectorAll("[data-rail-view], [data-shell-area]").forEach((button) => {
      const key = button.dataset.railView || button.dataset.shellArea;
      const active = key === area;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
  };

  const installPetitSubnav = () => {
    const panel = document.querySelector('[data-view-panel="chat"]');
    if (!panel || panel.querySelector(".petit-subnav")) return;
    const subnav = document.createElement("nav");
    subnav.className = "petit-subnav";
    subnav.setAttribute("aria-label", "PETIT機能");
    subnav.innerHTML = `
      <button type="button" class="is-active">Chat</button>
      <button type="button" disabled>Voice</button>
      <button type="button" disabled>Context</button>
      <button type="button" disabled>History</button>
      <button type="button" disabled>Automations</button>
      <button type="button" disabled>Settings</button>
    `;
    panel.prepend(subnav);
  };

  const initialize = () => {
    const nav = document.querySelector(".view-tabs");
    if (!nav || nav.dataset.petitAppShellReady === "true") return;
    nav.dataset.petitAppShellReady = "true";

    relabelNavigation(nav);
    installUniverseModules();
    createDesktopRail();
    installPetitSubnav();

    const requested = new URLSearchParams(window.location.search).get("view");
    const supported = ["home", "focus", "tasks", "chat", "universe", "reminders", "petit", "projects"];
    const initialView = requested && supported.includes(requested) ? requested : "home";
    window.requestAnimationFrame(() => activateView(initialView));
  };

  window.PetitAppShell = { initialize, activateView, homeView: HOME_VIEW };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
