// PETIT Universe — Focus Orbit vertical slice.
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
    filter: "active",
    sessionId: localStorage.getItem("petit_session_id") || randomId(),
    history: [],
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

  const normalizeStatus = (value) => String(value || "Ready").trim();
  const isDone = (task) => ["done", "canceled", "cancelled", "chancel"].includes(normalizeStatus(task.status).toLowerCase());
  const taskKey = (task, index = 0) => String(task.id || task.external_id || task.url || `task-${index}`);
  const text = (value, fallback = "—") => {
    const normalized = String(value ?? "").trim();
    return normalized || fallback;
  };

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
    if (values.includes("conflict")) return ["競合あり", "error"];
    if (values.includes("failed")) return ["同期失敗あり", "error"];
    if (values.includes("pending")) return ["Notionへ同期中", "warning"];
    return ["Notion同期済み", "synced"];
  };

  const areaLabel = (value) => ({
    personal: "Personal",
    group: "Group",
    university: "University",
    work: "Work",
  }[value] || "Unsorted");

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
    const ring = status === "doing" || status === "now"
      ? 0.26
      : priority === "high" ? 0.34 : priority === "low" ? 0.46 : 0.41;
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
    byId("chat-context-copy").textContent = "このActionを中心にPETITへ相談できます。";
  };

  const renderOrbit = () => {
    nodesEl.replaceChildren();
    const visible = state.tasks.filter((task) => !isDone(task)).slice(0, 10);
    visible.forEach((task, index) => {
      const key = taskKey(task, index);
      const priority = String(task.priority || "Mid").toLowerCase();
      const status = normalizeStatus(task.status).toLowerCase();
      const sync = syncClass(task);
      const button = document.createElement("button");
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
      const label = document.createElement("span");
      label.className = "space-node__label";
      label.textContent = text(task.title, "名称未設定");
      button.appendChild(label);
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
    fragment.querySelector('[data-detail="title"]').textContent = text(task.title, "名称未設定");
    fragment.querySelector('[data-detail="status"]').textContent = normalizeStatus(task.status);
    fragment.querySelector('[data-detail="priority"]').textContent = text(task.priority, "未設定");
    fragment.querySelector('[data-detail="due"]').textContent = text(task.due_date, "期限なし");
    fragment.querySelector('[data-detail="sync"]').textContent = syncClass(task);
    fragment.querySelector('[data-detail="reason"]').textContent = text(task.reason || task.summary, "メモはありません。");
    fragment.querySelector('[data-action="activate"]').addEventListener("click", () => activateTask(task, index));
    fragment.querySelector('[data-action="chat"]').addEventListener("click", () => {
      switchView("chat");
      chatInputEl.value = `「${text(task.title, "このタスク")}」について、次の一手を整理して`;
      chatInputEl.focus();
    });
    detailPanelEl.appendChild(fragment);
  };

  const filteredTasks = () => {
    if (state.filter === "high") {
      return state.tasks.filter((task) => String(task.priority || "").toLowerCase() === "high" && !isDone(task));
    }
    if (state.filter === "all") return state.tasks;
    return state.tasks.filter((task) => !isDone(task));
  };

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
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 6;
      cell.textContent = "表示できるタスクがありません。";
      row.appendChild(cell);
      taskTableBodyEl.appendChild(row);
      return;
    }

    rows.forEach((task, index) => {
      const row = document.createElement("tr");
      appendCell(row, task.title, "task-table__title");
      appendCell(row, normalizeStatus(task.status));
      appendCell(row, task.priority);
      appendCell(row, task.due_date);
      appendCell(row, task.project_title || task.project_name);
      const syncCell = document.createElement("td");
      const sync = syncClass(task);
      const syncLabel = document.createElement("span");
      syncLabel.className = `status-dot status-dot--${sync}`;
      syncLabel.textContent = sync;
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
    state.tasks.forEach((task) => {
      const project = text(task.project_title || task.project_name, "未分類の星座");
      const current = grouped.get(project) || { tasks: [], area: task.area };
      current.tasks.push(task);
      grouped.set(project, current);
    });
    if (!grouped.size) grouped.set("今日のFocus", { tasks: [], area: "personal" });

    grouped.forEach((group, project) => {
      const activeCount = group.tasks.filter((task) => !isDone(task)).length;
      const card = document.createElement("article");
      card.className = "constellation-card";
      const eyebrow = document.createElement("span");
      eyebrow.className = "eyebrow";
      eyebrow.textContent = areaLabel(group.area);
      const heading = document.createElement("h2");
      heading.textContent = project;
      const meta = document.createElement("span");
      meta.className = "constellation-card__meta";
      meta.textContent = `${activeCount} active actions`;
      const stars = document.createElement("div");
      stars.className = "constellation-card__stars";
      for (let index = 0; index < Math.max(1, Math.min(activeCount, 8)); index += 1) {
        stars.appendChild(document.createElement("i"));
      }
      card.append(eyebrow, heading, meta, stars);
      card.addEventListener("click", () => {
        const task = group.tasks.find((item) => !isDone(item));
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
      const response = await fetch(`/api/actions/${encodeURIComponent(approvalId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      appendMessage("assistant", data.reply || (approved ? "実行しました。" : "キャンセルしました。"));
      await loadUniverse();
    } catch (error) {
      appendMessage("assistant", `確認操作に失敗しました: ${error.message}`);
    }
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
    const requestId = randomId();
    appendMessage("user", message);
    const pending = appendMessage("assistant", "考え中…");
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          history: state.history,
          request_id: requestId,
          session_id: state.sessionId,
        }),
      });
      const data = await response.json();
      pending.remove();
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      appendMessage("assistant", data.reply || "返答がありませんでした。", data.pending_actions || []);
      state.history.push(
        { role: "user", content: message },
        { role: "assistant", content: data.reply || "" },
      );
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
