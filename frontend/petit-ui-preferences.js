// PETIT explicit UI preferences: theme, render cost, and mobile viewport handling.
(() => {
  if (window.PetitUiPreferences?.initialized) return;

  const root = document.documentElement;
  const STORAGE = {
    theme: "petit_ui_theme",
    performance: "petit_ui_performance",
    developer: "petit_developer_mode",
  };

  const normalizeTheme = (value) => (value === "light" ? "light" : "dark");
  const normalizePerformance = (value) => (value === "standard" ? "standard" : "lite");
  const normalizeDeveloper = (value) => (value === "true" || value === "on" ? "on" : "off");

  const defaultPerformance = () => {
    const mobile = window.matchMedia("(max-width: 760px)").matches;
    const lowConcurrency = Number(navigator.hardwareConcurrency || 8) <= 4;
    return mobile || lowConcurrency ? "lite" : "standard";
  };

  const state = {
    theme: normalizeTheme(localStorage.getItem(STORAGE.theme) || "dark"),
    performance: normalizePerformance(localStorage.getItem(STORAGE.performance) || defaultPerformance()),
    developer: normalizeDeveloper(localStorage.getItem(STORAGE.developer) || "off"),
  };

  const syncMetaThemeColor = () => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = state.theme === "light" ? "#f4f6fb" : "#050711";
  };

  const apply = () => {
    root.dataset.petitTheme = state.theme;
    root.dataset.petitPerformance = state.performance;
    root.dataset.petitDeveloper = state.developer === "on" ? "true" : "false";
    root.style.colorScheme = state.theme;
    syncMetaThemeColor();

    document.querySelectorAll("[data-petit-theme-choice]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.petitThemeChoice === state.theme));
    });
    document.querySelectorAll("[data-petit-performance-choice]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.petitPerformanceChoice === state.performance));
    });
    document.querySelectorAll("[data-petit-developer-choice]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.petitDeveloperChoice === state.developer));
    });

    const isDev = state.developer === "on";
    document.querySelectorAll("[data-developer-only]").forEach((el) => {
      if (isDev) el.removeAttribute("hidden");
      else el.setAttribute("hidden", "");
    });
  };

  const setTheme = (theme) => {
    state.theme = normalizeTheme(theme);
    localStorage.setItem(STORAGE.theme, state.theme);
    apply();
  };

  const setPerformance = (performance) => {
    state.performance = normalizePerformance(performance);
    localStorage.setItem(STORAGE.performance, state.performance);
    apply();
    window.dispatchEvent(new CustomEvent("petit:performance-change", {
      detail: { performance: state.performance },
    }));
  };

  const setDeveloper = (developer) => {
    state.developer = normalizeDeveloper(developer);
    localStorage.setItem(STORAGE.developer, state.developer === "on" ? "true" : "false");
    apply();
    window.dispatchEvent(new CustomEvent("petit:developer-mode-change", {
      detail: { developer: state.developer, enabled: state.developer === "on" },
    }));
  };

  const preferenceGroup = ({ label, kind, values }) => {
    const wrapper = document.createElement("div");
    wrapper.className = "petit-preference-group";

    const title = document.createElement("span");
    title.textContent = label;
    wrapper.appendChild(title);

    const control = document.createElement("div");
    control.className = "petit-segmented-control";
    control.setAttribute("role", "group");
    control.setAttribute("aria-label", label);

    values.forEach(({ value, text }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      if (kind === "theme") button.dataset.petitThemeChoice = value;
      else if (kind === "performance") button.dataset.petitPerformanceChoice = value;
      else if (kind === "developer") button.dataset.petitDeveloperChoice = value;
      button.addEventListener("click", () => {
        if (kind === "theme") setTheme(value);
        else if (kind === "performance") setPerformance(value);
        else if (kind === "developer") setDeveloper(value);
      });
      control.appendChild(button);
    });

    wrapper.appendChild(control);
    return wrapper;
  };

  const installSettingsCard = () => {
    const grid = document.querySelector('[data-view-panel="settings"] .settings-grid');
    if (!grid || grid.querySelector("[data-petit-preference-card]")) return;

    const card = document.createElement("section");
    card.className = "settings-card petit-preference-card";
    card.dataset.petitPreferenceCard = "true";

    const head = document.createElement("div");
    head.className = "settings-card__head";
    head.innerHTML = "<div><h3>表示・開発</h3><p>外観・描画負荷および開発者向けオプションを設定します。</p></div>";

    const groups = document.createElement("div");
    groups.className = "petit-preference-groups";
    groups.appendChild(preferenceGroup({
      label: "テーマ",
      kind: "theme",
      values: [
        { value: "dark", text: "Dark" },
        { value: "light", text: "Light" },
      ],
    }));
    groups.appendChild(preferenceGroup({
      label: "描画負荷",
      kind: "performance",
      values: [
        { value: "lite", text: "軽量" },
        { value: "standard", text: "標準" },
      ],
    }));
    groups.appendChild(preferenceGroup({
      label: "開発者オプション",
      kind: "developer",
      values: [
        { value: "off", text: "OFF" },
        { value: "on", text: "ON" },
      ],
    }));

    const devActions = document.createElement("div");
    devActions.className = "petit-preference-dev-actions";
    devActions.setAttribute("data-developer-only", "");
    if (state.developer !== "on") devActions.setAttribute("hidden", "");

    const exportBtn = document.createElement("button");
    exportBtn.type = "button";
    exportBtn.className = "petit-preference-export-btn";
    exportBtn.setAttribute("data-open-chat-log", "");
    exportBtn.textContent = "会話ログを取得";
    exportBtn.addEventListener("click", () => {
      window.PetitChatLog?.open?.();
    });
    devActions.appendChild(exportBtn);

    const note = document.createElement("p");
    note.className = "petit-preference-note";
    note.textContent = "軽量表示では背景・軌道の常時アニメーションと一部ぼかしを抑えます。開発者オプションをONにすると会話ログ取得UIが有効になります。";

    card.append(head, groups, devActions, note);
    grid.prepend(card);
    apply();
  };

  const updateViewportMetrics = () => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const keyboardInset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
    root.style.setProperty("--petit-keyboard-inset", `${Math.round(keyboardInset)}px`);
    root.style.setProperty("--petit-visual-viewport-height", `${Math.round(viewport.height)}px`);
  };

  const installViewportTracking = () => {
    updateViewportMetrics();
    const viewport = window.visualViewport;
    if (!viewport) return;
    viewport.addEventListener("resize", updateViewportMetrics, { passive: true });
    viewport.addEventListener("scroll", updateViewportMetrics, { passive: true });
  };

  const boot = () => {
    apply();
    installSettingsCard();
    installViewportTracking();

    document.addEventListener("click", (event) => {
      const tab = event.target instanceof Element ? event.target.closest('[data-view="settings"]') : null;
      if (tab) queueMicrotask(installSettingsCard);
    }, true);
  };

  window.PetitUiPreferences = {
    initialized: true,
    theme: () => state.theme,
    performance: () => state.performance,
    developer: () => state.developer === "on",
    setTheme,
    setPerformance,
    setDeveloper,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
