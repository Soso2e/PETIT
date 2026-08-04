// PETIT corner shell: iPhone-first navigation, status, and utility access.
(() => {
  if (window.PetitCornerShell?.initialized) return;
  const AREA_META = {
    univ: { label: "Univ", title: "Universe", icon: "planet" },
    tasks: { label: "Tasks", title: "Tasks", icon: "check" },
    chat: { label: "PETIT", title: "Chat", icon: "chat" },
    reminders: { label: "Reminders", title: "Reminders", icon: "bell" },
  };

  const ICONS = {
    planet: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="4.2"></circle>
        <path d="M3.2 13.7c1.6 2.4 7.1 3.4 12.2 2.1 5.2-1.3 7.4-3.9 5.8-5.5-1.1-1.1-3.5-1.2-6.1-.7"></path>
        <path d="M8.5 8.9C5.2 9.5 2.7 10.8 2.7 12.2c0 .6.5 1.1 1.4 1.6"></path>
      </svg>`,
    check: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="4" y="4" width="16" height="16" rx="4"></rect>
        <path d="m8 12.3 2.6 2.6L16.5 9"></path>
      </svg>`,
    chat: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5.2 5.5h13.6A2.2 2.2 0 0 1 21 7.7v7.6a2.2 2.2 0 0 1-2.2 2.2H11l-4.8 3v-3H5.2A2.2 2.2 0 0 1 3 15.3V7.7a2.2 2.2 0 0 1 2.2-2.2Z"></path>
        <path d="M7.5 10h9M7.5 13.5h5.8"></path>
      </svg>`,
    bell: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6.5 10.3a5.5 5.5 0 0 1 11 0v3.2l1.8 2.7H4.7l1.8-2.7v-3.2Z"></path>
        <path d="M9.5 19h5"></path>
      </svg>`,
    settings: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3.2"></circle>
        <path d="M19 13.8v-3.6l-2-.6a7.3 7.3 0 0 0-.7-1.7l1-1.8-2.5-2.5-1.8 1a7.3 7.3 0 0 0-1.7-.7l-.6-2H7.2l-.6 2a7.3 7.3 0 0 0-1.7.7l-1.8-1L.6 6.1l1 1.8a7.3 7.3 0 0 0-.7 1.7l-2 .6v3.6l2 .6c.2.6.4 1.2.7 1.7l-1 1.8 2.5 2.5 1.8-1c.5.3 1.1.5 1.7.7l.6 2h3.6l.6-2c.6-.2 1.2-.4 1.7-.7l1.8 1 2.5-2.5-1-1.8c.3-.5.5-1.1.7-1.7l1.9-.6Z" transform="translate(2 0) scale(.83)"></path>
      </svg>`,
    close: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m7 7 10 10M17 7 7 17"></path>
      </svg>`,
  };

  const iconMarkup = (name) => `<span class="petit-corner-icon">${ICONS[name] || ""}</span>`;

  const ensureStylesheet = () => {
    if (document.querySelector('link[data-petit-module="corner-shell-style"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `/static/petit-corner-shell.css?v=${window.PETIT_ASSET_VERSION || "0.14.1"}`;
    link.dataset.petitModule = "corner-shell-style";
    document.head.appendChild(link);
  };

  const activate = (view) => {
    if (window.PetitAppShell?.activateView) {
      window.PetitAppShell.activateView(view);
      return;
    }
    window.dispatchEvent(new CustomEvent("petit:navigate", { detail: { view } }));
  };

  const areaFromPanel = () => {
    const visible = Array.from(document.querySelectorAll("[data-view-panel]"))
      .find((panel) => !panel.hidden && panel.getAttribute("aria-hidden") !== "true");
    if (!visible) return "univ";
    return visible.dataset.viewPanel === "universe" ? "univ" : visible.dataset.viewPanel;
  };

  const decorateNavigation = () => {
    const nav = document.querySelector(".view-tabs");
    if (!nav) return false;
    nav.classList.add("petit-corner-nav");
    nav.setAttribute("role", "tablist");

    nav.querySelectorAll("[data-shell-area]").forEach((button) => {
      const area = button.dataset.shellArea;
      const meta = AREA_META[area];
      if (!meta) return;
      button.classList.add("petit-corner-nav__item");
      button.setAttribute("aria-label", meta.title);
      button.title = meta.title;
      if (button.dataset.cornerDecorated === "true") return;
      button.dataset.cornerDecorated = "true";
      button.innerHTML = `${iconMarkup(meta.icon)}<span class="petit-corner-nav__label">${meta.label}</span>`;
    });
    return nav.querySelectorAll("[data-shell-area]").length === 3;
  };

  const installStatus = () => {
    const topbar = document.querySelector(".universe-topbar");
    const brand = topbar?.querySelector(".brand");
    const actions = topbar?.querySelector(".topbar-actions");
    if (!topbar || !brand || !actions || topbar.querySelector(".petit-corner-status")) return;

    const status = document.createElement("section");
    status.className = "petit-corner-status";
    status.setAttribute("aria-label", "PETITの現在状態");
    status.innerHTML = `
      <div class="petit-corner-status__identity">
        <span class="petit-corner-status__eyebrow">PETIT</span>
        <strong data-petit-current-area>Universe</strong>
      </div>
      <div class="petit-corner-status__meta">
        <span data-petit-status-copy>READY</span>
      </div>
    `;

    const version = actions.querySelector(".version-pill");
    const sync = actions.querySelector("#sync-pill");
    if (sync) {
      sync.hidden = false;
      sync.classList.add("petit-corner-status__sync");
      status.querySelector(".petit-corner-status__meta")?.appendChild(sync);
    }
    if (version) {
      version.classList.add("petit-corner-status__version");
      status.querySelector(".petit-corner-status__meta")?.appendChild(version);
    }

    brand.hidden = true;
    topbar.prepend(status);
    actions.classList.add("petit-corner-actions");
  };

  const installUtilityDock = () => {
    if (document.querySelector(".petit-utility-dock")) return;

    const dock = document.createElement("aside");
    dock.className = "petit-utility-dock";
    dock.setAttribute("aria-label", "補助機能");
    dock.innerHTML = `
      <button type="button" class="petit-utility-dock__button" data-corner-reminders aria-label="リマインダー" title="リマインダー">
        ${iconMarkup("bell")}
        <span>Remind</span>
      </button>
      <button type="button" class="petit-utility-dock__button" data-corner-settings aria-label="設定メニュー" aria-expanded="false" title="設定">
        ${iconMarkup("settings")}
        <span>Settings</span>
      </button>
      <section class="petit-utility-menu" data-corner-menu hidden aria-label="設定と補助機能">
        <header>
          <div><span>PETIT</span><strong>Settings</strong></div>
          <button type="button" data-corner-close aria-label="閉じる">${iconMarkup("close")}</button>
        </header>
        <button type="button" data-corner-menu-reminders>
          ${iconMarkup("bell")}
          <span><strong>リマインダー</strong><small>登録内容と履歴を確認</small></span>
        </button>
        <a href="/static/legacy.html?view=settings">
          ${iconMarkup("settings")}
          <span><strong>詳細設定</strong><small>機能が揃った設定画面を開く</small></span>
        </a>
        <a href="/static/legacy.html">
          <span class="petit-corner-icon petit-corner-icon--legacy" aria-hidden="true">UI</span>
          <span><strong>クラシックUI</strong><small>従来機能へ戻る</small></span>
        </a>
      </section>
    `;
    document.body.appendChild(dock);

    const menu = dock.querySelector("[data-corner-menu]");
    const settings = dock.querySelector("[data-corner-settings]");
    const setOpen = (open) => {
      menu.hidden = !open;
      settings.setAttribute("aria-expanded", String(open));
      dock.classList.toggle("is-open", open);
      if (open) menu.querySelector("[data-corner-close]")?.focus();
    };

    dock.querySelector("[data-corner-reminders]")?.addEventListener("click", () => activate("reminders"));
    dock.querySelector("[data-corner-menu-reminders]")?.addEventListener("click", () => {
      setOpen(false);
      activate("reminders");
    });
    settings?.addEventListener("click", () => setOpen(menu.hidden));
    dock.querySelector("[data-corner-close]")?.addEventListener("click", () => setOpen(false));

    document.addEventListener("pointerdown", (event) => {
      if (!menu.hidden && event.target instanceof Node && !dock.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !menu.hidden) {
        setOpen(false);
        settings?.focus();
      }
    });
  };

  const syncState = (requestedArea = "") => {
    const area = requestedArea || areaFromPanel();
    const meta = AREA_META[area] || AREA_META.univ;
    document.querySelectorAll("[data-petit-current-area]").forEach((element) => {
      if (element.textContent !== meta.title) element.textContent = meta.title;
    });
    document.body.dataset.petitCornerArea = area;

    const sync = document.querySelector("#sync-pill");
    const statusCopy = document.querySelector("[data-petit-status-copy]");
    if (statusCopy) {
      const syncText = String(sync?.textContent || "").trim();
      const nextStatus = syncText && !/確認中/.test(syncText) ? syncText : "READY";
      if (statusCopy.textContent !== nextStatus) statusCopy.textContent = nextStatus;
    }
  };

  const observeShell = () => {
    const root = document.querySelector(".universe-shell");
    if (!root) return;
    new MutationObserver(() => {
      decorateNavigation();
      syncState();
    }).observe(root, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["hidden", "class", "aria-hidden"],
    });
  };

  const initialize = () => {
    ensureStylesheet();
    installStatus();
    installUtilityDock();
    decorateNavigation();
    syncState();
    observeShell();

    window.addEventListener("petit:area-change", (event) => syncState(event.detail?.area || ""));
    window.addEventListener("petit:panel-change", () => syncState());

    let attempts = 0;
    const waitForShell = () => {
      const ready = decorateNavigation();
      if (ready || attempts >= 20) return;
      attempts += 1;
      window.requestAnimationFrame(waitForShell);
    };
    waitForShell();
  };

  window.PetitCornerShell = { initialize, initialized: true };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
