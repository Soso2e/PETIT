// PETIT Universe — important-task-first UI.
(() => {
  const randomId = () => (
    globalThis.crypto?.randomUUID
      ? globalThis.crypto.randomUUID()
      : `petit-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );

  const state = {
    briefing: null,
    tasks: [],
    selectedTaskId: null,
    activeTaskId: localStorage.getItem("petit_universe_active_task_id"),
    activeStartedAt: Number(localStorage.getItem("petit_universe_active_started_at") || 0),
    filter: "high",
    sessionId: localStorage.getItem("petit_session_id") || randomId(),
    history: [],
    busyTaskIds: new Set(),
  };
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
  const focusTitleEl = byId("focus-title");
  const activeLabelEl = byId("active-task-label");
  const activeElapsedEl = byId("active-elapsed");
  const syncPillEl = byId("sync-pill");
  const messagesEl = byId("messages");
  const chatFormEl = byId("chat-form");
  const chatInputEl = byId("chat-input");
  const chatStatusEl = byId("chat-status");
  const feedbackEl = byId("task-feedback");
  const feedbackCopyEl = feedbackEl?.querySelector("[data-feedback-copy]");
  const feedbackActionEl = feedbackEl?.querySelector("[data-feedback-action]");
  let feedbackTimer = null;

  const normalizeStatus = (value) => String(value || "Ready").trim();
  const isDone = (task) => ["done", "canceled", "cancelled", "chancel"].includes(normalizeStatus(task.status).toLowerCase());
  const priorityOf = (task) => String(task.priority || "").trim().toLowerCase();
  const isHigh = (task) => priorityOf(task) === "high";
  const isLow = (task) => priorityOf(task) === "low";
  const taskKey = (task, index = 0) => String(task.id || task.external_id || task.url || `task-${index}`);
  const taskProject = (task) => task.project_title || task.project_name || "未分類";
  const taskNumericId = (task) => /^\d+$/.test(String(task.id || "")) ? Number(task.id) : null;
  const text = (value, fallback = "—") => {
    const normalized = String(value ?? "").trim();
    return normalized || fallback;
  };
  const highTasks = () => state.tasks.filter((task) => isHigh(task) && !isDone(task));
  const lowTasks = () => state.tasks.filter((task) => isLow(task) && !isDone(task));

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

  const chooseObjective = () => {
    const active = highTasks().find((task, index) => taskKey(task, index) === state.activeTaskId);
    if (active) return taskProject(active);
    const first = highTasks()[0];
    return first ? taskProject(first) : "Highタスクなし";
  };

  const orbitPosition = (index, total, task) => {
    const status = normalizeStatus(task.status).toLowerCase();
    const ring = status === "doing" || status === "now" ? 0.28 : 0.4;
    const angle = (-Math.PI / 2) + (Math.PI * 2 * index / Math.max(total, 1));
    return {
      left: `${50 + Math.cos(angle) * ring * 100}%`,
      top: `${50 + Math.sin(angle) * ring * 68}%`,
    };
  };

  const activeTask = () => state.tasks.find((task, index) => taskKey(task, index) === state.activeTaskId) || null;
  const selectedTask = () => state.tasks.find((task, index) => taskKey(task, index) === state.selectedTaskId) || null;

  const activateTask = (task, index = 0) => {
    const key = taskKey(task, index);
    state.activeTaskId = key;
    state.activeStartedAt = Date.now();
    localStorage.setItem("petit_universe_active_task_id", key);
    localStorage.setItem("petit_universe_active_started_at", String(state.activeStartedAt));
    renderAll();
  };

  const selectTask = (task, index = 0) => {
    state.selectedTaskId = taskKey(task, index);
    renderOrbit();
    renderDetail(task, index);
    byId("chat-context-title").textContent = text(task.title, "タスク");
    byId("chat-context-copy").textContent = "このタスクを中心にPETITへ相談できます。";
  };

  const renderOrbit = () => {
    nodesEl.replaceChildren();
    const visible = highTasks().slice(0, 10);
    visible.forEach((task, index) => {
      const key = taskKey(task, state.tasks.indexOf(task));
      const status = normalizeStatus(task.status).toLowerCase();
      const sync = syncClass(task);
      const button = document.createElement("button");
      button.type = "button";
      button.className = [
        "space-node",
        "space-node--high",
        ["waiting", "blocked"].includes(status) ? "space-node--waiting" : "",
        key === state.activeTaskId ? "space-node--active" : "",
        key === state.selectedTaskId ? "is-selected" : "",
        sync === "failed" ? "space-node--failed" : sync === "conflict" ? "space-node--conflict" : "",
      ].filter(Boolean).join(" ");
      const position = orbitPosition(index, visible.length, task);
      button.style.left = position.left;
      button.style.top = position.top;
      button.dataset.taskId = key;
      button.setAttribute("role", "listitem");
      const label = document.createElement("span");
      label.className = "space-node__label";
      label.textContent = text(task.title, "名称未設定");
      button.appendChild(label);
      button.addEventListener("click", () => selectTask(task, state.tasks.indexOf(task)));
      button.addEventListener("dblclick", () => activateTask(task, state.tasks.indexOf(task)));
      nodesEl.appendChild(button);
    });

    const objective = chooseObjective();
    objectiveNodeEl.querySelector(".space-node__label").textContent = objective;
    focusTitleEl.textContent = objective;
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
    detailPanelEl.innerHTML = '<div class="detail-panel__empty"><span class="eyebrow">TASK DETAIL</span><h2>タスクを選択</h2><p>星または一覧のタスクを選ぶと、完了・分類変更・作業開始ができます。</p></div>';
  };

  const renderDetail = (task, index = 0) => {
    detailPanelEl.replaceChildren();
    const fragment = detailTemplate.content.cloneNode(true);
    fragment.querySelector('[data-detail="title"]').textContent = text(task.title, "名称未設定");
    fragment.querySelector('[data-detail="status"]').textContent = isDone(task) ? "完了" : normalizeStatus(task.status);
    fragment.querySelector('[data-detail="bucket"]').textContent = isLow(task) ? "あとで" : "重要";
    fragment.querySelector('[data-detail="due"]').textContent = text(task.due_date, "期限なし");
    fragment.querySelector('[data-detail="project"]').textContent = taskProject(task);
    fragment.querySelector('[data-detail="reason"]').textContent = text(task.reason || task.summary, "メモはありません。");
    const sync = syncClass(task);
    const syncEl = fragment.querySelector('[data-detail="sync"]');
    syncEl.textContent = sync === "synced" ? "" : `同期状態: ${sync}`;
    syncEl.hidden = sync === "synced";

    const completeButton = fragment.querySelector('[data-action="complete"]');
    const bucketButton = fragment.querySelector('[data-action="bucket"]');
    const numericId = taskNumericId(task);
    const busy = numericId != null && state.busyTaskIds.has(numericId);
    completeButton.disabled = busy || isDone(task) || numericId == null;
    completeButton.textContent = busy ? "処理中…" : (isDone(task) ? "完了済み" : "完了にする");
    bucketButton.disabled = busy || numericId == null;
    bucketButton.textContent = isLow(task) ? "重要に戻す" : "あとでに移す";
    completeButton.addEventListener("click", () => completeTask(task));
    bucketButton.addEventListener("click", () => toggleTaskBucket(task));
    fragment.querySelector('[data-action="activate"]').addEventListener("click", () => activateTask(task, index));
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
    const rows = filteredTasks();
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

  const renderConstellations = () => {
    constellationGridEl.replaceChildren();
    const grouped = new Map();
    highTasks().forEach((task) => {
      const project = taskProject(task);
      const current = grouped.get(project) || { tasks: [], area: task.area };
      current.tasks.push(task);
      grouped.set(project, current);
    });
    if (!grouped.size) {
      const empty = document.createElement("p");
      empty.className = "constellation-empty";
      empty.textContent = "重要タスクが残っているProjectはありません。";
      constellationGridEl.appendChild(empty);
      return;
    }

    grouped.forEach((group, project) => {
      const card = document.createElement("article");
      card.className = "constellation-card";
      const eyebrow = document.createElement("span");
      eyebrow.className = "eyebrow";
      eyebrow.textContent = areaLabel(group.area);
      const heading = document.createElement("h2");
      heading.textContent = project;
      const meta = document.createElement("span");
      meta.className = "constellation-card__meta";
      meta.textContent = `${group.tasks.length} important actions`;
      const stars = document.createElement("div");
      stars.className = "constellation-card__stars";
      for (let index = 0; index < Math.max(1, Math.min(group.tasks.length, 8)); index += 1) stars.appendChild(document.createElement("i"));
      card.append(eyebrow, heading, meta, stars);
      card.addEventListener("click", () => {
        const task = group.tasks[0];
        if (task) selectTask(task, state.tasks.indexOf(task));
        switchView("focus");
      });
      constellationGridEl.appendChild(card);
    });
  };

  const renderActive = () => {
    const task = activeTask();
    activeLabelEl.textContent = task?.title || "まだ実行中のタスクはありません";
    if (!task || !state.activeStartedAt) activeElapsedEl.textContent = "0分";
  };

  const renderSync = () => {
    const [label, status] = aggregateSync();
    syncPillEl.textContent = label;
    syncPillEl.dataset.state = status;
    syncPillEl.hidden = status === "synced";
  };

  const renderAll = () => {
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

  const loadUniverse = async () => {
    const refresh = byId("refresh-universe");
    if (refresh) refresh.disabled = true;
    try {
      const briefing = await requestJson("/api/briefing");
      state.briefing = briefing;
      let tasks = normalizeTaskRows(briefing.tasks);
      try {
        const [highData, lowData] = await Promise.all([
          requestJson("/api/notifications/tasks?priority=high&limit=200"),
          requestJson("/api/notifications/tasks?priority=low&limit=200"),
        ]);
        tasks = normalizeTaskRows([...(highData.tasks || []), ...(lowData.tasks || [])]);
      } catch (taskListError) {
        console.warn("PETIT Universe task list fallback", taskListError);
      }
      state.tasks = tasks;
      if (state.selectedTaskId && !selectedTask()) state.selectedTaskId = null;
      if (!state.selectedTaskId && highTasks().length) state.selectedTaskId = taskKey(highTasks()[0], state.tasks.indexOf(highTasks()[0]));
      renderAll();
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

  byId("refresh-universe")?.addEventListener("click", loadUniverse);
  objectiveNodeEl?.addEventListener("click", () => switchView("universe"));

  window.setInterval(() => {
    const task = activeTask();
    if (!task || !state.activeStartedAt) return;
    const minutes = Math.max(0, Math.floor((Date.now() - state.activeStartedAt) / 60000));
    activeElapsedEl.textContent = `${minutes}分`;
  }, 1000);

  checkHealth();
  loadUniverse();
})();
