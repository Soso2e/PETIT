// PETIT Today view: an actionable daily dashboard backed by work sessions.
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
    return Number.isNaN(date.getTime())
      ? "—"
      : date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  };

  const formatDate = (value) => {
    const date = new Date(`${value || ""}T00:00:00`);
    return Number.isNaN(date.getTime())
      ? (value || "今日")
      : date.toLocaleDateString("ja-JP", { month: "long", day: "numeric", weekday: "short" });
  };

  const requestJson = async (url) => {
    const response = await fetch(url, { cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  const empty = (copy) => {
    const element = document.createElement("p");
    element.className = "today-empty";
    element.textContent = copy;
    return element;
  };

  const activateView = (view) => {
    if (window.PetitAppShell?.activateView) {
      window.PetitAppShell.activateView(view);
      return;
    }
    document.querySelector(`[data-view="${view}"]`)?.click();
  };

  const ensureDashboard = () => {
    const grid = document.querySelector(".today-grid");
    const summary = document.querySelector(".today-card--summary");
    const active = byId("today-active")?.closest(".today-card");
    if (!grid || !summary || !active) return;
    grid.classList.add("today-dashboard");
    summary.classList.add("today-card--hero");
    active.classList.add("today-card--now");

    if (!summary.querySelector(".today-quick-actions")) {
      const actions = document.createElement("div");
      actions.className = "today-quick-actions";
      actions.innerHTML = `
        <button type="button" data-today-go="focus">Focusを始める</button>
        <button type="button" data-today-go="universe">Lifeを見る</button>
        <button type="button" data-today-go="tasks">Tasksを整理</button>
      `;
      summary.appendChild(actions);
      actions.addEventListener("click", (event) => {
        const button = event.target instanceof Element ? event.target.closest("[data-today-go]") : null;
        if (button) activateView(button.dataset.todayGo);
      });
    }

    if (!byId("today-metrics")) {
      const metrics = document.createElement("section");
      metrics.id = "today-metrics";
      metrics.className = "today-card today-card--metrics";
      metrics.innerHTML = `
        <div><span>セッション</span><strong id="today-session-count">0</strong><small>回</small></div>
        <div><span>取り組み</span><strong id="today-project-count">0</strong><small>件</small></div>
        <div><span>最長Focus</span><strong id="today-longest">0分</strong></div>
      `;
      active.insertAdjacentElement("afterend", metrics);
    }
  };

  const render = (data) => {
    ensureDashboard();
    const sessions = Array.isArray(data.sessions) ? data.sessions : [];
    const tasksData = Array.isArray(data.tasks) ? data.tasks : [];
    const projectsData = Array.isArray(data.projects) ? data.projects : [];
    const total = Number(data.total_seconds || 0);
    const longest = sessions.reduce(
      (maximum, session) => Math.max(maximum, Number(session.elapsed_seconds || 0)),
      0,
    );

    byId("today-title").textContent = `${formatDate(data.date)}の流れ`;
    byId("today-total").textContent = formatDuration(total);
    byId("today-message").textContent = data.active
      ? `いまは「${data.active.task || "作業"}」に集中しています。終わるまでTodayから見守ります。`
      : total
        ? `今日は${formatDuration(total)}進みました。次の1個はLifeかFocusから選べます。`
        : "まだ作業記録はありません。Lifeから星を選んで始めよう。";

    const active = data.active;
    const activeCard = byId("today-active")?.closest(".today-card");
    activeCard?.classList.toggle("is-working", Boolean(active));
    byId("today-active").textContent = active?.task || "次のFocusを選べます";
    byId("today-active-meta").textContent = active
      ? `${active.status === "paused" ? "一時停止中" : "作業中"} · ${formatTime(active.started_at)}開始`
      : "Lifeから親Taskへ潜るか、Tasksから1件選んでください。";

    byId("today-session-count").textContent = String(sessions.length);
    byId("today-project-count").textContent = String(projectsData.length);
    byId("today-longest").textContent = formatDuration(longest);

    const timeline = byId("today-timeline");
    timeline.replaceChildren();
    sessions.forEach((session, index) => {
      const row = document.createElement("article");
      row.className = "today-timeline__row";
      if (!session.ended_at) row.classList.add("is-active");
      row.innerHTML = `
        <span>${formatTime(session.started_at)}–${formatTime(session.ended_at)}</span>
        <strong></strong>
        <small>${formatDuration(session.elapsed_seconds)}</small>
        <i aria-hidden="true" style="--today-order:${index}"></i>
      `;
      row.querySelector("strong").textContent = session.task;
      timeline.appendChild(row);
    });
    if (!timeline.children.length) timeline.appendChild(empty("今日の作業はまだありません。"));

    const tasks = byId("today-tasks");
    tasks.replaceChildren();
    tasksData.forEach((task) => {
      const row = document.createElement("article");
      row.className = "today-projects__row";
      const ratio = total ? Math.max(4, Math.round(task.elapsed_seconds / total * 100)) : 0;
      row.innerHTML = `
        <div><strong></strong><span>${formatDuration(task.elapsed_seconds)} · ${ratio}%</span></div>
        <i style="--today-progress:${ratio}%"></i>
      `;
      row.querySelector("strong").textContent = task.task;
      tasks.appendChild(row);
    });
    if (!tasks.children.length) tasks.appendChild(empty("タスク別の記録はまだありません。"));

    const projects = byId("today-projects");
    projects.replaceChildren();
    projectsData.forEach((project) => {
      const row = document.createElement("article");
      row.className = "today-projects__row";
      const ratio = total ? Math.max(4, Math.round(project.elapsed_seconds / total * 100)) : 0;
      row.innerHTML = `
        <div><strong></strong><span>${formatDuration(project.elapsed_seconds)} · ${ratio}%</span></div>
        <i style="--today-progress:${ratio}%"></i>
      `;
      row.querySelector("strong").textContent = project.project;
      projects.appendChild(row);
    });
    if (!projects.children.length) projects.appendChild(empty("取り組み別の記録はまだありません。"));
  };

  const load = async () => {
    const refresh = byId("refresh-today");
    if (refresh) refresh.disabled = true;
    try {
      render(await requestJson("/api/work-sessions/today"));
    } catch (error) {
      ensureDashboard();
      byId("today-message").textContent = `今日の情報を取得できませんでした: ${error.message}`;
    } finally {
      if (refresh) refresh.disabled = false;
    }
  };

  byId("refresh-today")?.addEventListener("click", load);
  document.querySelector('[data-view="today"]')?.addEventListener("click", load);
  window.setInterval(() => {
    const panel = document.querySelector('[data-view-panel="today"]');
    if (panel && !panel.hidden) void load();
  }, 30000);

  ensureDashboard();
  void load();
})();
