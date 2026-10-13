// PETIT unified UI system: theme, current context, accessibility, and stable spatial motion.
(() => {
  if (!document.querySelector(".universe-shell") || window.PetitUnifiedUI) return;

  const STORAGE_KEY = "petit_ui_theme";
  const root = document.documentElement;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const byId = (id) => document.getElementById(id);
  const text = (value, fallback = "—") => String(value ?? "").trim() || fallback;

  let scheduled = false;
  let contextBar = null;

  const currentTheme = () => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  };

  const themePreference = () => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
  };

  const updateThemeColor = (theme) => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "light" ? "#f3f5f8" : "#07090f";
  };

  const applyTheme = (theme, { persist = true } = {}) => {
    const normalized = theme === "light" ? "light" : "dark";
    root.dataset.theme = normalized;
    if (persist) localStorage.setItem(STORAGE_KEY, normalized);
    updateThemeColor(normalized);

    const toggle = byId("petit-theme-toggle");
    if (!toggle) return;
    const preference = themePreference();
    const next = preference === "system" ? "light" : preference === "light" ? "dark" : "system";
    const labels = { light: "ライト", dark: "ダーク", system: "システム" };
    toggle.textContent = `テーマ: ${labels[preference]}`;
    toggle.setAttribute("aria-label", `${labels[next]}テーマに切り替え`);
    toggle.setAttribute("aria-pressed", String(preference === "light"));
  };

  const installThemeToggle = () => {
    const actions = document.querySelector(".topbar-actions");
    if (!actions || byId("petit-theme-toggle")) return;

    const button = document.createElement("button");
    button.id = "petit-theme-toggle";
    button.className = "petit-theme-toggle";
    button.type = "button";
    button.addEventListener("click", () => {
      const preference = themePreference();
      const next = preference === "system" ? "light" : preference === "light" ? "dark" : "system";
      applyTheme(next === "system" ? currentTheme() : next);
      if (next === "system") localStorage.setItem(STORAGE_KEY, "system");
    });
    actions.prepend(button);
    applyTheme(currentTheme(), { persist: false });
  };

  const installContextBar = () => {
    if (byId("petit-context-bar")) {
      contextBar = byId("petit-context-bar");
      return;
    }

    const main = document.querySelector(".universe-main");
    if (!main) return;

    const bar = document.createElement("details");
    bar.id = "petit-context-bar";
    bar.className = "petit-context-bar";
    bar.setAttribute("aria-label", "ワークセッション");
    bar.innerHTML = `
      <summary aria-controls="petit-work-details"><strong id="petit-context-session">作業なし</strong><span aria-hidden="true">⌄</span></summary>
      <div id="petit-work-details" class="petit-work-details"></div>`;
    const dropdown = bar.querySelector(".petit-work-details");
    const footer = document.querySelector(".focus-footer");
    if (footer) dropdown.appendChild(footer);
    const detail = byId("detail-panel");
    const placeDetail = () => {
      const view = document.querySelector('[data-view-panel].is-active:not([hidden])')?.dataset.viewPanel;
      const spatial = ["universe", "focus"].includes(view);
      const destination = spatial ? document.body : dropdown;
      if (detail && destination && detail.parentElement !== destination) destination.appendChild(detail);
      document.body.classList.toggle("petit-chat-screen", view === "chat");
      scheduleContextUpdate();
    };
    window.addEventListener("petit:panel-change", () => { bar.open = false; placeDetail(); });
    // Covers direct navigation from the original tabs and restored URLs too.
    new MutationObserver(placeDetail).observe(document.querySelector(".universe-main"), {
      subtree: true, attributes: true, attributeFilter: ["hidden"],
    });
    bar.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { bar.open = false; bar.querySelector("summary").focus(); }
    });
    document.addEventListener("pointerdown", (event) => {
      if (bar.open && !bar.contains(event.target)) bar.open = false;
    });
    main.before(bar);
    contextBar = bar;
    placeDetail();
  };

  const updateContext = () => {
    scheduled = false;
    if (!contextBar) return;

    const activeTask = text(byId("active-task-label")?.textContent, "");
    const sessionEl = byId("petit-context-session");
    const paused = byId("work-session-pause")?.textContent === "再開";
    const idle = byId("work-session-end")?.hidden !== false;
    if (sessionEl) {
      const copy = idle ? "作業なし" : `${paused ? "一時停止中" : "作業中"}：${activeTask}`;
      if (sessionEl.textContent !== copy) sessionEl.textContent = copy;
      contextBar.dataset.state = idle ? "idle" : paused ? "paused" : "active";
    }
  };

  const scheduleContextUpdate = () => {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(updateContext);
  };

  const installTabsA11y = () => {
    const tabs = Array.from(document.querySelectorAll(".view-tab[data-view]"));
    const panels = Array.from(document.querySelectorAll("[data-view-panel]"));
    const tablist = document.querySelector(".view-tabs");
    if (tablist) tablist.setAttribute("role", "tablist");

    tabs.forEach((tab) => {
      const name = tab.dataset.view;
      const panel = panels.find((candidate) => candidate.dataset.viewPanel === name);
      if (!panel) return;

      const tabId = `petit-tab-${name}`;
      const panelId = `petit-panel-${name}`;
      tab.id = tabId;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panelId);
      panel.id = panelId;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tabId);
      tab.setAttribute("aria-selected", String(tab.classList.contains("is-active")));
      tab.addEventListener("click", scheduleContextUpdate);
    });
  };

  const decorateDepth = () => {
    document.querySelectorAll(".space-node[data-orbit-index]").forEach((node, index) => {
      const layer = (index % 7) - 3;
      const depth = layer * 7;
      const nextDepth = `${depth}px`;
      const nextScale = (1 + depth / 900).toFixed(3);
      const nextOpacity = (0.92 + Math.max(0, depth) / 450).toFixed(3);

      if (node.style.getPropertyValue("--node-depth") !== nextDepth) {
        node.style.setProperty("--node-depth", nextDepth);
      }
      if (node.style.getPropertyValue("--node-scale") !== nextScale) {
        node.style.setProperty("--node-scale", nextScale);
      }
      if (node.style.getPropertyValue("--node-opacity") !== nextOpacity) {
        node.style.setProperty("--node-opacity", nextOpacity);
      }
    });
  };

  const installSpatialMotion = () => {
    const card = document.querySelector(".orbit-card");
    if (!card) return;

    card.style.setProperty("--orbit-tilt-x", "0deg");
    card.style.setProperty("--orbit-tilt-y", "0deg");
  };

  const installObservers = () => {
    const viewTabs = document.querySelector(".view-tabs");
    if (viewTabs) {
      const tabsObserver = new MutationObserver(() => {
        scheduleContextUpdate();
        document.querySelectorAll(".view-tab[data-view]").forEach((tab) => {
          const nextAria = String(tab.classList.contains("is-active"));
          if (tab.getAttribute("aria-selected") !== nextAria) {
            tab.setAttribute("aria-selected", nextAria);
          }
        });
      });
      tabsObserver.observe(viewTabs, {
        attributes: true,
        attributeFilter: ["class"],
        subtree: true,
      });
    }

    const detailTitle = document.querySelector('#detail-panel [data-detail="title"]');
    const infoTargets = [
      detailTitle,
      byId("active-task-label"),
      byId("active-elapsed"),
      byId("work-session-pause"),
      byId("sync-pill"),
      byId("focus-project-name"),
    ].filter(Boolean);

    if (infoTargets.length > 0) {
      const infoObserver = new MutationObserver(() => {
        scheduleContextUpdate();
      });
      infoTargets.forEach((target) => {
        infoObserver.observe(target, {
          childList: true,
          characterData: true,
          subtree: true,
        });
      });
    }

    const taskNodes = byId("task-nodes");
    if (taskNodes) {
      new MutationObserver(decorateDepth).observe(taskNodes, {
        childList: true,
      });
    }
  };

  const installVisibilityLifecycle = () => {
    const update = () => {
      root.dataset.pageHidden = String(document.hidden);
    };
    document.addEventListener("visibilitychange", update);
    update();
  };

  const installInputMode = () => {
    document.addEventListener("focusin", (event) => {
      if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) {
        document.body.classList.add("is-input-mode");
      }
    });
    document.addEventListener("focusout", () => {
      window.setTimeout(() => {
        const active = document.activeElement;
        if (!(active instanceof HTMLTextAreaElement) && !(active instanceof HTMLInputElement)) {
          document.body.classList.remove("is-input-mode");
        }
      }, 0);
    });
  };

  const initialize = () => {
    applyTheme(currentTheme(), { persist: false });
    const systemTheme = window.matchMedia("(prefers-color-scheme: light)");
    systemTheme.addEventListener?.("change", () => {
      if (themePreference() === "system") applyTheme(currentTheme(), { persist: false });
    });
    installThemeToggle();
    installContextBar();
    installTabsA11y();
    installSpatialMotion();
    installVisibilityLifecycle();
    installInputMode();
    installObservers();
    decorateDepth();
    scheduleContextUpdate();
    window.requestAnimationFrame(() => {
      root.dataset.uiReady = "true";
    });
  };

  window.PetitUnifiedUI = {
    applyTheme,
    refresh: () => {
      decorateDepth();
      scheduleContextUpdate();
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
