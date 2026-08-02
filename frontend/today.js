// PETIT Today view: server-backed daily work summary.
(() => {
  const byId = (id) => document.getElementById(id);
  const formatDuration = (seconds) => {
    const minutes = Math.max(0, Math.floor(Number(seconds || 0) / 60));
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return hours ? `${hours}時間${rest}分` : `${minutes}分`;
  };
  const formatTime = (value) => {
    if (!value) return "進行中";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  };
  const requestJson = async (url) => {
    const response = await fetch(url, { cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };
  const empty = (text) => {
    const element = document.createElement("p");
    element.className = "today-empty";
    element.textContent = text;
    return element;
  };
  const render = (data) => {
    const total = Number(data.total_seconds || 0);
    byId("today-title").textContent = `${data.date || "今日"}の流れ`;
    byId("today-total").textContent = formatDuration(total);
    byId("today-message").textContent = total
      ? `今日は${formatDuration(total)}作業したね。よく進めてる。`
      : "まだ作業記録はありません。Focusから始めよう。";

    const active = data.active;
    byId("today-active").textContent = active?.task || "作業中ではありません";
    byId("today-active-meta").textContent = active
      ? `${active.status === "paused" ? "一時停止中" : "作業中"} · ${formatTime(active.started_at)}開始`
      : "Focusから作業を開始すると、ここに表示されます。";

    const timeline = byId("today-timeline");
    timeline.replaceChildren();
    (data.sessions || []).forEach((session) => {
      const row = document.createElement("article");
      row.className = "today-timeline__row";
      row.innerHTML = `<span>${formatTime(session.started_at)}–${formatTime(session.ended_at)}</span><strong></strong><small>${formatDuration(session.elapsed_seconds)}</small>`;
      row.querySelector("strong").textContent = session.task;
      timeline.appendChild(row);
    });
    if (!timeline.children.length) timeline.appendChild(empty("今日の作業はまだありません。"));

    const projects = byId("today-projects");
    projects.replaceChildren();
    (data.projects || []).forEach((project) => {
      const row = document.createElement("article");
      row.className = "today-projects__row";
      const ratio = total ? Math.max(4, Math.round(project.elapsed_seconds / total * 100)) : 0;
      row.innerHTML = `<div><strong></strong><span>${formatDuration(project.elapsed_seconds)}</span></div><i style="--today-progress:${ratio}%"></i>`;
      row.querySelector("strong").textContent = project.project;
      projects.appendChild(row);
    });
    if (!projects.children.length) projects.appendChild(empty("プロジェクト別の記録はまだありません。"));
  };
  const load = async () => {
    try {
      render(await requestJson("/api/work-sessions/today"));
    } catch (error) {
      byId("today-message").textContent = `今日の情報を取得できませんでした: ${error.message}`;
    }
  };
  byId("refresh-today")?.addEventListener("click", load);
  document.querySelector('[data-view="today"]')?.addEventListener("click", load);
  window.setInterval(() => {
    const panel = document.querySelector('[data-view-panel="today"]');
    if (panel && !panel.hidden) void load();
  }, 30000);
  void load();
})();
