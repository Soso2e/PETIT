// Shared PETIT application shell for the Univ-first UI.
(() => {
  if (window.PetitAppShell?.initialized) return;
  const HOME_VIEW = "universe";
  const ASSET_VERSION = window.PETIT_ASSET_VERSION || "0.14.1";
  const PRIMARY_VIEWS = [
    { view: "univ", target: "universe", label: "Univ", title: "Universe", description: "タスク空間" },
    { view: "tasks", target: "tasks", label: "Tasks", title: "Tasks", description: "やること" },
    { view: "chat", target: "chat", label: "PETIT", title: "PETIT", description: "会話と相談" },
    { view: "stats", target: "today", label: "統計", title: "統計", description: "頑張りと振り返り" },
  ];
  const VIEW_ALIASES = {
    home: "univ",
    focus: "univ",
    universe: "univ",
    projects: "univ",
    petit: "chat",
    today: "stats",
    reminders: "reminders",
  };

  const resolveArea = (view) => VIEW_ALIASES[view] || view;
  const panelForArea = (area) => area === "univ" ? "universe" : area === "stats" ? "today" : area;

  const switchPanelDirectly = (panelView) => {
    const tabs = Array.from(document.querySelectorAll("[data-view]"));
    const panels = Array.from(document.querySelectorAll("[data-view-panel]"));
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Univ is a viewport, not a document section. Keep the page lock in the
    // shell so every navigation path (tab, URL alias, and task deep link)
    // receives the same fixed-space contract.
    if (panelView === "universe" || panelView === "chat") window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    document.body.classList.toggle("petit-univ-screen", panelView === "universe");

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
            openDetail: Boolean(detail.openDetail),
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
    loadStylesheet("/static/petit-rail.css", "resizable-rail-style");
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
      stats: buttons.get("today"),
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
    const header = document.createElement("div");
    header.className = "petit-area-rail__header";

    const brand = document.createElement("a");
    brand.className = "petit-area-rail__brand";
    brand.href = "/?view=univ";
    brand.setAttribute("aria-label", "PETITのUnivを開く");
    brand.innerHTML = '<img src="/static/branding/icon_logo.png" alt=""><span><strong>PETIT</strong><small>LOCAL WORKSPACE</small></span>';
    header.appendChild(brand);
    const pin = document.createElement("button");
    pin.type = "button"; pin.className = "petit-area-rail__pin";
    let pinned = null;
    try {
      const saved = localStorage.getItem("petit_rail_pinned");
      if (saved === "true" || saved === "false") pinned = saved === "true";
    } catch { /* The rail also works when storage is unavailable. */ }
    let hovered = false;
    const syncRailSize = () => {
      const compact = pinned === false || (pinned === null && document.body.classList.contains("petit-univ-active"));
      document.body.dataset.petitRailMode = pinned === true ? "pinned" : compact ? "compact" : "expanded";
      pin.textContent = compact ? "›" : "‹";
      pin.setAttribute("aria-pressed", String(pinned === true));
      pin.setAttribute("aria-label", compact ? "タブバーを広く固定" : "タブバーを小さくする");
      pin.title = pin.getAttribute("aria-label");
      const keyboardInside = rail.contains(document.activeElement) && document.activeElement !== pin;
      const open = compact && (hovered || keyboardInside);
      if (document.body.classList.contains("petit-rail-open") !== open) document.body.classList.toggle("petit-rail-open", open);
    };
    pin.addEventListener("click", () => {
      pinned = document.body.dataset.petitRailMode === "compact";
      try { localStorage.setItem("petit_rail_pinned", String(pinned)); } catch { /* Session-only choice. */ }
      syncRailSize();
    });
    rail.addEventListener("pointerenter", (event) => { if (event.pointerType !== "touch") { hovered = true; syncRailSize(); } });
    rail.addEventListener("pointerleave", () => { hovered = false; syncRailSize(); });
    rail.addEventListener("focusin", syncRailSize);
    rail.addEventListener("focusout", () => requestAnimationFrame(syncRailSize));
    // View switches alter this class; hover expansion never changes the scene geometry.
    new MutationObserver(syncRailSize).observe(document.body, { attributes: true, attributeFilter: ["class"] });
    header.appendChild(pin); rail.appendChild(header);

    const commandButton = document.createElement("button");
    commandButton.type = "button";
    commandButton.className = "petit-area-rail__command";
    commandButton.dataset.commandOpen = "true";
    commandButton.innerHTML = '<span class="petit-area-rail__command-icon" aria-hidden="true">⌕</span><span class="petit-area-rail__command-label">移動と操作を検索</span><kbd>Ctrl K</kbd>';
    commandButton.setAttribute("aria-label", "移動と操作を検索");
    rail.appendChild(commandButton);

    const railNav = document.createElement("nav");
    railNav.className = "petit-area-rail__nav";
    railNav.setAttribute("aria-label", "ワークスペース");
    PRIMARY_VIEWS.forEach(({ view, title, description }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.railView = view;
      button.setAttribute("aria-label", `${title}：${description}`);
      button.title = title;
      button.innerHTML = `<span class="petit-area-rail__monogram" aria-hidden="true">${title.slice(0, 1)}</span><span><strong>${title}</strong><small>${description}</small></span>`;
      button.addEventListener("click", () => activateView(view));
      railNav.appendChild(button);
    });
    rail.appendChild(railNav);

    const shortcuts = document.createElement("div");
    shortcuts.className = "petit-area-rail__shortcuts";
    shortcuts.innerHTML = `
      <span class="petit-area-rail__section-label">UTILITY</span>
      <button type="button" data-shell-target="reminders" aria-label="Reminders：通知と履歴" title="Reminders"><span class="petit-area-rail__monogram" aria-hidden="true">R</span><span class="petit-area-rail__utility-label"><span>Reminders</span><small>通知と履歴</small></span></button>
      <button type="button" data-shell-target="settings" aria-label="Settings：モデルと環境" title="Settings"><span class="petit-area-rail__monogram" aria-hidden="true">S</span><span class="petit-area-rail__utility-label"><span>Settings</span><small>モデルと環境</small></span></button>
    `;
    shortcuts.querySelectorAll("[data-shell-target]").forEach((button) => {
      button.addEventListener("click", () => activateView(button.dataset.shellTarget));
    });
    rail.appendChild(shortcuts);

    const status = document.createElement("div");
    status.className = "petit-area-rail__status";
    status.innerHTML = `
      <span class="petit-area-rail__status-dot" aria-hidden="true"></span>
      <span><button type="button" data-rail-sync aria-haspopup="dialog" aria-label="接続ステータスを開く">接続確認中</button><small data-rail-version>${window.PETIT_VERSION || ""}</small></span>
    `;
    rail.appendChild(status);
    document.body.appendChild(rail);
    syncRailSize();
  };

  const installCommandPalette = () => {
    if (document.querySelector(".petit-command-palette")) return;
    const dialog = document.createElement("dialog");
    dialog.className = "petit-command-palette";
    dialog.setAttribute("aria-labelledby", "petit-command-title");
    dialog.innerHTML = `
      <form method="dialog" class="petit-command-palette__surface">
        <header>
          <span class="petit-command-palette__eyebrow">QUICK SWITCHER</span>
          <button type="submit" value="cancel" aria-label="閉じる">Esc</button>
        </header>
        <label for="petit-command-input" id="petit-command-title">どこへ移動しますか？</label>
        <input id="petit-command-input" type="search" autocomplete="off" placeholder="Universe、Tasks、設定…" />
        <div class="petit-command-palette__results" role="listbox" aria-label="移動先">
          <button type="button" data-command-view="univ"><strong>Universe</strong><small>タスク空間をひらく</small><kbd>1</kbd></button>
          <button type="button" data-command-view="tasks"><strong>Tasks</strong><small>重要なタスクを確認</small><kbd>2</kbd></button>
          <button type="button" data-command-view="chat"><strong>PETIT</strong><small>会話をはじめる</small><kbd>3</kbd></button>
          <button type="button" data-command-view="stats"><strong>統計</strong><small>今日の頑張りと7日間の作業を振り返る</small><kbd>4</kbd></button>
          <button type="button" data-command-view="reminders"><strong>Reminders</strong><small>通知と履歴を確認</small></button>
          <button type="button" data-command-view="settings"><strong>Settings</strong><small>モデルと環境を設定</small><kbd>⌘,</kbd></button>
        </div>
        <p class="petit-command-palette__empty" hidden>該当する移動先がありません。</p>
        <footer><span>↑↓ で選択</span><span>Enter で開く</span></footer>
      </form>
    `;
    document.body.appendChild(dialog);

    const input = dialog.querySelector("input");
    const commands = Array.from(dialog.querySelectorAll("[data-command-view]"));
    const empty = dialog.querySelector(".petit-command-palette__empty");
    let activeIndex = 0;

    const visibleCommands = () => commands.filter((button) => !button.hidden);
    const syncActive = (index = 0) => {
      const visible = visibleCommands();
      activeIndex = Math.max(0, Math.min(index, visible.length - 1));
      commands.forEach((button) => button.classList.remove("is-active"));
      visible[activeIndex]?.classList.add("is-active");
      visible[activeIndex]?.scrollIntoView({ block: "nearest" });
    };
    const closeAndActivate = (view) => {
      dialog.close();
      activateView(view);
    };
    const open = () => {
      if (!dialog.open) dialog.showModal();
      input.value = "";
      commands.forEach((button) => { button.hidden = false; });
      empty.hidden = true;
      syncActive(0);
      window.requestAnimationFrame(() => input.focus());
    };

    document.querySelector("[data-command-open]")?.addEventListener("click", open);
    commands.forEach((button) => button.addEventListener("click", () => closeAndActivate(button.dataset.commandView)));
    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase("ja");
      commands.forEach((button) => {
        button.hidden = Boolean(query) && !button.textContent.toLocaleLowerCase("ja").includes(query);
      });
      empty.hidden = visibleCommands().length > 0;
      syncActive(0);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        const count = visibleCommands().length;
        if (count) syncActive((activeIndex + delta + count) % count);
      }
      if (event.key === "Enter") {
        const command = visibleCommands()[activeIndex];
        if (!command) return;
        event.preventDefault();
        closeAndActivate(command.dataset.commandView);
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    document.addEventListener("keydown", (event) => {
      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === "k") {
        event.preventDefault();
        open();
      }
      if (modifier && event.key === ",") {
        event.preventDefault();
        if (dialog.open) dialog.close();
        activateView("settings");
      }
    });
  };

  const syncRailStatus = () => {
    const source = document.querySelector("#sync-pill");
    const target = document.querySelector("[data-rail-sync]");
    const status = document.querySelector(".petit-area-rail__status");
    if (!source || !target || !status) return;
    const copy = String(source.textContent || "").trim() || "接続確認中";
    target.textContent = copy;
    status.dataset.state = source.dataset.state || (/失敗|競合/.test(copy) ? "error" : /確認中|同期中/.test(copy) ? "loading" : "ready");
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
    installCommandPalette();
    syncRailStatus();
    installPetitSubnav();
    installPanelObserver();

    const syncPill = document.querySelector("#sync-pill");
    if (syncPill) {
      new MutationObserver(syncRailStatus).observe(syncPill, {
        attributes: true,
        childList: true,
        characterData: true,
        subtree: true,
      });
    }

    const requested = new URLSearchParams(window.location.search).get("view");
    const supported = ["univ", "home", "focus", "tasks", "chat", "stats", "today", "universe", "reminders", "settings", "petit", "projects"];
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
