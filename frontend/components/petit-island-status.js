/* PETIT Morph Island status controller:
 * Aggregates live session, coding activity, notifications, and chat/voice state
 * into the top-center floating Morph Island.
 */
(() => {
  'use strict';
  if (window.PetitIslandStatus || !window.PetitMorphIsland) return;
  if (!document.querySelector('.universe-shell')) return;

  const ACTIVE_JOB_STATUSES = new Set(['running', 'queued', 'ready_for_review', 'proposed']);
  const POLL_MS = 20000;

  const store = {
    ephemeral: null,       // { state, label, detail, icon, timer }
    activeSession: null,   // work_sessions active object
    codingJobs: [],        // active coding jobs
    notifications: [],     // pending notification events
  };

  let island = null;
  let pollTimer = null;
  let tickTimer = null;
  let fetching = false;

  // "完了しました" is a one-time notice: once the user has gone to Develop for a job, it stays dismissed.
  const SEEN_KEY = 'petit-island-seen-reviews';
  const seenReviews = new Set();
  try {
    const saved = JSON.parse(window.localStorage?.getItem(SEEN_KEY) || '[]');
    if (Array.isArray(saved)) saved.forEach((id) => seenReviews.add(String(id)));
  } catch { /* Storage can be unavailable; the notice then resets on reload. */ }

  const visibleJobs = () => store.codingJobs.filter(
    (job) => !(job.status === 'ready_for_review' && seenReviews.has(String(job.id))),
  );

  const acknowledgeReviews = (ids) => {
    const targets = Array.isArray(ids)
      ? ids
      : store.codingJobs.filter((job) => job.status === 'ready_for_review').map((job) => job.id);
    let changed = false;
    for (const id of targets) {
      if (id == null || seenReviews.has(String(id))) continue;
      seenReviews.add(String(id));
      changed = true;
    }
    if (!changed) return;
    try {
      window.localStorage?.setItem(SEEN_KEY, JSON.stringify([...seenReviews].slice(-200)));
    } catch { /* Kept in memory for this page only. */ }
    syncDisplay();
  };

  const formatElapsed = (session) => {
    if (!session?.started_at) return '00:00';
    const start = Date.parse(session.started_at);
    if (!Number.isFinite(start)) return '00:00';
    let end = Date.now();
    if (session.status === 'paused' && session.paused_at) {
      const pausedAt = Date.parse(session.paused_at);
      if (Number.isFinite(pausedAt)) end = pausedAt;
    }
    const pausedMs = Number(session.paused_total_seconds || 0) * 1000;
    const sec = Math.max(0, Math.floor((end - start - pausedMs) / 1000));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  };

  const navigateTo = (view) => {
    if (window.PetitAppShell?.activateView) {
      window.PetitAppShell.activateView(view);
      return;
    }
    const tab = document.querySelector(`.view-tab[data-view="${view}"]`);
    if (tab instanceof HTMLElement) tab.click();
  };

  const computeView = () => {
    if (store.ephemeral) {
      return store.ephemeral;
    }

    const jobs = visibleJobs();
    const runningJob = jobs.find((j) => j.status === 'running' || j.status === 'queued')
      || jobs[0];
    if (runningJob) {
      const statusText = runningJob.status === 'running'
        ? '開発中'
        : runningJob.status === 'queued'
          ? '開発待機中'
          : runningJob.status === 'ready_for_review'
            ? '完了しました'
            : '開発提案';
      const detail = runningJob.summary
        ? String(runningJob.summary).slice(0, 28)
        : runningJob.status === 'ready_for_review'
          ? 'タップして確認'
          : 'Developで確認できます';
      return {
        state: 'develop',
        label: statusText,
        detail,
        badge: '',
        view: 'development',
      };
    }

    if (store.notifications.length > 0) {
      const latest = store.notifications[0];
      const title = latest?.title || latest?.message || '新しい通知があります';
      return {
        state: 'notification',
        label: String(title).slice(0, 24),
        detail: 'タップして通知を確認',
        badge: `${store.notifications.length}件`,
        view: 'reminders',
      };
    }

    if (store.activeSession && ['active', 'paused'].includes(store.activeSession.status)) {
      const taskName = store.activeSession.task_title || store.activeSession.task || store.activeSession.title || '作業中';
      const paused = store.activeSession.status === 'paused';
      return {
        state: 'session',
        label: paused ? `一時停止: ${taskName}` : taskName,
        detail: '',
        trailing: paused ? '停止中' : formatElapsed(store.activeSession),
        view: 'focus',
      };
    }

    return {
      state: 'idle',
      label: 'PETIT',
      detail: '',
      trailing: '',
      badge: '',
      view: null,
    };
  };

  function syncDisplay() {
    if (!island) return;
    const next = computeView();
    island.setState(next.state, {
      label: next.label,
      detail: next.detail || '',
      trailing: next.trailing || '',
      badge: next.badge || '',
      icon: next.icon,
    });
  }

  const safeFetchJson = async (url) => {
    try {
      const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(6000) });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  };

  const refresh = async () => {
    if (fetching || document.hidden) return;
    fetching = true;
    try {
      const [sessionData, codingData, notifData] = await Promise.all([
        safeFetchJson('/api/work-sessions/active'),
        safeFetchJson('/api/coding/activity?limit=10'),
        safeFetchJson('/api/notifications/events?state=pending&limit=10'),
      ]);
      if (sessionData && 'session' in sessionData) {
        store.activeSession = sessionData.session || null;
      }
      if (codingData && Array.isArray(codingData.jobs)) {
        store.codingJobs = codingData.jobs.filter((j) => ACTIVE_JOB_STATUSES.has(j.status));
      }
      if (notifData && Array.isArray(notifData.events)) {
        store.notifications = notifData.events;
      } else if (notifData && Array.isArray(notifData.items)) {
        store.notifications = notifData.items;
      }
      syncDisplay();
    } finally {
      fetching = false;
    }
  };

  const setEphemeral = (next, autoClearMs = 0) => {
    if (store.ephemeral?.timer) clearTimeout(store.ephemeral.timer);
    if (!next) {
      store.ephemeral = null;
      syncDisplay();
      return;
    }
    const timer = autoClearMs > 0 ? setTimeout(() => {
      store.ephemeral = null;
      syncDisplay();
    }, autoClearMs) : null;
    store.ephemeral = { ...next, timer };
    syncDisplay();
  };

  const onMascotSignal = (event) => {
    const s = event.detail?.state;
    if (s === 'thinking') {
      setEphemeral({ state: 'working', label: '考えています…', detail: '', icon: 'dot', view: 'chat' });
    } else if (s === 'listening') {
      setEphemeral({ state: 'listening', label: '聞いています…', detail: '', icon: 'mic', view: 'chat' });
    } else if (s === 'speaking') {
      setEphemeral({ state: 'listening', label: '話しています…', detail: '', icon: 'mic', view: 'chat' });
    } else if (s === 'approval') {
      setEphemeral({ state: 'notification', label: '承認待ちがあります', detail: 'チャットで確認してください', icon: 'bell', view: 'chat' }, 6000);
    } else if (s === 'error') {
      setEphemeral({ state: 'error', label: '確認が必要です', detail: '', icon: 'alert', view: 'chat' }, 3500);
    } else if (s === 'success') {
      setEphemeral({ state: 'success', label: '完了しました', detail: '', icon: 'check', view: 'chat' }, 2500);
    } else if (s === 'idle' || s === 'happy' || s === 'sleeping') {
      setEphemeral(null);
    }
  };

  const onAreaChange = (event) => {
    if (event.detail?.area === 'development') acknowledgeReviews();
  };

  const mountIsland = () => {
    const dock = document.createElement('div');
    dock.className = 'petit-island-dock';
    document.body.appendChild(dock);

    island = window.PetitMorphIsland.mount(dock, {
      initialState: 'idle',
      onClick: () => {
        const current = computeView();
        if (current.view) {
          navigateTo(current.view);
          if (current.view === 'development') acknowledgeReviews();
        } else {
          void refresh();
        }
      },
    });

    document.addEventListener('petit:mascot', onMascotSignal);
    document.addEventListener('petit:working-task', () => { void refresh(); });
    window.addEventListener('petit:area-change', onAreaChange);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) void refresh();
    });

    tickTimer = setInterval(() => {
      if (!store.ephemeral && store.activeSession?.status === 'active') {
        syncDisplay();
      }
    }, 1000);

    pollTimer = setInterval(() => { void refresh(); }, POLL_MS);
    void refresh();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountIsland, { once: true });
  } else {
    mountIsland();
  }

  window.PetitIslandStatus = Object.freeze({
    refresh,
    acknowledgeReviews,
    setState: (state, overrides) => island?.setState(state, overrides),
    destroy() {
      if (pollTimer) clearInterval(pollTimer);
      if (tickTimer) clearInterval(tickTimer);
      document.removeEventListener('petit:mascot', onMascotSignal);
      window.removeEventListener('petit:area-change', onAreaChange);
      island?.destroy();
    },
  });
})();
