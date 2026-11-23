// PETIT Rubber Dock Navigation: unified spring-physics dock for Desktop & Mobile.
(() => {
  if (!document.querySelector(".universe-shell") || window.PetitRubberDock?.initialized) return;

  const ICONS = {
    chat: `<path d="M5.2 5.5h13.6A2.2 2.2 0 0 1 21 7.7v7.6a2.2 2.2 0 0 1-2.2 2.2H11l-4.8 3v-3H5.2A2.2 2.2 0 0 1 3 15.3V7.7a2.2 2.2 0 0 1 2.2-2.2Z"/><path d="M7.5 10h9M7.5 13.5h5.8"/>`,
    univ: `<circle cx="12" cy="12" r="4.2"/><path d="M3.2 13.7c1.6 2.4 7.1 3.4 12.2 2.1 5.2-1.3 7.4-3.9 5.8-5.5-1.1-1.1-3.5-1.2-6.1-.7"/><path d="M8.5 8.9C5.2 9.5 2.7 10.8 2.7 12.2c0 .6.5 1.1 1.4 1.6"/>`,
    development: `<path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>`,
    stats: `<path d="M4 4v16h17M8 16v-5M13 16V6M18 16V9"/>`,
    utility: `<rect x="4" y="4" width="6.5" height="6.5" rx="1.8"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8"/>`,
    tasks: `<rect x="4" y="4" width="16" height="16" rx="4"/><path d="m8 12.3 2.6 2.6L16.5 9"/>`,
    reminders: `<path d="M6.5 10.3a5.5 5.5 0 0 1 11 0v3.2l1.8 2.7H4.7l1.8-2.7v-3.2Z"/><path d="M9.5 19h5"/>`,
    settings: `<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>`,
    search: `<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4"/>`,
    theme: `<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>`,
    sync: `<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>`,
  };

  const svg = (name) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;

  const TABS = [
    { key: "chat", label: "Chat", title: "Chat", icon: "chat" },
    { key: "univ", label: "Univ", title: "Univ", icon: "univ" },
    { key: "development", label: "Develop", title: "Develop", icon: "development" },
    { key: "stats", label: "Dashboard", title: "Dashboard", icon: "stats" },
    { key: "utility", label: "More", title: "Utility (Tasks / Remind / Settings)", icon: "utility", isUtility: true },
  ];

  const UTILITY_AREAS = new Set(["tasks", "reminders", "settings"]);

  const activateView = (view) => {
    if (window.PetitAppShell?.activateView) {
      window.PetitAppShell.activateView(view);
      return;
    }
    window.dispatchEvent(new CustomEvent("petit:navigate", { detail: { view } }));
  };

  const currentAreaFromDom = () => {
    const visible = Array.from(document.querySelectorAll("[data-view-panel]"))
      .find((panel) => !panel.hidden && panel.getAttribute("aria-hidden") !== "true");
    if (!visible) return "chat";
    const panel = visible.dataset.viewPanel;
    if (panel === "universe") return "univ";
    if (panel === "today") return "stats";
    return panel || "chat";
  };

  const initialize = () => {
    if (document.querySelector(".petit-rubber-dock-stage")) return;

    const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const S = (x, k = 400, c = 30) => ({ x, v: 0, t: x, k, c });
    const tune = (s, k, c) => {
      s.k = k;
      s.c = reduceQuery.matches ? 2 * Math.sqrt(k) : c;
    };
    const step = (s, dt) => {
      const a = -s.k * (s.x - s.t) - s.c * s.v;
      s.v += a * dt;
      s.x += s.v * dt;
    };
    const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

    const token = (name, fallback) =>
      getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
    const springToken = (name, fallback) =>
      token(name, fallback).split(/\s+/).map(Number);

    const T = {
      lead: springToken("--dock-lead", "640 38"),
      trail: springToken("--dock-trail", "150 16"),
      dragLead: springToken("--dock-drag-lead", "1100 56"),
      dragTrail: springToken("--dock-drag-trail", "320 26"),
      openW: springToken("--dock-open-w", "340 21"),
      openH: springToken("--dock-open-h", "230 21"),
      close: springToken("--dock-close", "420 30"),
      pop: springToken("--dock-pop", "520 16"),
    };

    const stage = document.createElement("div");
    stage.className = "petit-rubber-dock-stage";

    const dock = document.createElement("div");
    dock.className = "petit-rubber-dock";

    const panels = document.createElement("div");
    panels.className = "petit-dock-panels";
    panels.innerHTML = `
      <section class="petit-dock-panel" aria-label="Moreメニュー" aria-hidden="true" inert>
        <div class="petit-dock-head petit-dock-it" style="--i:0">
          <h3>Utility</h3>
          <small data-dock-version>${window.PETIT_VERSION || ""}</small>
        </div>
        <div class="petit-dock-tiles petit-dock-it" style="--i:1">
          <button type="button" class="petit-dock-tile" data-dock-target="tasks">
            ${svg("tasks")}
            <strong>Tasks</strong>
            <small>タスク一覧</small>
          </button>
          <button type="button" class="petit-dock-tile" data-dock-target="reminders">
            ${svg("reminders")}
            <strong>Remind</strong>
            <small>通知と履歴</small>
          </button>
          <button type="button" class="petit-dock-tile" data-dock-target="settings">
            ${svg("settings")}
            <strong>Settings</strong>
            <small>環境設定</small>
          </button>
        </div>
        <div class="petit-dock-rows">
          <button type="button" class="petit-dock-row petit-dock-it" style="--i:2" data-dock-command>
            <span class="petit-dock-row__left">${svg("search")}<span>移動と操作を検索</span></span>
            <kbd>Ctrl K</kbd>
          </button>
          <button type="button" class="petit-dock-row petit-dock-it" style="--i:3" data-dock-theme>
            <span class="petit-dock-row__left">${svg("theme")}<span>テーマ</span></span>
            <span class="petit-dock-row__meta" data-dock-theme-label>—</span>
          </button>
          <button type="button" class="petit-dock-row petit-dock-it" style="--i:4" data-dock-sync>
            <span class="petit-dock-row__left">
              <span class="petit-dock-dot" data-dock-sync-dot aria-hidden="true"></span>
              <span>接続ステータス</span>
            </span>
            <span class="petit-dock-row__meta" data-dock-sync-label>確認中</span>
          </button>
          <div class="petit-dock-it" style="--i:5">
            <button type="button" class="petit-dock-row petit-dock-restart" data-dock-restart
                    aria-describedby="petit-dock-restart-status">
              <span class="petit-dock-row__left">${svg("sync")}<span>Coreを再起動</span></span>
              <span class="petit-dock-row__meta">通常モード</span>
            </button>
            <div class="petit-dock-restart-feedback">
              <span id="petit-dock-restart-status" role="status"></span>
              <a href="/static/setup.html?next=/static/universe.html" data-dock-restart-login hidden>管理者ログインを開く</a>
            </div>
          </div>
        </div>
      </section>
    `;

    const tabs = document.createElement("div");
    tabs.className = "petit-dock-tabs";

    const baseIcons = document.createElement("div");
    baseIcons.className = "petit-dock-icons base";
    baseIcons.setAttribute("role", "tablist");
    baseIcons.setAttribute("aria-label", "PETITナビゲーション");

    const ind = document.createElement("div");
    ind.className = "petit-dock-ind";
    ind.setAttribute("aria-hidden", "true");

    const topIcons = document.createElement("div");
    topIcons.className = "petit-dock-icons top";
    topIcons.setAttribute("aria-hidden", "true");

    TABS.forEach((tab) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-label", tab.title);
      btn.title = tab.title;
      btn.dataset.dockTab = tab.key;
      if (tab.isUtility) {
        btn.setAttribute("aria-expanded", "false");
        btn.setAttribute("aria-haspopup", "true");
      }
      btn.innerHTML = `${svg(tab.icon)}<span class="petit-dock-label">${tab.label}</span>`;
      baseIcons.appendChild(btn);

      const overlay = document.createElement("div");
      overlay.innerHTML = `${svg(tab.icon)}<span class="petit-dock-label">${tab.label}</span>`;
      topIcons.appendChild(overlay);
    });

    tabs.append(baseIcons, ind, topIcons);
    dock.append(panels, tabs);
    stage.appendChild(dock);
    document.body.appendChild(stage);
    document.body.classList.add("petit-rubber-dock-ready");

    const btns = Array.from(baseIcons.children);
    const tops = Array.from(topIcons.children);
    const utilityPanel = panels.querySelector(".petit-dock-panel");

    // Geometry
    const N = TABS.length;
    const GAP = 4;
    const TAB_H = 54;
    const DOCK_H = 64;
    let TAB_W = 60;
    let TW = N * TAB_W + (N - 1) * GAP;
    let COL_W = TW + 12;

    const computeMetrics = () => {
      const maxDockW = Math.min(368, Math.max(260, window.innerWidth - 20));
      TAB_W = Math.min(64, Math.floor((maxDockW - 12 - (N - 1) * GAP) / N));
      TW = N * TAB_W + (N - 1) * GAP;
      COL_W = TW + 12;
      dock.style.setProperty("--dock-tab-w", `${TAB_W}px`);
      tabs.style.width = `${TW}px`;
    };
    computeMetrics();

    const cx = (i) => TAB_W / 2 + i * (TAB_W + GAP);
    const expW = () => Math.min(360, Math.max(COL_W, window.innerWidth - 24));
    const measurePanelH = () => utilityPanel.offsetHeight || 236;

    const L = S(cx(0) - TAB_W / 2);
    const R = S(cx(0) + TAB_W / 2);
    const W = S(COL_W, 260, 20);
    const H = S(DOCK_H, 400, 34);
    const nudge = S(0, 300, 18);
    const pops = btns.map(() => S(1, ...T.pop));
    const allSprings = [L, R, W, H, nudge, ...pops];

    let active = 0;
    let expanded = false;
    let rafId = null;
    let lastTime = performance.now();

    const isSettled = () =>
      allSprings.every((s) => Math.abs(s.v) < 0.05 && Math.abs(s.x - s.t) < 0.08);

    const renderFrame = () => {
      const w = Math.max(W.x, COL_W * 0.8);
      const h = Math.max(H.x, DOCK_H);
      const open = clamp((h - DOCK_H) / 220, 0, 1);
      const give = clamp(-H.v / 9000, -0.04, 0.04);

      dock.style.width = `${w * (1 + give)}px`;
      dock.style.height = `${h}px`;
      dock.style.borderRadius = `${Math.min(h / 2, 32 - 8 * open)}px`;
      dock.style.transform = `translate3d(${nudge.x}px, 0, 0)`;

      let l = L.x;
      let r = R.x;
      if (r < l) [l, r] = [r, l];
      const iw = Math.max(r - l, 24);
      const ih = TAB_H * clamp(1 / Math.sqrt(iw / TAB_W), 0.68, 1.06);
      const top = (TAB_H - ih) / 2;

      ind.style.width = `${iw}px`;
      ind.style.height = `${ih}px`;
      ind.style.borderRadius = `${ih / 2}px`;
      ind.style.transform = `translate3d(${l}px, ${top}px, 0)`;

      const rightInset = Math.max(0, TW - l - iw);
      const bottomInset = Math.max(0, TAB_H - top - ih);
      topIcons.style.clipPath = `inset(${top}px ${rightInset}px ${bottomInset}px ${Math.max(0, l)}px round ${ih / 2}px)`;

      pops.forEach((p, idx) => {
        const scale = `scale(${p.x})`;
        const baseSvg = btns[idx].firstElementChild;
        const topSvg = tops[idx].firstElementChild;
        if (baseSvg) baseSvg.style.transform = scale;
        if (topSvg) topSvg.style.transform = scale;
      });
    };

    const tick = (now) => {
      const dt = Math.min((now - lastTime) / 1000, 1 / 30);
      lastTime = now;
      const sub = 4;
      for (let k = 0; k < sub; k++) {
        allSprings.forEach((s) => step(s, dt / sub));
      }
      renderFrame();
      if (!isSettled() || drag?.live) {
        rafId = requestAnimationFrame(tick);
      } else {
        allSprings.forEach((s) => {
          s.x = s.t;
          s.v = 0;
        });
        renderFrame();
        rafId = null;
      }
    };

    const wake = () => {
      if (rafId != null) return;
      lastTime = performance.now();
      rafId = requestAnimationFrame(tick);
    };

    const moveTo = (center, dir, isDrag = false) => {
      const lead = isDrag ? T.dragLead : T.lead;
      const trail = isDrag ? T.dragTrail : T.trail;
      if (dir === 0) {
        tune(L, 600, 44);
        tune(R, 600, 44);
      } else {
        const [lSpring, rSpring] = dir > 0 ? [trail, lead] : [lead, trail];
        tune(L, ...lSpring);
        tune(R, ...rSpring);
      }
      L.t = center - TAB_W / 2;
      R.t = center + TAB_W / 2;
      wake();
    };

    const setActiveIndex = (i, dirHint = null, { pop = true } = {}) => {
      const clamped = clamp(i, 0, N - 1);
      const dir = dirHint ?? Math.sign(cx(clamped) - (L.x + R.x) / 2);
      moveTo(cx(clamped), dir);
      active = clamped;
      if (pop) pops[clamped].v -= 3.2;
      btns.forEach((b, j) => {
        b.setAttribute("aria-selected", String(j === clamped));
        b.tabIndex = j === clamped ? 0 : -1;
      });
      wake();
    };

    const setExpanded = (v) => {
      if (v === expanded) return;
      expanded = v;
      const utilBtn = btns[N - 1];
      utilBtn?.setAttribute("aria-expanded", String(v));
      utilityPanel.setAttribute("aria-hidden", String(!v));
      utilityPanel.inert = !v;

      if (v) {
        syncUtilityMeta();
        utilityPanel.classList.add("prep");
        void utilityPanel.offsetWidth;
        utilityPanel.classList.remove("prep");
        requestAnimationFrame(() => utilityPanel.classList.add("on"));

        W.t = expW();
        H.t = DOCK_H + measurePanelH();
        tune(W, ...T.openW);
        tune(H, ...T.openH);
      } else {
        utilityPanel.classList.remove("on");
        W.t = COL_W;
        H.t = DOCK_H;
        tune(W, T.close[0] * 0.72, T.close[1] * 0.66);
        tune(H, ...T.close);
      }
      pops[N - 1].v -= 2.4;
      wake();
    };

    const syncFromArea = (requestedArea = "") => {
      const area = requestedArea || currentAreaFromDom();
      const idx = TABS.findIndex((t) => t.key === area);
      const targetIdx = idx >= 0 ? idx : (UTILITY_AREAS.has(area) ? N - 1 : 0);
      if (targetIdx !== active) {
        setActiveIndex(targetIdx, null, { pop: false });
      }
      panels.querySelectorAll("[data-dock-target]").forEach((tile) => {
        tile.classList.toggle("is-active", tile.dataset.dockTarget === area);
      });
    };

    const syncUtilityMeta = () => {
      const themeToggle = document.getElementById("petit-theme-toggle");
      const themeLabel = panels.querySelector("[data-dock-theme-label]");
      if (themeLabel && themeToggle) {
        themeLabel.textContent = themeToggle.textContent.replace(/^テーマ:\s*/, "");
      }

      const syncPill = document.getElementById("sync-pill");
      const syncLabel = panels.querySelector("[data-dock-sync-label]");
      const syncDot = panels.querySelector("[data-dock-sync-dot]");
      if (syncPill && syncLabel && syncDot) {
        const copy = String(syncPill.textContent || "").trim() || "確認中";
        syncLabel.textContent = copy;
        syncDot.dataset.state =
          syncPill.dataset.state || (/失敗|競合/.test(copy) ? "error" : /確認中|同期中/.test(copy) ? "loading" : "ready");
      }
    };

    // Pointer drag & rubber banding
    let drag = null;
    let suppressClick = false;

    const rubber = (x, min, max, d = 46) =>
      x < min ? min - (1 - 1 / (((min - x) * 0.55) / d + 1)) * d :
      x > max ? max + (1 - 1 / (((x - max) * 0.55) / d + 1)) * d : x;

    const localX = (e) => {
      const r = dock.getBoundingClientRect();
      return e.clientX - (r.left + r.width / 2 - nudge.x) + TW / 2;
    };

    tabs.addEventListener("pointerdown", (e) => {
      drag = { id: e.pointerId, x0: e.clientX, last: localX(e), live: false, dir: 0 };
    });

    tabs.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      if (!drag.live && Math.abs(e.clientX - drag.x0) > 4) {
        drag.live = true;
        tabs.setPointerCapture(e.pointerId);
        tabs.classList.add("dragging");
      }
      if (!drag.live) return;
      const raw = localX(e);
      const d = raw - drag.last;
      drag.last = raw;
      if (Math.abs(d) > 0.5) drag.dir = Math.sign(d);
      const c = rubber(raw, cx(0), cx(N - 1));
      moveTo(c, drag.dir, true);
      nudge.t = (c - clamp(c, cx(0), cx(N - 1))) * 0.35;
      wake();
    });

    const endDrag = (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      if (drag.live) {
        const c = (L.t + R.t) / 2;
        nudge.t = 0;
        const target = clamp(Math.round((c - cx(0)) / (TAB_W + GAP) + drag.dir * 0.18), 0, N - 1);
        setActiveIndex(target, drag.dir || 0);
        const tab = TABS[target];
        if (tab.isUtility) {
          setExpanded(true);
        } else {
          if (expanded) setExpanded(false);
          activateView(tab.key);
        }
        suppressClick = true;
        setTimeout(() => {
          suppressClick = false;
        }, 0);
        tabs.classList.remove("dragging");
      }
      drag = null;
    };

    tabs.addEventListener("pointerup", endDrag);
    tabs.addEventListener("pointercancel", endDrag);

    btns.forEach((btn, i) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (suppressClick) return;
        const tab = TABS[i];
        if (tab.isUtility) {
          setActiveIndex(i);
          setExpanded(!expanded);
          return;
        }
        if (expanded) setExpanded(false);
        setActiveIndex(i);
        activateView(tab.key);
      });
    });

    // Utility panel actions
    panels.querySelectorAll("[data-dock-target]").forEach((tile) => {
      tile.addEventListener("click", () => {
        const target = tile.dataset.dockTarget;
        setExpanded(false);
        if (target) activateView(target);
      });
    });

    panels.querySelector("[data-dock-command]")?.addEventListener("click", () => {
      setExpanded(false);
      window.PetitAppShell?.openCommandPalette?.();
    });

    panels.querySelector("[data-dock-theme]")?.addEventListener("click", () => {
      document.getElementById("petit-theme-toggle")?.click();
      requestAnimationFrame(syncUtilityMeta);
    });

    panels.querySelector("[data-dock-sync]")?.addEventListener("click", () => {
      setExpanded(false);
      document.getElementById("sync-pill")?.click();
    });

    const restartButton = panels.querySelector("[data-dock-restart]");
    const restartStatus = panels.querySelector("#petit-dock-restart-status");
    const restartLogin = panels.querySelector("[data-dock-restart-login]");
    const showRestartStatus = (message, loginRequired = false) => {
      restartStatus.textContent = message;
      restartLogin.hidden = !loginRequired;
      if (expanded) {
        H.t = DOCK_H + measurePanelH();
        wake();
      }
    };
    restartButton.addEventListener("click", async () => {
      restartButton.disabled = true;
      showRestartStatus("接続を確認しています…");
      try {
        await window.PetitCoreRestart.restart(() => showRestartStatus("Coreを再起動しています…"));
        showRestartStatus("通常モードで復旧しました。");
      } catch (error) {
        showRestartStatus(error.message, error.status === 401);
      } finally {
        restartButton.disabled = false;
      }
    });

    // Outside click & Escape
    document.addEventListener("click", (e) => {
      if (expanded && !dock.contains(e.target)) setExpanded(false);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && expanded) {
        setExpanded(false);
      }
    });

    // Resize handling
    window.addEventListener("resize", () => {
      computeMetrics();
      const center = cx(active);
      L.x = L.t = center - TAB_W / 2;
      R.x = R.t = center + TAB_W / 2;
      if (expanded) {
        W.t = expW();
        H.t = DOCK_H + measurePanelH();
      } else {
        W.x = W.t = COL_W;
      }
      renderFrame();
      wake();
    }, { passive: true });

    // Sync with app shell & panel changes
    window.addEventListener("petit:area-change", (e) => syncFromArea(e.detail?.area || ""));
    window.addEventListener("petit:panel-change", () => syncFromArea());

    const syncPill = document.getElementById("sync-pill");
    if (syncPill) {
      new MutationObserver(syncUtilityMeta).observe(syncPill, {
        attributes: true,
        childList: true,
        characterData: true,
        subtree: true,
      });
    }

    // Initial sync without animation jump
    const initialArea = currentAreaFromDom();
    const initialIdx = TABS.findIndex((t) => t.key === initialArea);
    active = initialIdx >= 0 ? initialIdx : (UTILITY_AREAS.has(initialArea) ? N - 1 : 0);
    const c0 = cx(active);
    L.x = L.t = c0 - TAB_W / 2;
    R.x = R.t = c0 + TAB_W / 2;
    W.x = W.t = COL_W;
    H.x = H.t = DOCK_H;
    btns.forEach((b, j) => {
      b.setAttribute("aria-selected", String(j === active));
      b.tabIndex = j === active ? 0 : -1;
    });
    syncUtilityMeta();
    renderFrame();
  };

  window.PetitRubberDock = { initialize, initialized: true };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
