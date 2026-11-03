// Dashboard 90-day activity map. Core owns all durations, pause and midnight clipping.
(() => {
  "use strict";

  const DAYS = 90;
  const pad = (value) => String(value).padStart(2, "0");
  const dateUTC = (value) => {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const time = Date.parse(value + "T00:00:00Z");
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value
      ? new Date(time) : null;
  };
  const duration = (total) => {
    const minutes = Math.floor(Math.max(0, Number(total) || 0) / 60);
    return minutes >= 60 ? `${Math.floor(minutes / 60)}時間${minutes % 60}分` : `${minutes}分`;
  };
  const intensity = (seconds) => {
    if (seconds <= 0) return 0;
    if (seconds < 1800) return 1;
    if (seconds < 3600) return 2;
    if (seconds < 7200) return 3;
    return 4;
  };
  const summarize = (payload) => {
    if (!payload || payload.days !== DAYS || !Array.isArray(payload.daily) || payload.daily.length !== DAYS) {
      throw new Error("90日間の集計結果を確認できませんでした。");
    }
    const first = dateUTC(payload.date_from);
    const last = dateUTC(payload.date_to);
    if (!first || !last || last.getTime() - first.getTime() !== (DAYS - 1) * 86400000) {
      throw new Error("作業記録の日付範囲が正しくありません。");
    }
    const daily = payload.daily.map((row, index) => {
      const date = dateUTC(row?.date);
      const expected = new Date(first.getTime() + index * 86400000).toISOString().slice(0, 10);
      if (!date || row.date !== expected || !Number.isFinite(row.elapsed_seconds) || row.elapsed_seconds < 0) {
        throw new Error("日別の作業時間を確認できませんでした。");
      }
      return { date: row.date, seconds: row.elapsed_seconds };
    });
    const recent = daily.slice(-30);
    return {
      daily,
      last7: daily.slice(-7).reduce((sum, row) => sum + row.seconds, 0),
      last30: recent.reduce((sum, row) => sum + row.seconds, 0),
      activeDays30: recent.filter((row) => row.seconds > 0).length,
    };
  };

  if (typeof module !== "undefined" && module.exports) module.exports = { summarize, intensity, duration, dateUTC, DAYS };
  if (typeof document === "undefined") return;

  const panel = document.querySelector('[data-view-panel="today"]');
  const grid = document.getElementById("dashboard-activity-days");
  const state = document.getElementById("dashboard-activity-status");
  const dateInput = document.getElementById("stats-date");
  if (!panel || !grid || !state || !dateInput) return;

  const build = (tag, className, content) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content != null) element.textContent = content;
    return element;
  };

  const render = (summary) => {
    document.getElementById("dashboard-metric-week").textContent = duration(summary.last7);
    document.getElementById("dashboard-metric-month").textContent = duration(summary.last30);
    document.getElementById("dashboard-metric-days").textContent = summary.activeDays30 + "日";

    grid.replaceChildren();
    const weekdays = ["月", "火", "水", "木", "金", "土", "日"];
    for (const weekday of weekdays) grid.append(build("span", "dashboard-day-heading", weekday));
    const offset = (dateUTC(summary.daily[0].date).getUTCDay() + 6) % 7;
    for (let i = 0; i < offset; i++) {
      const spacer = build("span", "dashboard-day-spacer");
      spacer.setAttribute("aria-hidden", "true");
      grid.append(spacer);
    }
    const today = summary.daily[summary.daily.length - 1].date;
    for (const row of summary.daily) {
      const cell = build("button", "dashboard-day", String(Number(row.date.slice(-2))));
      cell.type = "button";
      cell.dataset.level = String(intensity(row.seconds));
      cell.dataset.date = row.date;
      cell.classList.toggle("is-today", row.date === today);
      const label = `${row.date}：${duration(row.seconds)}。この日の記録を表示`;
      cell.title = label;
      cell.setAttribute("aria-label", label);
      cell.addEventListener("click", () => {
        if (dateInput.disabled) return;
        dateInput.value = row.date;
        dateInput.dispatchEvent(new Event("change", { bubbles: true }));
      });
      grid.append(cell);
    }
    state.textContent = `${summary.daily[0].date}〜${today} · 日本時間（JST）`;
  };

  let lastLoaded = 0;
  let loading = false;
  const load = async (force = false) => {
    if (panel.hidden || document.hidden || loading || (!force && Date.now() - lastLoaded < 120000)) return;
    loading = true;
    state.textContent = "90日間の作業時間を読み込み中…";
    try {
      const response = await fetch("/api/work-sessions/summary?days=90", {
        credentials: "same-origin",
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error("集計取得失敗（HTTP " + response.status + "）");
      render(summarize(await response.json()));
      lastLoaded = Date.now();
    } catch (error) {
      state.textContent = "90日間の作業記録を取得できませんでした。更新で再試行できます。";
      if (!lastLoaded) grid.replaceChildren();
    } finally {
      loading = false;
    }
  };

  window.PetitDashboardActivity = { reload: () => load(true) };
  window.addEventListener("petit:panel-change", (event) => {
    if (event.detail?.panel === "today") void load();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) void load(); });
  document.getElementById("refresh-today")?.addEventListener("click", () => void load(true));
  if (!panel.hidden) void load();
})();
