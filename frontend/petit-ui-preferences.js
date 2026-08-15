// PETIT explicit UI preferences: theme, render cost, and mobile viewport handling.
(() => {
  if (window.PetitUiPreferences?.initialized) return;

  const root = document.documentElement;
  const STORAGE = {
    theme: "petit_ui_theme",
    performance: "petit_ui_performance",
  };

  const normalizeTheme = (value) => (value === "light" ? "light" : "dark");
  const normalizePerformance = (value) => (value === "standard" ? "standard" : "lite");

  const defaultPerformance = () => {
    const mobile = window.matchMedia("(max-width: 760px)").matches;
    const lowConcurrency = Number(navigator.hardwareConcurrency || 8) <= 4;
    return mobile || lowConcurrency ? "lite" : "standard";
  };

  const state = {
    theme: normalizeTheme(localStorage.getItem(STORAGE.theme) || "dark"),
    performance: normalizePerformance(localStorage.getItem(STORAGE.performance) || defaultPerformance()),
  };

  const syncMetaThemeColor = () => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = state.theme === "light" ? "#f4f6fb" : "#050711";
  };

  const apply = () => {
    root.dataset.petitTheme = state.theme;
    root.dataset.petitPerformance = state.performance;
    root.style.colorScheme = state.theme;
    syncMetaThemeColor();

    document.querySelectorAll("[data-petit-theme-choice]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.petitThemeChoice === state.theme));
    });
    document.querySelectorAll("[data-petit-performance-choice]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.petitPerformanceChoice === state.performance));
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
      else button.dataset.petitPerformanceChoice = value;
      button.addEventListener("click", () => {
        if (kind === "theme") setTheme(value);
        else setPerformance(value);
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
    head.innerHTML = "<div><h3>表示</h3><p>OSの外観設定とは切り離し、PETIT側で見た目と描画負荷を固定します。</p></div>";

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

    const note = document.createElement("p");
    note.className = "petit-preference-note";
    note.textContent = "軽量表示では背景・軌道の常時アニメーションと一部ぼかしを抑えます。Coreの3D機能自体は維持します。";

    card.append(head, groups, note);
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
    setTheme,
    setPerformance,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
