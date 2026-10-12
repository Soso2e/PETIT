// Statistics use server work-session totals; pauses and midnight clipping belong to Core.
(() => {
  const byId = (id) => document.getElementById(id);
  const panel = document.querySelector('[data-view-panel="today"]');
  if (!panel) return;
  const seconds = (value) => Math.max(0, Number(value) || 0);
  const formatDuration = (value) => {
    const total = seconds(value);
    if (total > 0 && total < 60) return "1分未満";
    const minutes = Math.floor(total / 60);
    const hours = Math.floor(minutes / 60);
    return hours ? `${hours}時間${minutes % 60}分` : `${minutes}分`;
  };
  const formatDate = (value) => {
    const date = new Date(`${value}T00:00:00+09:00`);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric" });
  };
  const formatTime = (value) => {
    const date = new Date(value);
    return !value || Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" });
  };
  const element = (tag, className, copy) => {
    const node = document.createElement(tag);
    node.className = className;
    if (copy != null) node.textContent = copy;
    return node;
  };
  const empty = (copy) => element("p", "stats-empty", copy);
  let generation = 0;
  let controller = null;
  let busy = false;
  let hasToday = false;
  let hasWeek = false;

  const renderToday = (data) => {
    const sessions = Array.isArray(data.sessions) ? data.sessions : [];
    const tasksData = Array.isArray(data.tasks) ? data.tasks : [];
    const total = seconds(data.total_seconds);
    const longest = Math.max(0, ...sessions.map(session => seconds(session.elapsed_seconds)));
    byId("today-title").textContent = `${formatDate(data.date)} 今日の積み重ね`;
    byId("today-total").textContent = formatDuration(total);
    byId("today-message").textContent = total
      ? `今日は、${formatDuration(total)}の積み重ね。${tasksData.length}件のタスクに取り組みました。`
      : "記録はまだありません。最初の一歩から、ここに積み重なっていきます。";
    byId("today-session-count").textContent = String(sessions.length);
    byId("today-task-count").textContent = String(tasksData.length);
    byId("today-longest").textContent = formatDuration(longest);
    const active = data.active;
    byId("today-active").textContent = active ? `${active.status === "paused" ? "一時停止中" : "作業中"}：${active.task || "作業"}` : "いまは作業を記録していません";
    byId("today-active-meta").textContent = active ? `${formatTime(active.started_at)}から` : "";
    document.querySelector(".stats-now").dataset.state = active?.status || "idle";

    const tasks = byId("today-tasks");
    tasks.replaceChildren();
    tasksData.forEach(task => {
      const value = seconds(task.elapsed_seconds);
      const share = total > 0 ? Math.min(100, value / total * 100) : 0;
      const row = element("article", "stats-task-row");
      const header = element("div", "stats-task-label");
      header.append(element("strong", "", task.task || "名前のない作業"), element("span", "", `${formatDuration(value)} · ${Math.round(share)}%`));
      const track = element("div", "stats-task-track");
      const bar = element("div", "stats-task-bar");
      bar.style.width = `${share}%`;
      track.setAttribute("aria-hidden", "true"); track.append(bar);
      row.append(header, track); tasks.append(row);
    });
    if (!tasksData.length) tasks.append(empty("取り組んだタスクがここに並びます。Univから作業を始めてみよう。"));

    const timeline = byId("today-timeline");
    timeline.replaceChildren();
    sessions.forEach(session => {
      const row = element("article", "stats-session-row");
      const end = session.ended_at ? formatTime(session.ended_at) : session.status === "paused" ? "一時停止中" : "進行中";
      const started = new Date(session.started_at);
      const dayStart = new Date(`${data.date}T00:00:00+09:00`);
      const startLabel = started < dayStart ? `${started.toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric" })} ${formatTime(session.started_at)}` : formatTime(session.started_at);
      row.append(element("span", "stats-session-time", `${startLabel}〜${end}`),
        element("strong", "", session.task || "名前のない作業"), element("span", "stats-session-duration", formatDuration(session.elapsed_seconds)));
      timeline.append(row);
    });
    if (!sessions.length) timeline.append(empty("今日の記録はまだありません。休む日も、あなたのペースで。"));
    hasToday = true;
  };

  const renderWeek = (data) => {
    const daily = data.daily;
    byId("stats-week-total").textContent = `7日間で ${formatDuration(data.total_seconds)}`;
    byId("stats-week-period").textContent = `${formatDate(data.date_from)}〜${formatDate(data.date_to)} · 日本時間（JST）`;
    const chart = byId("stats-week-chart"); chart.replaceChildren(); chart.setAttribute("role", "group");
    const max = Math.max(1800, Math.ceil(Math.max(0, ...daily.map(day => seconds(day.elapsed_seconds))) / 1800) * 1800);
    const axis = element("div", "stats-week-axis");
    axis.setAttribute("aria-hidden", "true");
    axis.append(element("span", "", `${Math.round(max / 60)}分`), element("span", "", `${Math.round(max / 120)}分`), element("span", "", "0分"));
    const plot = element("div", "stats-week-plot");
    daily.forEach(day => {
      const value = seconds(day.elapsed_seconds);
      const current = day.date === data.date_to;
      const label = `${formatDate(day.date)}${current ? "（今日）" : ""}`;
      const column = element("div", `stats-week-column${current ? " is-today" : ""}`);
      column.setAttribute("role", "group");
      column.title = `${label}：${formatDuration(value)}（${value}秒）`;
      column.setAttribute("aria-label", column.title);
      column.append(element("span", "stats-week-value", value > 0 && value < 60 ? "<1分" : `${Math.floor(value / 60)}分`));
      const track = element("div", "stats-week-track");
      const bar = element("div", "stats-week-bar"); bar.style.height = `${value / max * 100}%`;
      track.setAttribute("aria-hidden", "true"); track.append(bar);
      column.append(track, element("span", "stats-week-label", current ? "今日" : formatDate(day.date)));
      plot.append(column);
    });
    chart.append(axis, plot);
    if (!daily.some(day => seconds(day.elapsed_seconds) > 0)) chart.append(empty("この7日間はまだ記録がありません。小さな一歩から始めよう。"));
    hasWeek = true;
  };

  const requestJson = async (url, signal) => {
    const response = await fetch(url, { cache: "no-store", signal });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    if (!Number.isFinite(data.total_seconds)) throw new Error("作業記録の形式を確認できませんでした。");
    if (url.endsWith("/today") && (!Array.isArray(data.sessions) || !Array.isArray(data.tasks) || !data.date)) throw new Error("今日の作業記録を確認できませんでした。");
    if (url.includes("/summary") && (!Array.isArray(data.daily) || data.daily.length !== 7 || !data.date_from || !data.date_to)) throw new Error("7日間の作業記録を確認できませんでした。");
    return data;
  };

  const load = async ({ force = false } = {}) => {
    if (panel.hidden || document.hidden || (busy && !force)) return;
    controller?.abort(); controller = new AbortController();
    const currentController = controller;
    const timeout = window.setTimeout(() => currentController.abort(), 15000);
    const token = ++generation;
    busy = true; byId("refresh-today").disabled = true;
    panel.setAttribute("aria-busy", "true");
    byId("stats-load-state").textContent = "作業記録を更新中…";
    byId("stats-week-state").textContent = "";
    const results = await Promise.allSettled([
      requestJson("/api/work-sessions/today", controller.signal),
      requestJson("/api/work-sessions/summary?days=7", controller.signal),
    ]);
    window.clearTimeout(timeout);
    if (token !== generation) return;
    const [today, week] = results;
    if (today.status === "fulfilled") {
      renderToday(today.value);
      byId("stats-load-state").textContent = "";
    } else {
      byId("stats-load-state").textContent = `${hasToday ? "前回の表示です。" : ""}今日の記録を取得できませんでした。更新で再試行できます。`;
      if (!hasToday) byId("today-message").textContent = "記録を取得できませんでした。作業時間は未確認です。";
    }
    if (week.status === "fulfilled" && (today.status !== "fulfilled" || today.value.date === week.value.date_to)) renderWeek(week.value);
    else {
      byId("stats-week-state").textContent = `${hasWeek ? "前回のグラフです。" : ""}7日間の記録を取得できませんでした。`;
      if (!hasWeek) byId("stats-week-chart").replaceChildren(empty("更新して再試行できます。"));
    }
    busy = false; byId("refresh-today").disabled = false; panel.removeAttribute("aria-busy");
  };
  const onViewChange = () => {
    if (!panel.hidden) void load({ force: true });
    else {
      controller?.abort(); generation++; busy = false;
      byId("refresh-today").disabled = false; panel.removeAttribute("aria-busy");
    }
  };
  byId("refresh-today").addEventListener("click", () => void load({ force: true }));
  document.querySelector('[data-view="today"]')?.addEventListener("click", () => void load({ force: true }));
  window.addEventListener("petit:panel-change", onViewChange);
  document.addEventListener("visibilitychange", onViewChange);
  window.setInterval(() => { if (!panel.hidden && !document.hidden) void load(); }, 30000);
  void load();
})();
