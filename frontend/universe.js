// PETIT Universe — Focus Orbit vertical slice.
(() => {
  const state = {
    briefing: null,
    tasks: [],
    selectedTaskId: null,
    activeTaskId: localStorage.getItem("petit_universe_active_task_id"),
    activeStartedAt: Number(localStorage.getItem("petit_universe_active_started_at") || 0),
    filter: "active",
    sessionId: localStorage.getItem("petit_session_id") || crypto.randomUUID(),
    history: [],
  };
  localStorage.setItem("petit_session_id", state.sessionId);

  const byId = (id) => document.getElementById(id);
  const panels = Array.from(document.querySelectorAll("[data-view-panel]"));
  const tabs = Array.from(document.querySelectorAll("[data-view]"));
  const filters = Array.from(document.querySelectorAll("[data-filter]"));
  const orbitEl = byId("orbit");
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

  const normalizeStatus = (value) => String(value || "Ready").trim();
  const isDone = (task) => ["done", "canceled", "cancelled", "chancel"].includes(normalizeStatus(task.status).toLowerCase());
  const taskKey = (task, index = 0) => String(task.id || task.external_id || task.url || `task-${index}`);

  const switchView = (name) => {
    for (const tab of tabs) {
      const active = tab.dataset.view === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    }
    for (const panel of panels) {
      const active = panel.dataset.viewPanel === name;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    }
    if (name === "chat") chatInputEl?.focus();
  };

  tabs.forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));

  const syncClass = (task) => {
    const value = String(task.sync_status || "synced").toLowerCase();
    return ["pending", "synced", "failed", "conflict"].includes(value) ? value : "synced";
  };

  const aggregateSync = () => {
    const values = state.tasks.map(syncClass);
    if (values.includes("conflict")) return ["競合あり", "error"];
    if (values.includes("failed")) return ["同期失敗あり", "error"];
    if (values.includes("pending")) return ["Notionへ同期中", "warning"];
    return ["Notion同期済み", "synced"];
  };

  const areaLabel = (value) => ({ personal: "Personal", group: "Group", university: "University", work: "Work" }[value] || "Unsorted");

  const chooseObjective = () => {
    const active = state.tasks.find((task, index) => taskKey(task, index) === state.activeTaskId);
    if (active?.project_title) return active.project_title;
    if (active?.project_name) return active.project_name;
    const projectTask = state.tasks.find((task) => task.project_title || task.project_name);
    return projectTask?.project_title || projectTask?.project_name || "今日のFocus";
  };

  const orbitPosition = (index, total, task) => {
    const priority = String(task.priority || "Mid").toLowerCase();
    const status = normalizeStatus(task.status).toLowerCase();
    const ring = status === "doing" || status === "now" ? 0.26 : (priority === "high" ? 0.34 : priority === "low" ? 0.46 : 0.41);
    const angle = (-Math.PI / 2) + (Math.PI * 2 * index / Math.max(total, 1));
    return {
      left: `${50 + Math.cos(angle) * ring * 100}%`,
      top: `${50 + Math.sin(angle) * ring * 68}%`,
    };
  };

  const activateTask = (task, index = 0) => {
    const key = taskKey(task, index);
    state.activeTaskId = key;
    state.activeStartedAt = Date.now();
    localStorage.setItem("petit_universe_active_task_id", key);
    localStorage.setItem("petit_universe_active_started_at", String(state.activeStartedAt));
    renderAll();
  };

  const selectedTask = () => state.tasks.find((task, index) => taskKey(task, index) === state.selectedTaskId) || null;
  const activeTask = () => state.tasks.find((task, index) => taskKey(task, index) === state.activeTaskId) || null;

  const selectTask = (task, index = 0) => {
    state.selectedTaskId = taskKey(task, index);
    renderOrbit();
    renderDetail(task, index);
    const title = task.title || "タスク";
    byId("chat-context-title").textContent = title;
    byId("chat-context-copy").textContent = "このActionを中心にPETITへ相談できます。";
  };

  const renderOrbit = () => {
    nodesEl.replaceChildren();
    const visible = state.tasks.filter((task) => !isDone(task)).slice(0, 10);
    visible.forEach((task, index) => {
      const key = taskKey(task, index);
      const button = document.createElement("button");
      const priority = String(task.priority || "Mid").toLowerCase();
      const status = normalizeStatus(task.status).toLowerCase();
      const sync = syncClass(task);
      button.type = "button";
      button.className = [
        "space-node",
        priority === "high" ? "space-node--high" : priority === "low" ? "space-node--low" : "",
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
      button.innerHTML = `<span class="space-node__label"></span>`;
      button.querySelector(".space-node__label").textContent = task.title || "名称未設定";
      button.addEventListener("click", () => selectTask(task, index));
      button.addEventListener("dblclick", () => activateTask(task, index));
      nodesEl.appendChild(button);
    });

    const objective = chooseObjective();
    objectiveNodeEl.querySelector(".space-node__label").textContent = objective;
    focusTitleEl.textContent = objective;
  };

  const renderDetail = (task, index = 0) => {
    detailPanelEl.replaceChildren();
    const fragment = detailTemplate.content.cloneNode(true);
    fragment.querySelector('[data-detail="title"]').textContent = task.title || "名称未設定";
    fragment.querySelector('[data-detail="status"]').textContent = normalizeStatus(task.status);
    fragment.querySelector('[data-detail="priority"]').textContent = task.priority || "未設定";
    fragment.querySelector('[data-detail="due"]').textContent = task.due_date || "期限なし";
    fragment.querySelector('[data-detail="sync"]').textContent = syncClass(task);
    fragment.querySelector('[data-detail="reason"]').textContent = task.reason || task.summary || "メモはありません。";
    fragment.querySelector('[data-action="activate"]').addEventListener("click", () => activateTask(task, index));
    fragment.querySelector('[data-action="chat"]').addEventListener("click", () => {
      switchView("chat");
      chatInputEl.value = `「${task.title || "このタスク"}」について、次の一手を整理して`;
      chatInputEl.focus();
    });
    detailPanelEl.appendChild(fragment);
  };

  const filteredTasks = () => {
    if (state.filter === "high") return state.tasks.filter((task) => String(task.priority || "").toLowerCase() === "high" && !isDone(task));
    if (state.filter === "all") return state.tasks;
    return state.tasks.filter((task) => !isDone(task));
  };

  const renderTaskTable = () => {
    taskTableBodyEl.replaceChildren();
    const rows = filteredTasks();
    if (!rows.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="6">表示できるタスクがありません。</td>';
      taskTableBodyEl.appendChild(tr);
      return;
    }
    rows.forEach((task, index) => {
      const tr = document.createElement("tr");
      const sync = syncClass(task);
      tr.innerHTML = `
        <td></td>
        <td>${normalizeStatus(task.status)}</td>
        <td>${task.priority || "—"}</td>
        <td>${task.due_date || "—"}</td>
        <td>${task.project_title || task.project_name || "—"}</td>
        <td><span class="status-dot status-dot--${sync}">${sync}</span></td>`;
      tr.firstElementChild.textContent = task.title || "名称未設定";
      tr.addEventListener("click", () => {
        selectTask(task, index);
        switchView("focus");
      });
      taskTableBodyEl.appendChild(tr);
    });
  };

  const renderConstellations = () => {
    constellationGridEl.replaceChildren();
    const grouped = new Map();
    state.tasks.forEach((task) => {
      const project = task.project_title || task.project_name || "未分類の星座";
      const current = grouped.get(project) || { tasks: [], area: task.area };
      current.tasks.push(task);
      grouped.set(project, current);
    });
    if (!grouped.size) grouped.set("今日のFocus", { tasks: [], area: "personal" });
    for (const [project, group] of grouped.entries()) {
      const activeCount = group.tasks.filter((task) => !isDone(task)).length;
      const card = document.createElement("article");
      card.className = "constellation-card";
      const stars = Math.max(1, Math.min(activeCount, 8));
      card.innerHTML = `
        <span class="eyebrow">${areaLabel(group.area)}</span>
        <h2></h2>
        <span class="constellation-card__meta">${activeCount} active actions</span>
        <div class="constellation-card__stars">${"<i></i>".repeat(stars)}</div>`;
      card.querySelector("h2").textContent = project;
      card.addEventListener("click", () => {
        const task = group.tasks.find((item) => !isDone(item));
        if (task) selectTask(task, state.tasks.indexOf(task));
        switchView("focus");
      });
      constellationGridEl.appendChild(card);
    }
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
  };

  const renderAll = () => {
    renderOrbit();
    renderTaskTable();
    renderConstellations();
    renderActive();
    renderSync();
    const task = selectedTask();
    if (task) renderDetail(task, state.tasks.indexOf(task));
  };

  const normalizeBriefingTasks = (data) => {
    const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
    return tasks.map((task, index) => ({
      ...task,
      id: task.id || task.external_id || `briefing-${index}`,
      sync_status: task.sync_status || "synced",
    }));
  };

  const loadUniverse = async () => {
    const refresh = byId("refresh-universe");
    if (refresh) refresh.disabled = true;
    try {
      const response = await fetch("/api/briefing", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      state.briefing = data;
      state.tasks = normalizeBriefingTasks(data);
      if (!state.selectedTaskId && state.tasks.length) state.selectedTaskId = taskKey(state.tasks[0], 0);
      renderAll();
    } catch (error) {
      focusTitleEl.textContent = "宇宙を読み込めませんでした";
      objectiveNodeEl.querySelector(".space-node__label").textContent = "再読み込みしてね";
      syncPillEl.textContent = "取得失敗";
      syncPillEl.dataset.state = "error";
      console.error("PETIT Universe load failed", error);
    } finally {
      if (refresh) refresh.disabled = false;
    }
  };

  const appendMessage = (role, text) => {
    const div = document.createElement("div");
    div.className = `message message--${role}`;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  };

  const checkHealth = async () => {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      const data = await response.json();
      const chat = data.chat_model || {};
      chatStatusEl.textContent = chat.server_ok ? `接続済み · ${chat.label || chat.model || "Chat"}` : "Chat未接続";
    } catch (_error) {
      chatStatusEl.textContent = "サーバー未接続";
    }
  };

  const sendChat = async (message) => {
    const requestId = crypto.randomUUID();
    appendMessage("user", message);
    const pending = document.createElement("div");
    pending.className = "message message--assistant";
    pending.textContent = "考え中…";
    messagesEl.appendChild(pending);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history: state.history, request_id: requestId, session_id: state.sessionId }),
      });
      const data = await response.json();
      pending.remove();
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      appendMessage("assistant", data.reply || "返答がありませんでした。");
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
    state.filter = button.dataset.filter;
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
