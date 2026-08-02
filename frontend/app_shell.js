// Shared PETIT application shell for Universe UI.
(() => {
  const PRIMARY_VIEWS = ["today", "focus", "tasks", "chat"];
  const MORE_VIEWS = [
    { view: "universe", label: "Life" },
    { view: "reminders", label: "Reminders" },
  ];

  const activateView = (view) => {
    const target = document.querySelector(`[data-view="${view}"]`);
    if (target) target.click();
  };

  const loadStylesheet = (href, marker) => {
    if (document.querySelector(`link[data-petit-module="${marker}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.petitModule = marker;
    document.head.appendChild(link);
  };

  const loadScript = (src, marker) => {
    if (document.querySelector(`script[data-petit-module="${marker}"]`)) return;
    const script = document.createElement("script");
    script.src = src;
    script.dataset.petitModule = marker;
    document.head.appendChild(script);
  };

  const installLifeMap = () => {
    if (!document.querySelector('[data-view-panel="universe"]')) return;
    loadStylesheet("/static/life-map.css", "life-map-style");
    loadScript("/static/life-map.js", "life-map-script");
  };

  const createMoreMenu = (nav) => {
    if (document.getElementById("petit-more-menu")) return;

    const moreButton = document.createElement("button");
    moreButton.type = "button";
    moreButton.className = "view-tab";
    moreButton.dataset.appShellMore = "true";
    moreButton.textContent = "More";
    moreButton.setAttribute("aria-expanded", "false");
    moreButton.setAttribute("aria-controls", "petit-more-menu");
    nav.appendChild(moreButton);

    const menu = document.createElement("div");
    menu.id = "petit-more-menu";
    menu.className = "petit-more-menu";
    menu.hidden = true;

    const panel = document.createElement("div");
    panel.className = "petit-more-menu__panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "その他の機能");

    MORE_VIEWS.forEach(({ view, label }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", () => {
        activateView(view);
        menu.hidden = true;
        moreButton.setAttribute("aria-expanded", "false");
      });
      panel.appendChild(button);
    });

    const notificationLink = document.createElement("a");
    notificationLink.href = "/static/legacy.html?view=notifications";
    notificationLink.textContent = "Notifications";
    panel.appendChild(notificationLink);

    const calendarLink = document.createElement("a");
    calendarLink.href = "/static/legacy.html?view=calendar";
    calendarLink.textContent = "Calendar（read-only）";
    panel.appendChild(calendarLink);

    const settingsLink = document.createElement("a");
    settingsLink.href = "/static/legacy.html?view=settings";
    settingsLink.textContent = "Settings";
    panel.appendChild(settingsLink);

    menu.appendChild(panel);
    document.body.appendChild(menu);

    moreButton.addEventListener("click", () => {
      menu.hidden = !menu.hidden;
      moreButton.setAttribute("aria-expanded", String(!menu.hidden));
    });

    menu.addEventListener("click", (event) => {
      if (event.target === menu) {
        menu.hidden = true;
        moreButton.setAttribute("aria-expanded", "false");
      }
    });

    window.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || menu.hidden) return;
      menu.hidden = true;
      moreButton.setAttribute("aria-expanded", "false");
      moreButton.focus();
    });
  };

  const installStyles = () => {
    if (document.getElementById("petit-app-shell-style")) return;
    const style = document.createElement("style");
    style.id = "petit-app-shell-style";
    style.textContent = `
      .petit-more-menu {
        position: fixed;
        inset: 0;
        z-index: 1000;
        display: grid;
        place-items: end center;
        padding: 24px;
        background: rgb(2 4 12 / 68%);
        backdrop-filter: blur(12px);
      }
      .petit-more-menu[hidden] { display: none; }
      .petit-more-menu__panel {
        width: min(100%, 420px);
        display: grid;
        gap: 10px;
        padding: 18px;
        border: 1px solid rgb(255 255 255 / 16%);
        border-radius: 20px;
        background: #0d1222;
        box-shadow: 0 24px 70px rgb(0 0 0 / 45%);
      }
      .petit-more-menu__panel button,
      .petit-more-menu__panel a {
        display: block;
        width: 100%;
        box-sizing: border-box;
        padding: 14px 16px;
        border: 0;
        border-radius: 14px;
        background: rgb(255 255 255 / 7%);
        color: inherit;
        font: inherit;
        text-align: left;
        text-decoration: none;
      }
      @media (min-width: 720px) {
        .petit-more-menu { place-items: start end; padding-top: 82px; }
        .petit-more-menu__panel { width: 320px; }
      }
    `;
    document.head.appendChild(style);
  };

  const initialize = () => {
    const nav = document.querySelector(".view-tabs");
    if (!nav || nav.dataset.petitAppShellReady === "true") return;
    nav.dataset.petitAppShellReady = "true";

    Array.from(nav.querySelectorAll("[data-view]")).forEach((button) => {
      const view = button.dataset.view;
      button.hidden = !PRIMARY_VIEWS.includes(view);
    });

    installStyles();
    installLifeMap();
    createMoreMenu(nav);

    const requested = new URLSearchParams(window.location.search).get("view");
    if (requested && [...PRIMARY_VIEWS, ...MORE_VIEWS.map((item) => item.view)].includes(requested)) {
      window.requestAnimationFrame(() => activateView(requested));
    }
  };

  window.PetitAppShell = { initialize, activateView };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
