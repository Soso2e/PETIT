// PETIT Universe — Life > Project > Task UI with server-backed work sessions.
(() => {
  const randomId = () => (
    globalThis.crypto?.randomUUID
      ? globalThis.crypto.randomUUID()
      : `petit-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );

  const STORAGE = {
    selectedProject: "petit_universe_selected_project",
    activeTask: "petit_universe_active_task_id",
    workSession: "petit_universe_work_session_id",
  };

  // Remove the old client-only timer. Selection must never count as work time.
  localStorage.removeItem("petit_universe_active_started_at");

  const state = {
    briefing: null,
    tasks: [],
    selectedProject: localStorage.getItem(STORAGE.selectedProject) || "",
    selectedTaskId: null,
    activeTaskId: localStorage.getItem(STORAGE.activeTask),
    workSessionId: localStorage.getItem(STORAGE.workSession),
    workSession: null,
    filter: "high",
    sessionId: localStorage.getItem("petit_session_id") || randomId(),
    history: [],
    busyTaskIds: new Set(),
    workSessionBusy: false,
    autoStopReported: false,
  };
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let orbitFrame = null;
  let orbitClock = 0;
  let orbitLastFrame = 0;
  localStorage.setItem("petit_session_id", state.sessionId);

  const byId = (id) => document.getElementById(id);
  const panels = Array.from(document.querySelectorAll("[data-view-panel]"));
  const tabs = Array.from(document.querySelectorAll("[data-view]"));
  const filters = Array.from(document.querySelectorAll("[data-filter]"));
  const nodesEl = byId("task-nodes");
  const objectiveNodeEl = byId("objective-node");
  const detailPanelEl = byId("detail-panel");
  const detailTemplate = byId("detail-template");
  const taskTableBodyEl = byId("task-table-body");
  const constellationGridEl = byId("constellation-grid");
  const universeSummaryEl = byId("universe-summary");
  const focusTitleEl = byId("focus-title");
  const focusProjectNameEl = byId("focus-project-name");
  const focusProjectSelectEl = byId("focus-project-select");
  const focusEmptyEl = byId("focus-empty");
  const activeLabelEl = byId("active-task-label");
  const activeElapsedEl = byId("active-elapsed");
  const workSessionStateEl = byId("work-session-state");
  const workContinueEl = byId("work-session-continue");
  const workPauseEl = byId("work-session-pause");
  const workEndEl = byId("work-session-end");
  const syncPillEl = byId("sync-pill");
  const messagesEl = byId("messages");
  const chatFormEl = byId("chat-form");
  const chatInputEl = byId("chat-input");
  const chatStatusEl = byId("chat-status");
  const feedbackEl = byId("task-feedback");
  const feedbackCopyEl = feedbackEl?.querySelector("[data-feedback-copy]");
  const feedbackActionEl = feedbackEl?.querySelector("[data-feedback-action]");
  let feedbackTimer = null;
  let lastWorkSessionPollAt = 0;

  const normalizeStatus = (value) => String(value || "Ready").trim();
  const isDone = (task) => ["done", "canceled", "cancelled", "chancel", "完了"].includes(normalizeStatus(task.status).toLowerCase());
  const priorityOf = (task) => String(task.priority || "").trim().toLowerCase();
  const isHigh = (task) => priorityOf(task) === "high";
  const isLow = (task) => priorityOf(task) === "low";
  const isMid = (task) => ["mid", "medium"].includes(priorityOf(task));
  const isRootTask = (task) => task?.hierarchy_role === "root" || !task?.parent_task_id;
  const taskKey = (task, index = 0) => String(task.id || task.external_id || task.url || `task-${index}`);
  const taskProject = (task) => String(task.project_title || task.project_name || "未分類").trim() || "未分類";
  const taskNumericId = (task) => /^\d+$/.test(String(task.id || "")) ? Number(task.id) : null;
  const text = (value, fallback = "—") => {
    const normalized = String(value ?? "").trim();
    return normalized || fallback;
  };
  const highTasks = () => state.tasks.filter((task) => isHigh(task) && !isDone(task));
  const lowTasks = () => state.tasks.filter((task) => isLow(task) && !isDone(task));
  const openTasks = () => state.tasks.filter((task) => !isDone(task));

  const switchView = (name) => {
    tabs.forEach((tab) => {
      const active = tab.dataset.view === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    panels.forEach((panel) => {
      const active = panel.dataset.viewPanel === name;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
    if (name === "chat") chatInputEl?.focus();
  };

  tabs.forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));

  const syncClass = (task) => {
    const value = String(task.sync_status || "synced").toLowerCase();
    return ["pending", "synced", "failed", "conflict"].includes(value) ? value : "synced";
  };

  const aggregateSync = () => {
    const values = state.tasks.map(syncClass);
    if (values.includes("conflict")) return ["同期競合あり", "error"];
    if (values.includes("failed")) return ["同期失敗あり", "error"];
    if (values.includes("pending")) return ["Notionへ同期中", "warning"];
    return ["同期済み", "synced"];
  };

  const areaLabel = (value) => ({
    personal: "Personal",
    group: "Group",
    university: "University",
    work: "Work",
  }[value] || "Unsorted");

  const priorityRank = (task) => {
    if (isHigh(task)) return 0;
    if (isMid(task)) return 1;
    if (isLow(task)) return 2;
    return 3;
  };

  const sortedTasks = (tasks) => [...tasks].sort((left, right) => {
    const priority = priorityRank(left) - priorityRank(right);
    if (priority) return priority;
    const leftDue = String(left.due_date || "9999-12-31");
    const rightDue = String(right.due_date || "9999-12-31");
    return leftDue.localeCompare(rightDue, "ja");
  });

  const projectGroups = () => {
    const grouped = new Map();
    openTasks().forEach((task) => {
      const project = taskProject(task);
      const current = grouped.get(project) || { project, tasks: [], area: task.area };
      current.tasks.push(task);
      if (!current.area && task.area) current.area = task.area;
      grouped.set(project, current);
    });
    return Array.from(grouped.values())
      .map((group) => ({ ...group, tasks: sortedTasks(group.tasks) }))
      .sort((left, right) => {
        const highDifference = right.tasks.filter(isHigh).length - left.tasks.filter(isHigh).length;
        if (highDifference) return highDifference;
        return left.project.localeCompare(right.project, "ja");
      });
  };

  const projectNames = () => projectGroups().map((group) => group.project);
  const projectTasks = (project = state.selectedProject) => openTasks().filter((task) => taskProject(task) === project);
  const focusTasks = () => sortedTasks(projectTasks().filter((task) => !isRootTask(task)));

  const activeTask = () => state.tasks.find((task, index) => taskKey(task, index) === state.activeTaskId) || null;
  const selectedTask = () => state.tasks.find((task, index) => taskKey(task, index) === state.selectedTaskId) || null;

  const ensureSelectedProject = () => {
    const names = projectNames();
    if (!names.length) {
      state.selectedProject = "";
      localStorage.removeItem(STORAGE.selectedProject);
      return;
    }
    if (!names.includes(state.selectedProject)) {
      const active = activeTask();
      if (active && names.includes(taskProject(active))) {
        state.selectedProject = taskProject(active);
      } else {
        const firstWithHigh = projectGroups().find((group) => group.tasks.some(isHigh));
        state.selectedProject = firstWithHigh?.project || names[0];
      }
    }
    localStorage.setItem(STORAGE.selectedProject, state.selectedProject);
  };

  const selectProject = (project, { openFocus = true } = {}) => {
    if (!projectNames().includes(project)) return;
    state.selectedProject = project;
    localStorage.setItem(STORAGE.selectedProject, project);
    const current = selectedTask();
    if (current && taskProject(current) !== project) state.selectedTaskId = null;
    const first = focusTasks()[0] || projectTasks()[0] || null;
    if (!state.selectedTaskId && first) state.selectedTaskId = taskKey(first, state.tasks.indexOf(first));
    renderAll();
    if (openFocus) switchView("focus");
  };

  const moveProject = (direction) => {
    const names = projectNames();
    if (!names.length) return;
    const currentIndex = Math.max(0, names.indexOf(state.selectedProject));
    const nextIndex = (currentIndex + direction + names.length) % names.length;
    selectProject(names[nextIndex]);
  };

  const orbitPosition = (index, total, elapsedSeconds = 0) => {
    const capacity = 8;
    const ringIndex = Math.floor(index / capacity);
    const ringStart = ringIndex * capacity;
    const ringTotal = Math.min(capacity, Math.max(1, total - ringStart));
    const slotIndex = index - ringStart;
    const radiusX = Math.min(43, 25 + (ringIndex * 10));
    const radiusY = Math.min(35, 20 + (ringIndex * 8));
    const duration = 74 + (ringIndex * 18);
    const direction = ringIndex % 2 === 0 ? 1 : -1;
    const angle = (-Math.PI / 2)
      + (Math.PI * 2 * slotIndex / ringTotal)
      + (direction * elapsedSeconds * Math.PI * 2 / duration);
    return {
      left: `${50 + Math.cos(angle) * radiusX}%`,
      top: `${50 + Math.sin(angle) * radiusY}%`,
      ring: ringIndex + 1,
    };
  };

  const stopOrbitMotion = () => {
    if (orbitFrame != null) window.cancelAnimationFrame(orbitFrame);
    orbitFrame = null;
    orbitLastFrame = 0;
  };

  const startOrbitMotion = () => {
    stopOrbitMotion();
    if (reducedMotion.matches || !nodesEl?.children.length) return;
    const tick = (timestamp) => {
      const focusPanelHidden = Boolean(nodesEl.closest("[data-view-panel]")?.hidden);
      const paused = document.hidden
        || focusPanelHidden
        || nodesEl.matches(":hover")
        || nodesEl.matches(":focus-within");
      if (!orbitLastFrame) orbitLastFrame = timestamp;
      const delta = Math.min(50, Math.max(0, timestamp - orbitLastFrame));
      orbitLastFrame = timestamp;
      if (!paused) orbitClock += delta / 1000;
      const nodes = Array.from(nodesEl.querySelectorAll(".space-node[data-orbit-index]"));
      nodes.forEach((node) => {
        const position = orbitPosition(
          Number(node.dataset.orbitIndex || 0),
          Number(node.dataset.orbitTotal || nodes.length),
          orbitClock,
        );
        node.style.left = position.left;
        node.style.top = position.top;
      });
      orbitFrame = window.requestAnimationFrame(tick);
    };
    orbitFrame = window.requestAnimationFrame(tick);
  };

  const showFeedback = (message, actionLabel = "", action = null) => {
    if (!feedbackEl || !feedbackCopyEl || !feedbackActionEl) return;
    if (feedbackTimer) window.clearTimeout(feedbackTimer);
    feedbackCopyEl.textContent = message;
    feedbackActionEl.hidden = !actionLabel || typeof action !== "function";
    feedbackActionEl.textContent = actionLabel;
    feedbackActionEl.onclick = typeof action === "function" ? action : null;
    feedbackEl.hidden = false;
    feedbackTimer = window.setTimeout(() => { feedbackEl.hidden = true; }, action ? 9000 : 4200);
  };

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  const workSessionRequest = async (path, method = "POST", body = null) => {
    const data = await requestJson(`/api/work-sessions${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    return data.session;
  };

  const clearWorkSession = ({ keepTask = false } = {}) => {
    state.workSessionId = null;
    state.workSession = null;
    state.workSessionBusy = false;
    localStorage.removeItem(STORAGE.workSession);
    if (!keepTask) {
      state.activeTaskId = null;
      localStorage.removeItem(STORAGE.activeTask);
    }
  };

  const applyWorkSession = (session, { notifyAutoStop = true } = {}) => {
    if (!session) return;
    state.workSession = session;
    state.workSessionId = session.session_id;
    localStorage.setItem(STORAGE.workSession, session.session_id);
    if (["ended", "auto_stopped"].includes(session.status)) {
      const autoStopped = session.status === "auto_stopped";
      clearWorkSession();
      if (autoStopped && notifyAutoStop && !state.autoStopReported) {
        state.autoStopReported = true;
        showFeedback("20分返事がなかったため、作業時間を自動停止しました。");
      }
    }
  };

  const sessionElapsedMs = () => {
    const session = state.workSession;
    if (!session?.started_at) return 0;
    const start = Date.parse(session.started_at);
    if (!Number.isFinite(start)) return 0;
    let end = Date.now();
    if (session.status === "paused" && session.paused_at) end = Date.parse(session.paused_at);
    if (["ended", "auto_stopped"].includes(session.status) && session.ended_at) end = Date.parse(session.ended_at);
    const pausedMs = Number(session.paused_total_seconds || 0) * 1000;
    return Math.max(0, end - start - pausedMs);
  };

  const formatElapsed = (milliseconds) => {
    const minutes = Math.max(0, Math.floor(milliseconds / 60000));
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return hours ? `${hours}時間${rest}分` : `${minutes}分`;
  };

  const restoreWorkSession = async () => {
    if (!state.workSessionId) return;
    try {
      const session = await workSessionRequest(`/${encodeURIComponent(state.workSessionId)}`, "GET");
      applyWorkSession(session);
    } catch (_error) {
      clearWorkSession();
    }
    renderAll();
  };

  const startTask = async (task, index = 0) => {
    if (state.workSessionBusy) return;
    state.workSessionBusy = true;
    renderAll();
    try {
      const key = taskKey(task, index);
      const sessionId = randomId();
      const session = await workSessionRequest("/start", "POST", {
        session_id: sessionId,
        task: text(task.title, "名称未設定タスク"),
      });
      state.activeTaskId = key;
      state.workSessionId = sessionId;
      state.autoStopReported = false;
      localStorage.setItem(STORAGE.activeTask, key);
      localStorage.setItem(STORAGE.workSession, sessionId);
      applyWorkSession(session, { notifyAutoStop: false });
      selectProject(taskProject(task), { openFocus: false });
      showFeedback(`「${text(task.title, "タスク")}」の作業を開始しました。20分後に確認します。`);
    } catch (error) {
      showFeedback(`作業を開始できませんでした: ${error.message}`);
    } finally {
      state.workSessionBusy = false;
      renderAll();
    }
  };

  const updateWorkSession = async (action) => {
    if (!state.workSessionId || state.workSessionBusy) return;
    state.workSessionBusy = true;
    renderAll();
    try {
      const session = await workSessionRequest(`/${encodeURIComponent(state.workSessionId)}/${action}`);
      applyWorkSession(session, { notifyAutoStop: false });
      const labels = {
        respond: "続行しました。20分後にもう一度確認します。",
        pause: "作業を一時停止しました。",
        resume: "作業を再開しました。",
        end: "作業を終了しました。",
      };
      showFeedback(labels[action] || "作業状態を更新しました。");
      if (action === "end") clearWorkSession();
    } catch (error) {
      showFeedback(`作業状態を更新できませんでした: ${error.message}`);
    } finally {
      state.workSessionBusy = false;
      renderAll();
    }
  };

  const pollWorkSession = async () => {
    if (!state.workSessionId || state.workSessionBusy) return;
    try {
      const session = await workSessionRequest(`/${encodeURIComponent(state.workSessionId)}`, "GET");
      applyWorkSession(session);
      renderActive();
    } catch (_error) {
      clearWorkSession();
      renderActive();
    }
  };

  const selectTask = (task, index = 0) => {
    state.selectedTaskId = taskKey(task, index);
    if (taskProject(task) !== state.selectedProject) {
      state.selectedProject = taskProject(task);
      localStorage.setItem(STORAGE.selectedProject, state.selectedProject);
    }
    renderOrbit();
    renderProjectControls();
    renderDetail(task, index);
    byId("chat-context-title").textContent = text(task.title, "タスク");
    byId("chat-context-copy").textContent = `Life › ${taskProject(task)} › ${text(task.title, "タスク")}`;
  };

  const renderProjectControls = () => {
    const names = projectNames();
    if (focusProjectNameEl) focusProjectNameEl.textContent = state.selectedProject || "Projectなし";
    if (focusProjectSelectEl) {
      const currentValue = state.selectedProject;
      focusProjectSelectEl.replaceChildren();
      names.forEach((project) => {
        const option = document.createElement("option");
        option.value = project;
        option.textContent = project;
        focusProjectSelectEl.appendChild(option);
      });
      focusProjectSelectEl.disabled = !names.length;
      if (names.includes(currentValue)) focusProjectSelectEl.value = currentValue;
    }
    byId("focus-project-prev").disabled = names.length < 2;
    byId("focus-project-next").disabled = names.length < 2;
  };

  const renderOrbit = () => {
    stopOrbitMotion();
    nodesEl.replaceChildren();
    const visible = focusTasks();
    focusEmptyEl.hidden = visible.length > 0;
    visible.forEach((task, index) => {
      const key = taskKey(task, state.tasks.indexOf(task));
      const status = normalizeStatus(task.status).toLowerCase();
      const sync = syncClass(task);
      const button = document.createElement("button");
      button.type = "button";
      button.className = [
        "space-node",
        `space-node--${isHigh(task) ? "high" : (isLow(task) ? "low" : "mid")}`,
        ["waiting", "blocked"].includes(status) ? "space-node--waiting" : "",
        key === state.activeTaskId && state.workSession ? "space-node--active" : "",
        key === state.selectedTaskId ? "is-selected" : "",
        sync === "failed" ? "space-node--failed" : sync === "conflict" ? "space-node--conflict" : "",
      ].filter(Boolean).join(" ");
      const position = orbitPosition(index, visible.length, orbitClock);
      button.style.left = position.left;
      button.style.top = position.top;
      button.dataset.taskId = key;
      button.dataset.orbitIndex = String(index);
      button.dataset.orbitTotal = String(visible.length);
      button.dataset.orbitRing = String(position.ring);
      button.setAttribute("role", "listitem");
      button.setAttribute("aria-label", `${text(task.title, "タスク")}を選択`);
      const label = document.createElement("span");
      label.className = "space-node__label";
      label.textContent = text(task.title, "名称未設定");
      button.appendChild(label);
      button.addEventListener("click", () => selectTask(task, state.tasks.indexOf(task)));
      nodesEl.appendChild(button);
    });

    const project = state.selectedProject || "Projectなし";
    objectiveNodeEl.querySelector(".space-node__label").textContent = project;
    focusTitleEl.textContent = project;
    startOrbitMotion();
  };

  const taskMutation = async (task, operation) => {
    const id = taskNumericId(task);
    if (id == null) {
      showFeedback("このタスクは直接操作できません。PETITへ相談してください。");
      return;
    }
    if (state.busyTaskIds.has(id)) return;
    state.busyTaskIds.add(id);
    renderAll();
    try {
      await operation(id);
    } finally {
      state.busyTaskIds.delete(id);
      renderAll();
    }
  };

  const reopenTaskById = async (id, title) => {
    await requestJson(`/api/notifications/tasks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "Yet", resolve_notification: false }),
    });
    showFeedback(`「${text(title, "タスク")}」を未完了に戻しました。`);
    await loadUniverse();
  };

  const completeTask = async (task) => taskMutation(task, async (id) => {
    const key = taskKey(task, state.tasks.indexOf(task));
    if (key === state.activeTaskId && state.workSessionId) await updateWorkSession("end");
    await requestJson(`/api/notifications/tasks/${encodeURIComponent(id)}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolve_notification: false }),
    });
    const title = text(task.title, "タスク");
    showFeedback(`「${title}」を完了しました。`, "元に戻す", async () => {
      feedbackActionEl.disabled = true;
      try {
        await reopenTaskById(id, title);
      } catch (error) {
        showFeedback(`未完了へ戻せませんでした: ${error.message}`);
      } finally {
        feedbackActionEl.disabled = false;
      }
    });
    await loadUniverse();
  }).catch((error) => showFeedback(`完了にできませんでした: ${error.message}`));

  const toggleTaskBucket = async (task) => taskMutation(task, async (id) => {
    const nextPriority = isLow(task) ? "High" : "Low";
    await requestJson(`/api/notifications/tasks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority: nextPriority, resolve_notification: false }),
    });
    showFeedback(nextPriority === "High" ? "重要なタスクへ移しました。" : "あとでやりたいことへ移しました。");
    await loadUniverse();
  }).catch((error) => showFeedback(`分類を変更できませんでした: ${error.message}`));

  const renderDetailEmpty = () => {
    detailPanelEl.innerHTML = '<div class="detail-panel__empty"><span class="eyebrow">TASK DETAIL</span><h2>タスクを選択</h2><p>星または一覧のタスクを選ぶと詳細を確認できます。時間計測は「作業開始」を押したときだけ始まります。</p></div>';
  };

  const renderDetail = (task, index = 0) => {
    detailPanelEl.replaceChildren();
    const fragment = detailTemplate.content.cloneNode(true);
    fragment.querySelector('[data-detail="title"]').textContent = text(task.title, "名称未設定");
    fragment.querySelector('[data-detail="status"]').textContent = isDone(task) ? "完了" : normalizeStatus(task.status);
    fragment.querySelector('[data-detail="bucket"]').textContent = isLow(task) ? "あとで" : (isHigh(task) ? "重要" : "Mid");
    fragment.querySelector('[data-detail="due"]').textContent = text(task.due_date, "期限なし");
    fragment.querySelector('[data-detail="project"]').textContent = taskProject(task);
    fragment.querySelector('[data-detail="reason"]').textContent = text(task.reason || task.summary, "メモはありません。");
    const sync = syncClass(task);
    const syncEl = fragment.querySelector('[data-detail="sync"]');
    syncEl.textContent = sync === "synced" ? "" : `同期状態: ${sync}`;
    syncEl.hidden = sync === "synced";

    const completeButton = fragment.querySelector('[data-action="complete"]');
    const bucketButton = fragment.querySelector('[data-action="bucket"]');
    const activateButton = fragment.querySelector('[data-action="activate"]');
    const numericId = taskNumericId(task);
    const busy = numericId != null && state.busyTaskIds.has(numericId);
    const key = taskKey(task, index);
    const active = key === state.activeTaskId && Boolean(state.workSession);
    completeButton.disabled = busy || isDone(task) || numericId == null;
    completeButton.textContent = busy ? "処理中…" : (isDone(task) ? "完了済み" : "完了にする");
    bucketButton.disabled = busy || numericId == null;
    bucketButton.textContent = isLow(task) ? "重要に戻す" : "あとでに移す";
    activateButton.disabled = state.workSessionBusy || active;
    activateButton.textContent = active ? "作業中" : "作業開始";
    completeButton.addEventListener("click", () => completeTask(task));
    bucketButton.addEventListener("click", () => toggleTaskBucket(task));
    activateButton.addEventListener("click", () => startTask(task, index));
    fragment.querySelector('[data-action="chat"]').addEventListener("click", () => {
      switchView("chat");
      chatInputEl.value = `「${text(task.title, "このタスク")}」について、次の一手を整理して`;
      chatInputEl.focus();
    });
    detailPanelEl.appendChild(fragment);
  };

  const filteredTasks = () => state.filter === "low" ? lowTasks() : highTasks();

  const appendCell = (row, value, className = "") => {
    const cell = document.createElement("td");
    cell.textContent = text(value);
    if (className) cell.className = className;
    row.appendChild(cell);
    return cell;
  };

  const renderTaskTable = () => {
    taskTableBodyEl.replaceChildren();
    const rows = sortedTasks(filteredTasks());
    byId("task-view-title").textContent = state.filter === "low" ? "あとでやりたいこと" : "重要なタスク";
    byId("task-view-copy").textContent = state.filter === "low"
      ? "Lowだけを分離して表示します。重要タスクとは混ざりません。"
      : "今やる必要があるHighタスクだけを表示します。";
    byId("task-view-count").textContent = `${rows.length}件`;

    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.className = "task-table__empty";
      cell.textContent = state.filter === "low" ? "あとでやりたいことはありません。" : "重要なタスクはありません。";
      row.appendChild(cell);
      taskTableBodyEl.appendChild(row);
      return;
    }

    rows.forEach((task) => {
      const row = document.createElement("tr");
      const actionCell = document.createElement("td");
      const complete = document.createElement("button");
      complete.type = "button";
      complete.className = "task-check";
      complete.setAttribute("aria-label", `${text(task.title, "タスク")}を完了にする`);
      complete.textContent = "✓";
      const numericId = taskNumericId(task);
      complete.disabled = numericId == null || state.busyTaskIds.has(numericId);
      complete.addEventListener("click", (event) => {
        event.stopPropagation();
        completeTask(task);
      });
      actionCell.appendChild(complete);
      row.appendChild(actionCell);
      appendCell(row, task.title, "task-table__title");
      appendCell(row, task.due_date, "task-table__due");
      appendCell(row, taskProject(task));
      const syncCell = document.createElement("td");
      const sync = syncClass(task);
      const syncLabel = document.createElement("span");
      syncLabel.className = `status-dot status-dot--${sync}`;
      syncLabel.textContent = sync === "synced" ? "済" : sync;
      syncCell.appendChild(syncLabel);
      row.appendChild(syncCell);
      row.addEventListener("click", () => {
        selectTask(task, state.tasks.indexOf(task));
        switchView("focus");
      });
      taskTableBodyEl.appendChild(row);
    });
  };

  const createUniverseTaskRow = (task) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `universe-task universe-task--${isHigh(task) ? "high" : (isLow(task) ? "low" : "mid")}`;
    row.dataset.taskId = taskKey(task, state.tasks.indexOf(task));
    const title = document.createElement("span");
    title.className = "universe-task__title";
    title.textContent = text(task.title, "名称未設定");
    const meta = document.createElement("span");
    meta.className = "universe-task__meta";
    meta.textContent = `${isHigh(task) ? "High" : (isLow(task) ? "Low" : "Mid")} · ${text(task.due_date, "期限なし")}`;
    row.append(title, meta);
    row.addEventListener("click", (event) => {
      event.stopPropagation();
      selectTask(task, state.tasks.indexOf(task));
      switchView("focus");
    });
    return row;
  };

  const renderConstellations = () => {
    constellationGridEl.replaceChildren();
    const groups = projectGroups();
    universeSummaryEl.textContent = `Life · ${groups.length} Project · ${openTasks().length} Task`;
    if (!groups.length) {
      const empty = document.createElement("p");
      empty.className = "constellation-empty";
      empty.textContent = "未完了タスクがあるProjectはありません。";
      constellationGridEl.appendChild(empty);
      return;
    }

    groups.forEach((group) => {
      const card = document.createElement("article");
      card.className = "constellation-card constellation-card--list";
      const rootTask = group.tasks.find(isRootTask) || group.tasks[0];
      if (rootTask) card.dataset.rootTaskId = taskKey(rootTask, state.tasks.indexOf(rootTask));
      card.dataset.area = String(group.area || "unsorted").toLowerCase();
      if (group.project === state.selectedProject) card.classList.add("is-selected");

      const header = document.createElement("button");
      header.type = "button";
      header.className = "constellation-card__header";
      const headingWrap = document.createElement("span");
      headingWrap.className = "constellation-card__heading";
      const eyebrow = document.createElement("span");
      eyebrow.className = "eyebrow";
      eyebrow.textContent = `${areaLabel(group.area)} · PROJECT UNIVERSE`;
      const heading = document.createElement("strong");
      heading.textContent = group.project;
      headingWrap.append(eyebrow, heading);
      const counts = document.createElement("span");
      counts.className = "constellation-card__counts";
      const highCount = group.tasks.filter(isHigh).length;
      const midCount = group.tasks.filter(isMid).length;
      const lowCount = group.tasks.filter(isLow).length;
      counts.textContent = `High ${highCount} / Mid ${midCount} / Low ${lowCount}`;
      header.append(headingWrap, counts);
      header.addEventListener("click", () => selectProject(group.project));

      const taskList = document.createElement("div");
      taskList.className = "universe-task-list";
      group.tasks.forEach((task) => taskList.appendChild(createUniverseTaskRow(task)));
      card.append(header, taskList);
      constellationGridEl.appendChild(card);
    });
  };

  const renderActive = () => {
    const task = activeTask();
    const session = state.workSession;
    if (!task || !session) {
      activeLabelEl.textContent = "作業は開始されていません";
      activeElapsedEl.textContent = "0分";
      workSessionStateEl.textContent = "タスクを選択しただけでは時間は増えません。";
      workContinueEl.hidden = true;
      workPauseEl.hidden = true;
      workEndEl.hidden = true;
      return;
    }

    activeLabelEl.textContent = task.title || session.task || "作業中";
    activeElapsedEl.textContent = formatElapsed(sessionElapsedMs());
    const awaiting = Boolean(session.awaiting_response_since);
    const paused = session.status === "paused";
    workSessionStateEl.textContent = awaiting
      ? "20分経過しました。続けているか確認中です。返事がなければ20分後に停止します。"
      : (paused ? "一時停止中" : "計測中 · 20分ごとに継続確認します");
    workContinueEl.hidden = !awaiting;
    workPauseEl.hidden = false;
    workPauseEl.textContent = paused ? "再開" : "一時停止";
    workEndEl.hidden = false;
    workContinueEl.disabled = state.workSessionBusy;
    workPauseEl.disabled = state.workSessionBusy;
    workEndEl.disabled = state.workSessionBusy;
  };

  const renderSync = () => {
    const [label, status] = aggregateSync();
    syncPillEl.textContent = label;
    syncPillEl.dataset.state = status;
    syncPillEl.hidden = status === "synced";
  };

  const renderAll = () => {
    ensureSelectedProject();
    renderProjectControls();
    renderOrbit();
    renderTaskTable();
    renderConstellations();
    renderActive();
    renderSync();
    const task = selectedTask();
    if (task) renderDetail(task, state.tasks.indexOf(task));
    else renderDetailEmpty();
  };

  const normalizeTaskRows = (tasks) => {
    const rows = Array.isArray(tasks) ? tasks : [];
    return rows.map((task, index) => ({
      ...task,
      id: task.id || task.external_id || `task-${index}`,
      sync_status: task.sync_status || "synced",
    }));
  };

  const loadUniverse = async ({ focusTaskId = "", openFocus = false } = {}) => {
    const refresh = byId("refresh-universe");
    if (refresh) refresh.disabled = true;
    try {
      const briefing = await requestJson("/api/briefing");
      state.briefing = briefing;
      let tasks = normalizeTaskRows(briefing.tasks);
      try {
        const allData = await requestJson("/api/notifications/tasks?priority=all&limit=500");
        tasks = normalizeTaskRows(allData.tasks || []);
      } catch (allTaskError) {
        console.warn("PETIT Universe all-task fallback", allTaskError);
        try {
          const [highData, lowData] = await Promise.all([
            requestJson("/api/notifications/tasks?priority=high&limit=200"),
            requestJson("/api/notifications/tasks?priority=low&limit=200"),
          ]);
          tasks = normalizeTaskRows([...(highData.tasks || []), ...(lowData.tasks || [])]);
        } catch (taskListError) {
          console.warn("PETIT Universe task list fallback", taskListError);
        }
      }
      state.tasks = tasks;
      document.dispatchEvent(new CustomEvent("petit:tasks-updated", { detail: { tasks: [...state.tasks] } }));
      if (state.selectedTaskId && !selectedTask()) state.selectedTaskId = null;
      if (state.activeTaskId && !activeTask()) {
        state.activeTaskId = null;
        localStorage.removeItem(STORAGE.activeTask);
      }
      ensureSelectedProject();
      const requestedTask = focusTaskId
        ? state.tasks.find((task, index) => taskKey(task, index) === String(focusTaskId))
        : null;
      if (requestedTask) {
        state.selectedProject = taskProject(requestedTask);
        state.selectedTaskId = taskKey(requestedTask, state.tasks.indexOf(requestedTask));
        localStorage.setItem(STORAGE.selectedProject, state.selectedProject);
      }
      if (!state.selectedTaskId) {
        const first = focusTasks()[0] || projectTasks()[0] || null;
        if (first) state.selectedTaskId = taskKey(first, state.tasks.indexOf(first));
      }
      renderAll();
      if (requestedTask && openFocus) switchView("focus");
    } catch (error) {
      focusTitleEl.textContent = "タスクを読み込めませんでした";
      objectiveNodeEl.querySelector(".space-node__label").textContent = "再読み込みしてね";
      syncPillEl.hidden = false;
      syncPillEl.textContent = "取得失敗";
      syncPillEl.dataset.state = "error";
      console.error("PETIT Universe load failed", error);
    } finally {
      if (refresh) refresh.disabled = false;
    }
  };

  const focusTaskById = async (id, { refresh = false } = {}) => {
    const key = String(id || "");
    if (!key) return false;
    if (refresh) {
      await loadUniverse({ focusTaskId: key, openFocus: true });
      return Boolean(selectedTask());
    }
    const task = state.tasks.find((candidate, index) => taskKey(candidate, index) === key);
    if (!task) return false;
    selectTask(task, state.tasks.indexOf(task));
    switchView("focus");
    return true;
  };

  window.PetitUniverse = {
    focusTask: (id) => focusTaskById(id),
    refreshAndFocusTask: (id) => focusTaskById(id, { refresh: true }),
    tasks: () => [...state.tasks],
  };

  const appendMessage = (role, message, actions = []) => {
    const item = document.createElement("div");
    item.className = `message message--${role}`;
    const copy = document.createElement("div");
    copy.textContent = message;
    item.appendChild(copy);

    if (actions.length) {
      const controls = document.createElement("div");
      controls.className = "chat-actions";
      const action = actions[0];
      const description = document.createElement("small");
      description.textContent = action.name === "complete_task"
        ? `完了: ${text(action.arguments?.title_query || action.arguments?.task_id, "対象タスク")}`
        : `${action.name}を実行します`;
      const approve = document.createElement("button");
      approve.type = "button";
      approve.textContent = action.name === "complete_task" ? "完了にする" : "実行する";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "キャンセル";
      approve.addEventListener("click", () => decideAction(action.approval_id, true, controls));
      cancel.addEventListener("click", () => decideAction(action.approval_id, false, controls));
      controls.append(description, approve, cancel);
      item.appendChild(controls);
    }

    messagesEl.appendChild(item);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return item;
  };

  const decideAction = async (approvalId, approved, controls) => {
    controls.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    try {
      const data = await requestJson(`/api/actions/${encodeURIComponent(approvalId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      appendMessage("assistant", data.reply || (approved ? "実行しました。" : "キャンセルしました。"));
      await loadUniverse();
    } catch (error) {
      appendMessage("assistant", `確認操作に失敗しました: ${error.message}`);
    }
  };

  const checkHealth = async () => {
    try {
      const data = await requestJson("/api/health");
      const chat = data.chat_model || {};
      chatStatusEl.textContent = chat.server_ok ? `接続済み · ${chat.label || chat.model || "Chat"}` : "Chat未接続";
    } catch (_error) {
      chatStatusEl.textContent = "サーバー未接続";
    }
  };

  const sendChat = async (message) => {
    const requestId = randomId();
    appendMessage("user", message);
    const pending = appendMessage("assistant", "考え中…");
    try {
      if (state.workSession?.awaiting_response_since && state.workSessionId) {
        const session = await workSessionRequest(`/${encodeURIComponent(state.workSessionId)}/respond`);
        applyWorkSession(session, { notifyAutoStop: false });
      }
      const data = await requestJson("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history: state.history, request_id: requestId, session_id: state.sessionId }),
      });
      pending.remove();
      appendMessage("assistant", data.reply || "返答がありませんでした。", data.pending_actions || []);
      state.history.push({ role: "user", content: message }, { role: "assistant", content: data.reply || "" });
      await loadUniverse();
    } catch (error) {
      pending.textContent = `通信に失敗しました: ${error.message}`;
    }
  };

  chatFormEl?.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = String(chatInputEl.value || "").trim();
    if (!message) return;
    chatInputEl.value = "";
    sendChat(message);
  });

  chatInputEl?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      chatFormEl.requestSubmit();
    }
  });

  filters.forEach((button) => button.addEventListener("click", () => {
    state.filter = button.dataset.filter === "low" ? "low" : "high";
    filters.forEach((item) => item.classList.toggle("is-active", item === button));
    renderTaskTable();
  }));

  byId("refresh-universe")?.addEventListener("click", async () => {
    await loadUniverse();
    await pollWorkSession();
  });
  objectiveNodeEl?.addEventListener("click", () => switchView("universe"));
  document.querySelector("[data-life-root]")?.addEventListener("click", () => switchView("universe"));
  focusProjectSelectEl?.addEventListener("change", () => selectProject(focusProjectSelectEl.value));
  byId("focus-project-prev")?.addEventListener("click", () => moveProject(-1));
  byId("focus-project-next")?.addEventListener("click", () => moveProject(1));
  workContinueEl?.addEventListener("click", () => updateWorkSession("respond"));
  workPauseEl?.addEventListener("click", () => updateWorkSession(state.workSession?.status === "paused" ? "resume" : "pause"));
  workEndEl?.addEventListener("click", () => updateWorkSession("end"));

  window.setInterval(() => {
    renderActive();
    if (Date.now() - lastWorkSessionPollAt >= 15000) {
      lastWorkSessionPollAt = Date.now();
      void pollWorkSession();
    }
  }, 1000);

  const initialize = async () => {
    checkHealth();
    await loadUniverse();
    await restoreWorkSession();
  };

  initialize();
})();
