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
  let selectedDate = "";
  let renderedDate = "";
  let todayDate = "";
  let noteSaving = false;
  const drafts = new Map();
  const noteInput = byId("stats-reflection-note");
  const noteState = byId("stats-reflection-state");

  const rememberDraft = () => {
    const draft = drafts.get(renderedDate);
    if (draft && noteInput.value !== draft.note) {
      draft.note = noteInput.value; draft.dirty = true;
    }
  };
  const renderReflection = (data) => {
    const previousDate = renderedDate;
    rememberDraft();
    renderedDate = data.date;
    const remote = data.reflection;
    const valid = remote && Number.isInteger(remote.revision) && typeof remote.note === "string";
    let draft = drafts.get(data.date);
    if (!draft?.dirty && !noteSaving && valid) {
      draft = { note: remote.note, revision: remote.revision, dirty: false, notice: draft?.notice || "" };
      drafts.set(data.date, draft);
    }
    noteInput.disabled = !valid;
    byId("stats-reflection-reload").disabled = !valid || noteSaving;
    byId("stats-reflection-save").disabled = !valid || noteSaving;
    if (previousDate !== data.date || !draft?.dirty) noteInput.value = draft?.note || "";
    noteState.textContent = !valid ? "振り返りを取得できません。サーバーの更新・再起動を確認してください。" : draft?.notice || (draft?.dirty ? "未保存の入力があります。" : "");
  };

  const renderToday = (data) => {
    const sessions = Array.isArray(data.sessions) ? data.sessions : [];
    const tasksData = Array.isArray(data.tasks) ? data.tasks : [];
    const total = seconds(data.total_seconds);
    const longest = Math.max(0, ...sessions.map(session => seconds(session.elapsed_seconds)));
    const isToday = !selectedDate || data.date === todayDate;
    byId("stats-date").value = data.date;
    if (todayDate) {
      byId("stats-date").max = todayDate; byId("stats-date").disabled = false; byId("stats-go-today").disabled = false;
    }
    byId("today-title").textContent = `${formatDate(data.date)} ${isToday ? "今日の" : ""}積み重ね`;
    byId("stats-total-label").textContent = `${isToday ? "今日" : formatDate(data.date)}、取り組んだ時間`;
    byId("stats-tasks-title").textContent = `${isToday ? "今日" : formatDate(data.date)}、何に取り組んだ？`;
    byId("stats-sessions-title").textContent = `${isToday ? "今日" : formatDate(data.date)}の作業記録`;
    byId("today-total").textContent = formatDuration(total);
    byId("today-message").textContent = total
      ? `${isToday ? "今日は" : "この日は"}、${formatDuration(total)}の積み重ね。${tasksData.length}件のタスクに取り組みました。`
      : "記録はまだありません。最初の一歩から、ここに積み重なっていきます。";
    byId("today-session-count").textContent = String(sessions.length);
    byId("today-task-count").textContent = String(tasksData.length);
    byId("today-longest").textContent = formatDuration(longest);
    const active = data.active;
    byId("today-active").textContent = active ? `${active.status === "paused" ? "一時停止中" : "作業中"}：${active.task || "作業"}` : "いまは作業を記録していません";
    byId("today-active-meta").textContent = active ? `${formatTime(active.started_at)}から` : "";
    document.querySelector(".stats-now").dataset.state = active?.status || "idle";
    document.querySelector(".stats-now").hidden = !isToday;
    renderReflection(data);

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
    if (!sessions.length) timeline.append(empty(`${isToday ? "今日" : "この日"}の記録はまだありません。休む日も、あなたのペースで。`));
    hasToday = true;
  };

  const renderWeek = (data) => {
    todayDate = data.date_to;
    byId("stats-date").max = todayDate;
    byId("stats-date").disabled = false; byId("stats-go-today").disabled = false;
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
      const column = element("button", `stats-week-column${current ? " is-today" : ""}`);
      column.type = "button";
      column.setAttribute("aria-pressed", String(day.date === (selectedDate || todayDate)));
      column.addEventListener("click", () => chooseDate(day.date));
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
    if (!url.includes("/summary") && (!Array.isArray(data.sessions) || !Array.isArray(data.tasks) || !data.date)) throw new Error("作業記録を確認できませんでした。");
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
      requestJson(selectedDate ? `/api/work-sessions/days/${selectedDate}` : "/api/work-sessions/today", controller.signal),
      requestJson("/api/work-sessions/summary?days=7", controller.signal),
    ]);
    window.clearTimeout(timeout);
    if (token !== generation) return;
    const [today, week] = results;
    if (today.status === "fulfilled") {
      if (!selectedDate) todayDate = today.value.date;
      renderToday(today.value);
      byId("stats-load-state").textContent = "";
    } else {
      byId("stats-load-state").textContent = `${hasToday ? "前回の表示です。" : ""}${selectedDate ? formatDate(selectedDate) : "今日"}の記録を取得できませんでした。更新で再試行できます。`;
      if (!hasToday) byId("today-message").textContent = "記録を取得できませんでした。作業時間は未確認です。";
    }
    if (week.status === "fulfilled" && (selectedDate || today.status !== "fulfilled" || today.value.date === week.value.date_to)) renderWeek(week.value);
    else {
      byId("stats-week-state").textContent = `${hasWeek ? "前回のグラフです。" : ""}7日間の記録を取得できませんでした。`;
      if (!hasWeek) byId("stats-week-chart").replaceChildren(empty("更新して再試行できます。"));
    }
    busy = false; byId("refresh-today").disabled = false; panel.removeAttribute("aria-busy");
  };
  const chooseDate = (date) => {
    rememberDraft();
    selectedDate = date === todayDate ? "" : date;
    hasToday = false;
    renderedDate = "";
    byId("today-total").textContent = "—";
    byId("today-title").textContent = `${formatDate(date)}の記録を読み込み中…`;
    byId("today-message").textContent = "選んだ日の記録を確認しています。";
    for (const id of ["today-session-count", "today-task-count", "today-longest"]) byId(id).textContent = "—";
    byId("today-tasks").replaceChildren(); byId("today-timeline").replaceChildren();
    noteInput.disabled = true; noteInput.value = ""; byId("stats-reflection-save").disabled = true;
    byId("stats-reflection-reload").disabled = true;
    document.querySelector(".stats-now").hidden = true;
    byId("stats-date").value = date;
    void load({ force: true });
  };
  byId("stats-date").addEventListener("change", (event) => {
    if (/^\d{4}-\d{2}-\d{2}$/.test(event.target.value) && event.target.value <= todayDate) chooseDate(event.target.value);
  });
  byId("stats-go-today").addEventListener("click", () => chooseDate(todayDate));
  noteInput.addEventListener("input", () => { rememberDraft(); const draft = drafts.get(renderedDate); if (draft) draft.notice = ""; noteState.textContent = "未保存の入力があります。"; });
  byId("stats-reflection-reload").addEventListener("click", () => {
    const draft = drafts.get(renderedDate);
    if (!renderedDate || noteSaving || (draft?.dirty && !window.confirm("未保存の入力を破棄して、保存済みの振り返りを読み直しますか？必要な入力は先にコピーしてください。"))) return;
    const day = renderedDate; drafts.delete(day); chooseDate(day);
  });
  byId("stats-reflection-form").addEventListener("submit", async (event) => {
    event.preventDefault(); rememberDraft();
    const day = renderedDate; const draft = drafts.get(day);
    if (!draft || noteSaving || noteInput.disabled) return;
    const sentNote = draft.note;
    draft.dirty = true;
    noteSaving = true; byId("stats-reflection-save").disabled = true; byId("stats-reflection-reload").disabled = true;
    noteState.textContent = "振り返りを保存中…";
    draft.notice = "";
    try {
      const response = await fetch(`/api/work-sessions/days/${day}/reflection`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: sentNote, revision: draft.revision }), signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      if (!response.ok || !data.reflection) throw new Error(data.detail || data.error || "保存できませんでした。");
      rememberDraft();
      draft.revision = data.reflection.revision;
      draft.dirty = draft.note !== sentNote;
      if (!draft.dirty) draft.note = data.reflection.note;
      if (renderedDate === day) {
        if (!draft.dirty) noteInput.value = draft.note;
        draft.notice = draft.dirty ? "保存後の変更は未保存です。" : "振り返りを保存しました。";
        noteState.textContent = draft.notice;
      }
    } catch (error) {
      draft.notice = `${error.message} 入力はこの画面に残っています。`;
      if (renderedDate === day) noteState.textContent = draft.notice;
    } finally {
      noteSaving = false; byId("stats-reflection-save").disabled = noteInput.disabled;
      byId("stats-reflection-reload").disabled = noteInput.disabled;
    }
  });
  window.addEventListener("beforeunload", (event) => {
    rememberDraft();
    if ([...drafts.values()].some(draft => draft.dirty)) { event.preventDefault(); event.returnValue = ""; }
  });
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
