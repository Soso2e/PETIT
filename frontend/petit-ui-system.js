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
    const next = normalized === "light" ? "dark" : "light";
    toggle.textContent = normalized === "light" ? "Dark" : "Light";
    toggle.setAttribute("aria-label", `${next === "light" ? "ライト" : "ダーク"}テーマに切り替え`);
    toggle.setAttribute("aria-pressed", String(normalized === "light"));
  };

  const installThemeToggle = () => {
    const actions = document.querySelector(".topbar-actions");
    if (!actions || byId("petit-theme-toggle")) return;

    const button = document.createElement("button");
    button.id = "petit-theme-toggle";
    button.className = "petit-theme-toggle";
    button.type = "button";
    button.addEventListener("click", () => {
      applyTheme(root.dataset.theme === "light" ? "dark" : "light");
    });
    actions.prepend(button);
    applyTheme(currentTheme(), { persist: false });
  };

  const createContextItem = (label, id) => {
    const item = document.createElement("div");
    item.className = "petit-context-item";
    item.innerHTML = `<span>${label}</span><strong id="${id}">—</strong>`;
    return item;
  };

  const installContextBar = () => {
    if (byId("petit-context-bar")) {
      contextBar = byId("petit-context-bar");
      return;
    }

    const main = document.querySelector(".universe-main");
    if (!main) return;

    const bar = document.createElement("section");
    bar.id = "petit-context-bar";
    bar.className = "petit-context-bar";
    bar.setAttribute("aria-label", "現在のPETIT状態");
    bar.append(
      createContextItem("View", "petit-context-view"),
      createContextItem("Current", "petit-context-current"),
      createContextItem("Work session", "petit-context-session"),
      createContextItem("Sync", "petit-context-sync"),
    );
    main.before(bar);
    contextBar = bar;
  };

  const activeTab = () => (
    document.querySelector(".view-tab.is-active")
    || document.querySelector('[aria-selected="true"]')
  );

  const updateContext = () => {
    scheduled = false;
    if (!contextBar) return;

    const tab = activeTab();
    const viewName = text(tab?.textContent, "PETIT");
    const detailTitle = text(document.querySelector('#detail-panel [data-detail="title"]')?.textContent, "");
    const project = text(byId("focus-project-name")?.textContent, "");
    const activeTask = text(byId("active-task-label")?.textContent, "");
    const elapsed = text(byId("active-elapsed")?.textContent, "");
    const sync = text(byId("sync-pill")?.textContent, "同期状態を確認中");

    const viewEl = byId("petit-context-view");
    const currentEl = byId("petit-context-current");
    const sessionEl = byId("petit-context-session");
    const syncEl = byId("petit-context-sync");

    if (viewEl) viewEl.textContent = viewName;
    if (currentEl) currentEl.textContent = detailTitle || project || "未選択";
    if (sessionEl) {
      sessionEl.textContent = activeTask && !activeTask.includes("開始されていません")
        ? `${activeTask}${elapsed ? ` · ${elapsed}` : ""}`
        : "停止中";
    }
    if (syncEl) syncEl.textContent = sync;

    const sessionItem = sessionEl?.closest(".petit-context-item");
    const syncItem = syncEl?.closest(".petit-context-item");
    if (sessionItem) {
      sessionItem.dataset.state = sessionEl.textContent === "停止中" ? "idle" : "active";
    }
    if (syncItem) {
      const lower = sync.toLowerCase();
      syncItem.dataset.state = lower.includes("失敗") || lower.includes("競合")
        ? "error"
        : lower.includes("中") || lower.includes("確認")
          ? "warning"
          : "active";
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

    const reset = () => {
      card.style.setProperty("--orbit-tilt-x", "0deg");
      card.style.setProperty("--orbit-tilt-y", "0deg");
    };

    card.addEventListener("pointermove", (event) => {
      if (event.pointerType === "touch" || reducedMotion.matches) return;
      const rect = card.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
      const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
      card.style.setProperty("--orbit-tilt-x", `${(x * 2.4).toFixed(2)}deg`);
      card.style.setProperty("--orbit-tilt-y", `${(-y * 1.8).toFixed(2)}deg`);
    }, { passive: true });
    card.addEventListener("pointerleave", reset, { passive: true });
    reducedMotion.addEventListener?.("change", reset);
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
