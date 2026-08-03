// Shared PETIT application shell for Universe UI.
(() => {
  const HOME_VIEW = "today";
  const ASSET_VERSION = window.PETIT_ASSET_VERSION || "0.10.0";
  const PRIMARY_VIEWS = [
    { view: "today", label: "Home" },
    { view: "focus", label: "Focus" },
    { view: "tasks", label: "Tasks" },
    { view: "chat", label: "PETIT" },
  ];
  const VIEW_ALIASES = {
    home: "today",
    petit: "chat",
    projects: "universe",
    reminders: "reminders",
  };

  const activateView = (view) => {
    const resolved = VIEW_ALIASES[view] || view;
    const target = document.querySelector(`[data-view="${resolved}"]`);
    if (target) target.click();
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
    loadScript("/static/life-map.js", "life-map-script");
    loadScript("/static/task-flow.js", "task-flow-script");
  };

  const relabelNavigation = (nav) => {
    const buttons = new Map(
      Array.from(nav.querySelectorAll("[data-view]")).map((button) => [button.dataset.view, button]),
    );

    PRIMARY_VIEWS.forEach(({ view, label }) => {
      const button = buttons.get(view);
      if (!button) return;
      button.hidden = false;
      button.textContent = label;
      button.dataset.primaryArea = label.toLowerCase();
      nav.appendChild(button);
    });

    Array.from(buttons.entries()).forEach(([view, button]) => {
      button.hidden = !PRIMARY_VIEWS.some((item) => item.view === view);
    });
  };

  const createDesktopRail = (nav) => {
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
      <button type="button" data-shell-target="universe">Projects</button>
      <button type="button" data-shell-target="reminders">Reminders</button>
      <button type="button" data-shell-target="chat">Settings</button>
    `;
    shortcuts.querySelectorAll("[data-shell-target]").forEach((button) => {
      button.addEventListener("click", () => activateView(button.dataset.shellTarget));
    });
    rail.appendChild(shortcuts);

    document.body.appendChild(rail);

    nav.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => syncActiveState(button.dataset.view));
    });
  };

  const syncActiveState = (view) => {
    document.querySelectorAll("[data-rail-view]").forEach((button) => {
      const active = button.dataset.railView === view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
  };

  const installHomeShortcuts = () => {
    const homePanel = document.querySelector('[data-view-panel="today"]');
    if (!homePanel || homePanel.querySelector(".home-area-shortcuts")) return;

    const shortcuts = document.createElement("section");
    shortcuts.className = "home-area-shortcuts";
    shortcuts.setAttribute("aria-label", "Homeの追加情報");
    shortcuts.innerHTML = `
      <button type="button" data-home-target="universe"><span>PROJECTS</span><strong>プロジェクト状況を見る</strong></button>
      <button type="button" data-home-target="reminders"><span>REMINDERS</span><strong>直近のリマインダーを見る</strong></button>
      <button type="button" data-home-target="chat"><span>PETIT</span><strong>PETITに相談する</strong></button>
    `;
    shortcuts.querySelectorAll("[data-home-target]").forEach((button) => {
      button.addEventListener("click", () => activateView(button.dataset.homeTarget));
    });
    const header = homePanel.querySelector(".section-head");
    if (header) header.insertAdjacentElement("afterend", shortcuts);
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
    createDesktopRail(nav);
    installHomeShortcuts();
    installPetitSubnav();

    const requested = new URLSearchParams(window.location.search).get("view");
    const supported = [
      ...PRIMARY_VIEWS.map((item) => item.view),
      "universe",
      "reminders",
      ...Object.keys(VIEW_ALIASES),
    ];
    const initialView = requested && supported.includes(requested) ? requested : HOME_VIEW;
    window.requestAnimationFrame(() => {
      activateView(initialView);
      syncActiveState(VIEW_ALIASES[initialView] || initialView);
    });
  };

  window.PetitAppShell = { initialize, activateView, homeView: HOME_VIEW };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
