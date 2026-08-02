// PETIT mobile work companion — foreground work tracking and proactive check-ins.
(() => {
  const STORAGE_KEY = "petit_work_companion_v1";
  const MAX_VISIBLE_MESSAGES = 6; // roughly three user/assistant rallies

  const byId = (id) => document.getElementById(id);
  const messagesEl = byId("messages");
  const formEl = byId("chat-form");
  const inputEl = byId("input");
  const historyToggleEl = byId("history-toggle");
  const sessionLabelEl = byId("session-label");
  const workTaskEl = byId("work-task");
  const workToggleEl = byId("work-toggle");
  const workContinueEl = byId("work-continue");
  const workPauseEl = byId("work-pause");
  const workEndEl = byId("work-end");
  const workCheckNowEl = byId("work-check-now");
  const workFrequencyEl = byId("work-frequency");
  const workElapsedEl = byId("work-elapsed");
  const workStateEl = byId("work-state-label");
  const dashboardNextEl = byId("dashboard-next");
  const dashboardTasksEl = byId("dashboard-tasks");
  const dashboardScheduleEl = byId("dashboard-schedule");
  const dashboardRefreshEl = byId("dashboard-refresh");

  if (!messagesEl || !formEl || !inputEl) return;

  const defaultState = () => ({
    active: false,
    paused: false,
    task: "",
    workSessionId: null,
    startedAt: null,
    pausedAt: null,
    pausedTotalMs: 0,
    pauseReason: "",
    endedAt: null,
    frequency: "10",
    nextCheckAt: null,
    lastCheckAt: null,
    lastCheckText: "",
    awaitingResponse: false,
  });

  const loadState = () => {
    try {
      return { ...defaultState(), ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
    } catch (_error) {
      return defaultState();
    }
  };

  let state = loadState();
  let briefing = null;
  let historyExpanded = false;
  let pendingLead = null;
  let proactiveInFlight = false;
  let lastInteractionAt = Date.now();
  let lastServerPollAt = 0;

  const workSessionRequest = async (path, method = "POST", body = null) => {
    const response = await fetch(`/api/work-sessions${path}`, {
      method,
      cache: "no-store",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data.session;
  };

  const syncSessionAction = (action) => {
    if (!state.workSessionId) return Promise.resolve(null);
    return workSessionRequest(`/${encodeURIComponent(state.workSessionId)}/${action}`).catch(() => null);
  };

  const saveState = () => localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  const sessionId = () => localStorage.getItem("petit_session_id") || window.PETIT_SESSION?.id || crypto.randomUUID();
  const internalPrefix = () => window.PETIT_SESSION?.internalPrefix || "[PETIT_INTERNAL_EVENT]";
  const newWorkSessionId = () => (
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `work_${Date.now()}_${Math.random().toString(36).slice(2)}`
  );
  const ensureWorkSessionId = () => {
    if (!state.active) return null;
    if (!state.workSessionId) {
      state.workSessionId = newWorkSessionId();
      saveState();
    }
    return state.workSessionId;
  };

  const formatElapsed = (totalMs) => {
    const minutes = Math.max(0, Math.floor(totalMs / 60000));
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return hours ? `${hours}時間${rest}分` : `${minutes}分`;
  };

  const elapsedMs = () => {
    if (!state.active || !state.startedAt) return 0;
    const end = state.paused && state.pausedAt ? state.pausedAt : Date.now();
    return Math.max(0, end - state.startedAt - Number(state.pausedTotalMs || 0));
  };

  const intervalMs = () => {
    if (state.frequency === "10") return 10 * 60 * 1000;
    if (state.frequency === "20") return 20 * 60 * 1000;
    return null;
  };

  const scheduleNextCheck = (from = Date.now()) => {
    const interval = intervalMs();
    state.nextCheckAt = interval ? from + interval : null;
    saveState();
  };

  const appendMessage = (role, text, { status = false, error = false } = {}) => {
    const wrap = document.createElement("div");
    wrap.className = `msg msg--${role}` + (status ? " msg--status" : "");
    wrap.dataset.companion = "1";
    const bubble = document.createElement("div");
    bubble.className = "bubble" + (error ? " bubble--error" : "");
    bubble.textContent = text;
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    updateConversationWindow();
    return wrap;
  };

  const removePendingLead = () => {
    if (!pendingLead) return;
    const target = pendingLead;
    pendingLead = null;
    window.setTimeout(() => target.remove(), 550);
  };

  const statusLeadFor = (text) => {
    const normalized = String(text || "").toLowerCase();
    if (/調べ|検索|ニュース|原因|詳しく/.test(normalized)) return "ちょっと調べてみるね！";
    if (/追加|登録|作って|保存|覚えて/.test(normalized)) return "やってみるね～";
    if (/タスク|予定|カレンダー|github|notion|brain|確認|見て/.test(normalized)) return "確認してみるね！";
    return "";
  };

  const updateConversationWindow = () => {
    const rows = Array.from(messagesEl.children).filter((element) => (
      element.classList?.contains("msg")
      && element.id !== "typing"
      && !element.classList.contains("msg--status")
    ));
    const hiddenCount = Math.max(0, rows.length - MAX_VISIBLE_MESSAGES);
    rows.forEach((row, index) => {
      row.classList.toggle("msg--history-hidden", !historyExpanded && index < hiddenCount);
    });
    if (historyToggleEl) {
      historyToggleEl.hidden = rows.length <= MAX_VISIBLE_MESSAGES;
      historyToggleEl.textContent = historyExpanded ? "直近3ラリー" : `履歴を見る（${hiddenCount}件）`;
      historyToggleEl.setAttribute("aria-expanded", String(historyExpanded));
    }
  };

  const nextEventText = () => {
    const event = briefing?.events?.[0];
    if (!event) return "次の予定は取得できていません";
    const raw = String(event.start_time || "");
    const match = raw.match(/T?(\d{2}:\d{2})/);
    const time = match ? match[1] : "";
    return `${time ? `${time} ` : ""}${event.title || "予定"}`;
  };

  const highTasks = () => {
    const tasks = Array.isArray(briefing?.tasks) ? briefing.tasks : [];
    return tasks.filter((task) => String(task.priority || "").toLowerCase() === "high").slice(0, 3);
  };

  const renderDashboard = () => {
    if (dashboardNextEl) dashboardNextEl.textContent = briefing?.next_action || "今日の次の一手を取得中…";
    if (dashboardScheduleEl) dashboardScheduleEl.textContent = nextEventText();
    if (dashboardTasksEl) {
      const tasks = highTasks();
      dashboardTasksEl.replaceChildren();
      if (!tasks.length) {
        const item = document.createElement("li");
        item.textContent = "Highタスクはありません";
        dashboardTasksEl.appendChild(item);
      } else {
        for (const task of tasks) {
          const item = document.createElement("li");
          item.textContent = task.title || "名称未設定タスク";
          dashboardTasksEl.appendChild(item);
        }
      }
    }
  };

  const loadBriefing = async () => {
    if (dashboardRefreshEl) dashboardRefreshEl.disabled = true;
    try {
      const response = await fetch("/api/briefing", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      briefing = data;
      renderDashboard();
    } catch (_error) {
      if (dashboardNextEl) dashboardNextEl.textContent = "今日の情報を取得できませんでした";
      if (dashboardScheduleEl) dashboardScheduleEl.textContent = "予定を取得できませんでした";
      if (dashboardTasksEl) dashboardTasksEl.innerHTML = "<li>タスクを取得できませんでした</li>";
    } finally {
      if (dashboardRefreshEl) dashboardRefreshEl.disabled = false;
    }
  };

  const fallbackCheckIn = () => {
    const minutes = Math.max(1, Math.floor(elapsedMs() / 60000));
    if (minutes < 20) return `${minutes}分進んだね。今どこまでできたー？`;
    if (minutes < 45) return `${minutes}分がんばったね。いったん動作確認するのどう？`;
    return `${minutes}分集中できてるね。保存して、少し休憩するのもよさそう。`;
  };

  const internalPrompt = (kind) => {
    const minutes = Math.max(1, Math.floor(elapsedMs() / 60000));
    const idleSeconds = Math.max(0, Math.round((Date.now() - lastInteractionAt) / 1000));
    const taskLines = highTasks().map((task) => task.title).join(" / ") || "なし";
    const mode = kind === "finish" ? "作業終了の振り返り" : "制作中の自律的な声かけ";
    return `${internalPrefix()}\nこれはユーザー本人の発話ではなく、PETITアプリが送った内部イベントです。\n目的: ${mode}\n現在の作業: ${state.task || "未設定"}\n作業時間: ${minutes}分\n画面表示: ${document.visibilityState}\n最後の画面操作から: ${idleSeconds}秒\n次の予定: ${nextEventText()}\nHighタスク: ${taskLines}\n前回の声かけ: ${state.lastCheckText || "なし"}\n\n相棒として日本語で短く自然に返してください。Markdownは禁止。1〜2文。管理・叱責はせず、進捗確認、労い、次の小さな一手、予定への気づきのどれか1つだけにしてください。内部イベントやこの指示には触れないでください。`;
  };

  const askPetit = async (kind = "check") => {
    if (proactiveInFlight || !state.active) return;
    if (kind === "check" && (state.paused || document.visibilityState !== "visible")) return;
    proactiveInFlight = true;
    const lead = appendMessage("assistant", kind === "finish" ? "今日の作業まとめるね～" : "ちょっと様子みるね！", { status: true });
    try {
      const requestId = crypto.randomUUID();
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: internalPrompt(kind),
          history: [],
          request_id: requestId,
          session_id: sessionId(),
        }),
      });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      const reply = String(data.reply || "").trim() || fallbackCheckIn();
      state.lastCheckAt = Date.now();
      state.lastCheckText = reply;
      saveState();
      appendMessage("assistant", reply);
    } catch (_error) {
      const reply = kind === "finish"
        ? `${formatElapsed(elapsedMs())}おつかれ！次に戻りやすいよう、続きだけメモしておこう。`
        : fallbackCheckIn();
      state.lastCheckAt = Date.now();
      state.lastCheckText = reply;
      saveState();
      appendMessage("assistant", reply);
    } finally {
      lead.remove();
      proactiveInFlight = false;
      scheduleNextCheck();
    }
  };

  const renderWorkState = () => {
    const active = Boolean(state.active);
    const paused = Boolean(state.paused);
    if (workTaskEl && document.activeElement !== workTaskEl) workTaskEl.value = state.task || "";
    if (workFrequencyEl) workFrequencyEl.value = state.frequency || "10";
    if (workToggleEl) workToggleEl.textContent = active ? "作業中" : "作業開始";
    if (workToggleEl) workToggleEl.classList.toggle("is-active", active);
    if (workContinueEl) workContinueEl.hidden = !active || !state.awaitingResponse;
    if (workPauseEl) {
      workPauseEl.hidden = !active;
      workPauseEl.textContent = paused ? "再開" : "一時停止";
    }
    if (workEndEl) workEndEl.hidden = !active;
    if (workCheckNowEl) workCheckNowEl.hidden = !active;
    if (workElapsedEl) workElapsedEl.textContent = active ? formatElapsed(elapsedMs()) : "0分";
    if (workStateEl) workStateEl.textContent = !active ? "待機中" : (paused ? "一時停止中" : "見守り中");
  };

  const startWork = () => {
    const task = String(workTaskEl?.value || briefing?.next_action || "").trim();
    if (!task) {
      workTaskEl?.focus();
      return;
    }
    state = {
      ...state,
      active: true,
      paused: false,
      task,
      workSessionId: newWorkSessionId(),
      startedAt: Date.now(),
      pausedAt: null,
      pausedTotalMs: 0,
      pauseReason: "",
      endedAt: null,
      lastCheckAt: null,
      lastCheckText: "",
    };
    scheduleNextCheck();
    saveState();
    void workSessionRequest("/start", "POST", { session_id: state.workSessionId, task }).catch(() => undefined);
    renderWorkState();
    appendMessage("assistant", `了解！「${task}」やろう。${state.frequency === "quiet" ? "静かに見守るね。" : "様子を見ながら声かけるね。"}`);
  };

  const pauseWork = ({ reason = "", reply = true } = {}) => {
    if (!state.active || state.paused) return false;
    ensureWorkSessionId();
    state.paused = true;
    state.pausedAt = Date.now();
    state.pauseReason = reason;
    state.nextCheckAt = null;
    saveState();
    void syncSessionAction("pause");
    renderWorkState();
    if (reply) appendMessage("assistant", `${formatElapsed(elapsedMs())}進んだね。いったん休憩しよ。`);
    return true;
  };

  const resumeWork = ({ reply = true } = {}) => {
    if (!state.active || !state.paused) return false;
    ensureWorkSessionId();
    const pausedDuration = state.pausedAt ? Date.now() - state.pausedAt : 0;
    state.pausedTotalMs = Number(state.pausedTotalMs || 0) + pausedDuration;
    state.paused = false;
    state.pausedAt = null;
    state.pauseReason = "";
    scheduleNextCheck();
    saveState();
    void syncSessionAction("resume");
    renderWorkState();
    if (reply) appendMessage("assistant", "おかえり。続きからいこー！");
    return true;
  };

  const pauseOrResume = () => {
    if (!state.active) return;
    if (state.paused) resumeWork();
    else pauseWork();
  };

  const endWork = async () => {
    if (!state.active) return;
    const finalElapsed = elapsedMs();
    const task = state.task;
    const sessionIdToEnd = state.workSessionId;
    await askPetit("finish");
    state = { ...defaultState(), frequency: state.frequency, task, endedAt: Date.now() };
    saveState();
    if (sessionIdToEnd) void workSessionRequest(`/${encodeURIComponent(sessionIdToEnd)}/end`).catch(() => undefined);
    renderWorkState();
    appendMessage("assistant", `作業モードを終了したよ。${formatElapsed(finalElapsed)}おつかれ！`);
    void loadBriefing();
  };

  const endWorkImmediately = () => {
    if (!state.active) return null;
    const finalElapsed = elapsedMs();
    const task = state.task;
    const finishedSessionId = ensureWorkSessionId();
    state = {
      ...defaultState(),
      frequency: state.frequency,
      task,
      endedAt: Date.now(),
      lastWorkSessionId: finishedSessionId,
    };
    saveState();
    if (finishedSessionId) void workSessionRequest(`/${encodeURIComponent(finishedSessionId)}/end`).catch(() => undefined);
    renderWorkState();
    void loadBriefing();
    return finalElapsed;
  };

  const pauseReasonFor = (text) => {
    const normalized = String(text || "").trim();
    const match = normalized.match(/^(.{1,80}?)(?:だから|なので|ので|ため(?:に)?|により)[、,\s]*(?:一旦|いったん|少し|ちょっと)?(?:作業を)?(?:止め|停止|休憩)/);
    if (!match) return "";
    return match[1].replace(/^(?:いま|今|作業は|作業を)[、,\s]*/, "").trim();
  };

  const isPhenomenonReport = (text) => {
    const normalized = String(text || "").trim();
    return /(petit|aivis|tts|音声|動画|再生|通信|接続|サーバ|アプリ).{0,30}(途中で)?(?:停止する|停止した|止まる|止まった|切れる|切れた|落ちる|落ちた)/i.test(normalized);
  };

  const classifySessionCommand = (text) => {
    const normalized = String(text || "").trim();
    if (!normalized || isPhenomenonReport(normalized)) return null;

    if (/^(?:再開|作業再開|作業を再開|続き(?:から)?(?:やる|やろう|始める)|戻ろう)(?:[。！!\s]|$)/.test(normalized)) {
      return { kind: "resume", reason: "" };
    }
    if (/(?:今日は|きょうは)?(?:ここまで|この辺で)(?:にする|終わり|終了)?(?:[。！!\s]|$)|^(?:作業を)?(?:終了|終わり|終わる)(?:[。！!\s]|$)/.test(normalized)) {
      return { kind: "end", reason: "" };
    }
    if (/(?:一旦|いったん|少し|ちょっと).*(?:止める|止めよう|停止|休憩)|(?:作業を|作業は).*(?:止める|停止|休憩)|^(?:止める|停止して|休憩する)(?:[。！!\s]|$)/.test(normalized)) {
      return { kind: "pause", reason: pauseReasonFor(normalized) };
    }
    return null;
  };

  const handleSessionCommand = (command) => {
    if (!state.active) {
      appendMessage("assistant", "いま進行中の作業はないよ。作業を始めてから操作してね。");
      return;
    }

    ensureWorkSessionId();
    if (command.kind === "pause") {
      if (state.paused) {
        appendMessage("assistant", "いまの作業はすでに一時停止中だよ。");
        return;
      }
      pauseWork({ reason: command.reason, reply: false });
      appendMessage("assistant", command.reason ? `${command.reason}で一時停止したよ。` : "作業を一時停止したよ。");
      return;
    }

    if (command.kind === "resume") {
      if (!state.paused) {
        appendMessage("assistant", "いまの作業はすでに進行中だよ。");
        return;
      }
      resumeWork({ reply: false });
      appendMessage("assistant", "同じ作業を再開したよ。");
      return;
    }

    if (command.kind === "end") {
      const finalElapsed = endWorkImmediately();
      appendMessage("assistant", `作業を終了したよ。${formatElapsed(finalElapsed)}おつかれ！`);
    }
  };

  const tick = () => {
    renderWorkState();
    if (!state.active || state.paused || proactiveInFlight) return;
    const next = Number(state.nextCheckAt || 0);
    if (!next) {
      scheduleNextCheck();
      return;
    }
    if (Date.now() >= next && document.visibilityState === "visible") {
      void askPetit("check");
    }
    if (Date.now() - lastServerPollAt >= 15000 && state.workSessionId) {
      lastServerPollAt = Date.now();
      void workSessionRequest(`/${encodeURIComponent(state.workSessionId)}`, "GET").then((session) => {
        if (!state.active || session.session_id !== state.workSessionId) return;
        state.awaitingResponse = Boolean(session.awaiting_response_since);
        if (session.status === "auto_stopped") {
          const finalElapsed = endWorkImmediately();
          appendMessage("assistant", `返事がなかったので作業時間を${formatElapsed(finalElapsed)}で止めたよ。続けるときはもう一度開始してね。`);
          return;
        }
        saveState();
        renderWorkState();
      }).catch(() => {
        const maximumLegacyMs = 2 * 20 * 60 * 1000;
        if (state.active && elapsedMs() > maximumLegacyMs) {
          const finalElapsed = endWorkImmediately();
          appendMessage("assistant", `以前の作業状態が残っていたので、${formatElapsed(finalElapsed)}で時間を止めたよ。`);
        }
      });
    }
  };

  formEl.addEventListener("submit", (event) => {
    const text = inputEl.value.trim();
    lastInteractionAt = Date.now();
    window.PETIT_SESSION?.markActive?.();
    if (text && state.active && state.workSessionId) {
      state.awaitingResponse = false;
      saveState();
      void syncSessionAction("respond");
    }

    const command = classifySessionCommand(text);
    if (command) {
      event.preventDefault();
      event.stopImmediatePropagation();
      removePendingLead();
      inputEl.value = "";
      inputEl.style.height = "auto";
      appendMessage("user", text);
      handleSessionCommand(command);
      inputEl.focus();
      return;
    }

    const leadText = statusLeadFor(text);
    if (leadText) {
      removePendingLead();
      pendingLead = appendMessage("assistant", leadText, { status: true });
    }
  }, true);

  for (const eventName of ["pointerdown", "touchstart", "keydown"]) {
    window.addEventListener(eventName, () => {
      lastInteractionAt = Date.now();
    }, { passive: true });
  }

  const messageObserver = new MutationObserver((mutations) => {
    let finalAssistantAdded = false;
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (!(node instanceof Element)) continue;
        const candidates = node.matches(".msg") ? [node] : Array.from(node.querySelectorAll?.(".msg") || []);
        for (const candidate of candidates) {
          if (candidate.id === "typing" || candidate.classList.contains("msg--status")) continue;
          if (candidate.classList.contains("msg--assistant")) finalAssistantAdded = true;
        }
      }
    }
    if (finalAssistantAdded) removePendingLead();
    updateConversationWindow();
  });
  messageObserver.observe(messagesEl, { childList: true });

  historyToggleEl?.addEventListener("click", () => {
    historyExpanded = !historyExpanded;
    updateConversationWindow();
  });
  dashboardRefreshEl?.addEventListener("click", () => void loadBriefing());
  workToggleEl?.addEventListener("click", () => {
    if (!state.active) startWork();
  });
  workContinueEl?.addEventListener("click", () => {
    state.awaitingResponse = false;
    scheduleNextCheck();
    renderWorkState();
    void syncSessionAction("respond");
    appendMessage("assistant", "了解、続行だね。20分後にまた様子を聞くよ。");
  });
  workPauseEl?.addEventListener("click", pauseOrResume);
  workEndEl?.addEventListener("click", () => void endWork());
  workCheckNowEl?.addEventListener("click", () => void askPetit("check"));
  workFrequencyEl?.addEventListener("change", () => {
    state.frequency = workFrequencyEl.value;
    scheduleNextCheck();
    renderWorkState();
  });
  workTaskEl?.addEventListener("change", () => {
    const value = workTaskEl.value.trim();
    if (state.active && value) {
      state.task = value;
      saveState();
      appendMessage("assistant", `作業内容を「${value}」に変えたよ。`);
    }
  });

  if (sessionLabelEl) sessionLabelEl.textContent = window.PETIT_SESSION?.label || "現在の会話";
  renderWorkState();
  updateConversationWindow();
  void loadBriefing();
  window.setInterval(tick, 1000);

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => undefined);
    });
  }
})();
