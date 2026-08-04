// Shared PETIT application shell for the Univ-first UI.
(() => {
  if (window.PetitAppShell?.initialized) return;
  const HOME_VIEW = "universe";
  const ASSET_VERSION = window.PETIT_ASSET_VERSION || "0.14.1";
  const PRIMARY_VIEWS = [
    { view: "univ", target: "universe", label: "Univ" },
    { view: "tasks", target: "tasks", label: "Tasks" },
    { view: "chat", target: "chat", label: "PETIT" },
  ];
  const VIEW_ALIASES = {
    home: "univ",
    focus: "univ",
    universe: "univ",
    projects: "univ",
    petit: "chat",
    reminders: "reminders",
  };

  const resolveArea = (view) => VIEW_ALIASES[view] || view;
  const panelForArea = (area) => area === "univ" ? "universe" : area;

  const switchPanelDirectly = (panelView) => {
    const tabs = Array.from(document.querySelectorAll("[data-view]"));
    const panels = Array.from(document.querySelectorAll("[data-view-panel]"));
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    tabs.forEach((tab) => {
      const active = tab.dataset.view === panelView;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });

    panels.forEach((panel) => {
      const active = panel.dataset.viewPanel === panelView;
      panel.hidden = !active;
      panel.setAttribute("aria-hidden", String(!active));
      panel.classList.toggle("is-active", active);
      panel.classList.remove("is-entering");
      if (active && panel.dataset.motionSeen !== "true" && !reducedMotion) {
        panel.dataset.motionSeen = "true";
        panel.classList.add("is-entering");
        panel.addEventListener("animationend", () => panel.classList.remove("is-entering"), { once: true });
      }
    });

    if (panelView === "chat") {
      window.requestAnimationFrame(() => document.querySelector("#chat-input")?.focus?.());
    }

    window.dispatchEvent(new CustomEvent("petit:panel-change", {
      detail: { panel: panelView },
    }));
  };

  const syncUrl = (area) => {
    const url = new URL(window.location.href);
    url.searchParams.set("view", area);
    window.history.replaceState({ petitArea: area }, "", url);
  };

  const activateView = (view, detail = {}) => {
    const area = resolveArea(view);
    const panelView = panelForArea(area);

    // Do not click the relabelled tab again. That path can re-enter the shell
    // capture handler and leave the old panel visible. Keep one source of truth.
    switchPanelDirectly(panelView);
    syncActiveState(area);
    syncUrl(area);

    window.requestAnimationFrame(() => {
      if (area === "univ") {
        window.dispatchEvent(new CustomEvent("petit:univ-open", {
          detail: {
            mode: view === "focus" ? "focus" : (detail.mode || "overview"),
            taskId: detail.taskId || null,
          },
        }));
      }
      window.dispatchEvent(new CustomEvent("petit:area-change", { detail: { area } }));
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
    loadStylesheet("/static/petit-four-area-shell.css", "three-area-shell-style");
    loadStylesheet("/static/univ-space.css", "univ-space-style");
    loadScript("/static/life-map.js", "life-map-script");
    loadScript("/static/task-flow.js", "task-flow-script");
    loadScript("/static/univ-space.js", "univ-space-script");
  };

  const relabelNavigation = (nav) => {
    const buttons = new Map(
      Array.from(nav.querySelectorAll("[data-view]")).map((button) => [button.dataset.view, button]),
    );
    const source = {
      univ: buttons.get("universe") || buttons.get("today"),
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
    brand.href = "/?view=univ";
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
    const area = resolveArea(view);
    document.querySelectorAll("[data-rail-view], [data-shell-area]").forEach((button) => {
      const key = button.dataset.railView || button.dataset.shellArea;
      const active = key === area;
      if (button.classList.contains("is-active") !== active) {
        button.classList.toggle("is-active", active);
      }
      const nextAria = active ? "page" : "false";
      if (button.getAttribute("aria-current") !== nextAria) {
        button.setAttribute("aria-current", nextAria);
      }
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

  const installPanelObserver = () => {
    const panels = Array.from(document.querySelectorAll("[data-view-panel]"));
    if (!panels.length) return;
    const observer = new MutationObserver(() => {
      const visible = panels.find((panel) => !panel.hidden);
      if (!visible) return;
      const area = visible.dataset.viewPanel === "universe" ? "univ" : visible.dataset.viewPanel;
      syncActiveState(area);
      const isUniv = area === "univ";
      if (document.body.classList.contains("petit-univ-active") !== isUniv) {
        document.body.classList.toggle("petit-univ-active", isUniv);
      }
    });
    panels.forEach((panel) => observer.observe(panel, {
      attributes: true,
      attributeFilter: ["hidden", "class"],
    }));
  };

  const initialize = () => {
    const nav = document.querySelector(".view-tabs");
    if (!nav || nav.dataset.petitAppShellReady === "true") return;
    nav.dataset.petitAppShellReady = "true";

    relabelNavigation(nav);
    installUniverseModules();
    createDesktopRail();
    installPetitSubnav();
    installPanelObserver();

    const requested = new URLSearchParams(window.location.search).get("view");
    const supported = ["univ", "home", "focus", "tasks", "chat", "universe", "reminders", "petit", "projects"];
    const initialView = requested && supported.includes(requested) ? requested : "univ";
    window.requestAnimationFrame(() => activateView(initialView));
  };

  window.addEventListener("popstate", (event) => {
    const requested = event.state?.petitArea || new URLSearchParams(window.location.search).get("view") || "univ";
    activateView(requested);
  });
  window.addEventListener("petit:navigate", (event) => activateView(event.detail?.view || "univ", event.detail || {}));

  window.PetitAppShell = { initialize, activateView, homeView: HOME_VIEW, initialized: true };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
