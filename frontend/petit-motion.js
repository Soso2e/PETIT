// PETIT Motion Continuity v0.8.0
// Connects Life, Focus, and Tasks with cancelable shared-element transitions.
(() => {
  if (!document.querySelector('.universe-shell') || window.PetitMotion) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const PRIMARY_ORDER = ['universe', 'focus', 'tasks'];
  const ACTIVE_SELECTOR = '.view-tab[data-view].is-active, .view-tab[data-view][aria-selected="true"]';
  const TASK_SELECTOR = [
    '.universe-task[data-task-id]',
    '.constellation-card[data-root-task-id] .constellation-card__header',
    '.space-node[data-task-id]',
    '#objective-node[data-motion-key]',
    '#task-table-body tr[data-task-id]',
  ].join(',');

  let replayingTab = false;
  let transitionId = 0;
  let cleanupActive = null;
  let decorateScheduled = false;
  let lastTasks = [];

  const byId = (id) => document.getElementById(id);
  const activeView = () => document.querySelector(ACTIVE_SELECTOR)?.dataset.view || 'focus';
  const panelFor = (view) => document.querySelector(`[data-view-panel="${CSS.escape(view)}"]`);
  const tabFor = (view) => document.querySelector(`.view-tab[data-view="${CSS.escape(view)}"]`);
  const text = (value) => String(value ?? '').trim();
  const taskIdOf = (element) => {
    if (!(element instanceof Element)) return '';
    return text(
      element.dataset.taskId
      || element.closest('[data-task-id]')?.dataset.taskId
      || element.closest('[data-root-task-id]')?.dataset.rootTaskId,
    );
  };
  const motionKeyForId = (id) => id ? `task-${id}` : '';
  const motionKeyOf = (element) => {
    if (!(element instanceof Element)) return '';
    return text(element.dataset.motionKey || element.closest('[data-motion-key]')?.dataset.motionKey || motionKeyForId(taskIdOf(element)));
  };

  const sanitizeClone = (clone) => {
    clone.removeAttribute('id');
    clone.querySelectorAll('[id]').forEach((node) => node.removeAttribute('id'));
    clone.querySelectorAll('[aria-describedby],[aria-labelledby],[aria-controls]').forEach((node) => {
      node.removeAttribute('aria-describedby');
      node.removeAttribute('aria-labelledby');
      node.removeAttribute('aria-controls');
    });
    clone.setAttribute('aria-hidden', 'true');
    clone.tabIndex = -1;
  };

  const setMotionKey = (element, id) => {
    if (!(element instanceof HTMLElement) || !id) return;
    element.dataset.motionKey = motionKeyForId(id);
  };

  const decorateTableRows = () => {
    const rows = Array.from(document.querySelectorAll('#task-table-body tr'));
    if (!rows.length || !lastTasks.length) return;

    const byTitle = new Map();
    lastTasks.forEach((task) => {
      const title = text(task.title);
      if (!title) return;
      const current = byTitle.get(title) || [];
      current.push(task);
      byTitle.set(title, current);
    });

    rows.forEach((row) => {
      const title = text(row.querySelector('.task-table__title')?.textContent);
      if (!title) return;
      const candidates = byTitle.get(title) || [];
      const due = text(row.querySelector('.task-table__due')?.textContent);
      const project = text(row.children[3]?.textContent);
      const task = candidates.find((candidate) => {
        const candidateDue = text(candidate.due_date || '—');
        const candidateProject = text(candidate.project_title || candidate.project_name || '未分類');
        return (!due || due === candidateDue) && (!project || project === candidateProject);
      }) || candidates[0];
      const id = text(task?.id || task?.external_id || task?.url);
      if (id) {
        row.dataset.taskId = id;
        setMotionKey(row, id);
      }
    });
  };

  const decorateMotionKeys = () => {
    decorateScheduled = false;
    document.querySelectorAll('.universe-task[data-task-id], .space-node[data-task-id]').forEach((element) => {
      setMotionKey(element, element.dataset.taskId);
    });
    document.querySelectorAll('.constellation-card[data-root-task-id]').forEach((card) => {
      const id = card.dataset.rootTaskId;
      setMotionKey(card, id);
      setMotionKey(card.querySelector('.constellation-card__header'), id);
    });
    decorateTableRows();

    const detailTaskId = text(byId('detail-panel')?.dataset.taskId);
    const matchingNode = detailTaskId
      ? document.querySelector(`.space-node[data-task-id="${CSS.escape(detailTaskId)}"]`)
      : null;
    const objective = byId('objective-node');
    if (objective) {
      if (detailTaskId && !matchingNode) setMotionKey(objective, detailTaskId);
      else delete objective.dataset.motionKey;
    }
  };

  const scheduleDecorate = () => {
    if (decorateScheduled) return;
    decorateScheduled = true;
    window.requestAnimationFrame(decorateMotionKeys);
  };

  const visibleMotionElement = (key, view) => {
    if (!key) return null;
    const panel = panelFor(view);
    if (!panel) return null;
    const candidates = Array.from(panel.querySelectorAll(`[data-motion-key="${CSS.escape(key)}"]`));
    return candidates.find((element) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    }) || null;
  };

  const selectedElementForView = (view) => {
    const panel = panelFor(view);
    if (!panel) return null;
    if (view === 'focus') {
      return panel.querySelector('.space-node.is-selected[data-motion-key], #objective-node[data-motion-key]');
    }
    if (view === 'universe') {
      return panel.querySelector('.universe-task.is-selected[data-motion-key], .constellation-card__header.is-selected[data-motion-key], .constellation-card.is-selected [data-motion-key]');
    }
    if (view === 'tasks') {
      return panel.querySelector('#task-table-body tr.is-selected[data-motion-key]');
    }
    return null;
  };

  const cancelActiveTransition = () => {
    transitionId += 1;
    cleanupActive?.();
    cleanupActive = null;
  };

  const animatePanelIn = (panel, from, to) => {
    if (!panel || reducedMotion.matches || typeof panel.animate !== 'function') return null;
    const fromIndex = PRIMARY_ORDER.indexOf(from);
    const toIndex = PRIMARY_ORDER.indexOf(to);
    const delta = fromIndex >= 0 && toIndex >= 0 ? Math.sign(toIndex - fromIndex) : 0;
    const translateX = delta === 0 ? 0 : delta * 24;
    const translateY = delta === 0 ? 8 : 0;
    return panel.animate([
      { opacity: 0.34, transform: `translate3d(${translateX}px, ${translateY}px, 0) scale(.992)`, filter: 'blur(4px)' },
      { opacity: 1, transform: 'translate3d(0, 0, 0) scale(1)', filter: 'blur(0)' },
    ], {
      duration: 360,
      easing: 'cubic-bezier(.2,.82,.2,1)',
      fill: 'both',
    });
  };

  const createGhost = (source) => {
    if (!(source instanceof HTMLElement)) return null;
    const rect = source.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const ghost = source.cloneNode(true);
    sanitizeClone(ghost);
    ghost.classList.add('petit-shared-ghost');
    Object.assign(ghost.style, {
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width}px`,
      height: `${rect.height}px`,
    });
    document.body.appendChild(ghost);
    return { ghost, rect };
  };

  const animateGhost = (ghostData, destination, from, to) => {
    if (!ghostData || !destination || typeof ghostData.ghost.animate !== 'function') return null;
    const end = destination.getBoundingClientRect();
    if (!end.width || !end.height) return null;
    const start = ghostData.rect;
    const translateX = end.left - start.left;
    const translateY = end.top - start.top;
    const scaleX = end.width / Math.max(1, start.width);
    const scaleY = end.height / Math.max(1, start.height);
    const depthForward = from === 'universe' && to === 'focus';
    const depthBack = from === 'focus' && to === 'universe';

    return ghostData.ghost.animate([
      { transform: 'translate3d(0,0,0) scale(1)', opacity: 1, filter: 'blur(0) brightness(1)' },
      {
        transform: `translate3d(${translateX * .45}px, ${translateY * .45}px, ${depthForward ? 80 : depthBack ? -35 : 20}px) scale(${1 + ((scaleX - 1) * .45)}, ${1 + ((scaleY - 1) * .45)})`,
        opacity: .96,
        filter: 'blur(.4px) brightness(1.08)',
        offset: .58,
      },
      { transform: `translate3d(${translateX}px, ${translateY}px, 0) scale(${scaleX}, ${scaleY})`, opacity: .08, filter: 'blur(2px) brightness(1.16)' },
    ], {
      duration: depthForward || depthBack ? 520 : 420,
      easing: 'cubic-bezier(.18,.86,.22,1)',
      fill: 'both',
    });
  };

  const setTransitionState = (from, to, active) => {
    const root = document.documentElement;
    if (active) {
      root.dataset.petitTransitioning = 'true';
      root.dataset.petitTransitionFrom = from;
      root.dataset.petitTransitionTo = to;
    } else {
      delete root.dataset.petitTransitioning;
      delete root.dataset.petitTransitionFrom;
      delete root.dataset.petitTransitionTo;
    }
  };

  const performTransition = async ({ from, to, source = null, activate, motionKey = '' }) => {
    cancelActiveTransition();
    const id = transitionId;
    const key = motionKey || motionKeyOf(source);
    const ghostData = !reducedMotion.matches ? createGhost(source) : null;
    setTransitionState(from, to, true);

    const animations = [];
    let cleaned = false;
    const cleanup = () => {
      if (cleaned) return;
      cleaned = true;
      animations.forEach((animation) => animation?.cancel?.());
      ghostData?.ghost.remove();
      if (id === transitionId) setTransitionState(from, to, false);
      scheduleDecorate();
    };
    cleanupActive = cleanup;

    try {
      await activate();
      if (id !== transitionId) return;
      await new Promise((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)));
      scheduleDecorate();
      decorateMotionKeys();

      const destination = visibleMotionElement(key, to) || selectedElementForView(to);
      const panelAnimation = animatePanelIn(panelFor(to), from, to);
      if (panelAnimation) animations.push(panelAnimation);
      const ghostAnimation = !reducedMotion.matches ? animateGhost(ghostData, destination, from, to) : null;
      if (ghostAnimation) animations.push(ghostAnimation);

      if (!animations.length) return;
      await Promise.allSettled(animations.map((animation) => animation.finished));
    } finally {
      if (id === transitionId) {
        cleanup();
        cleanupActive = null;
      }
    }
  };

  const replayTab = (tab) => {
    replayingTab = true;
    try {
      tab.click();
    } finally {
      replayingTab = false;
    }
  };

  const transitionToView = (to, source = null, key = '') => {
    const from = activeView();
    const tab = tabFor(to);
    if (!tab || from === to) return Promise.resolve();
    const chosenSource = source || selectedElementForView(from);
    return performTransition({
      from,
      to,
      source: chosenSource,
      motionKey: key || motionKeyOf(chosenSource),
      activate: async () => replayTab(tab),
    });
  };

  const transitionTaskToFocus = (source) => {
    const taskId = taskIdOf(source);
    if (!taskId || !window.PetitUniverse?.focusTask) return Promise.resolve(false);
    const from = activeView();
    return performTransition({
      from,
      to: 'focus',
      source,
      motionKey: motionKeyForId(taskId),
      activate: async () => {
        await window.PetitUniverse.focusTask(taskId);
      },
    }).then(() => true);
  };

  const installTabInterception = () => {
    document.addEventListener('click', (event) => {
      if (replayingTab || event.defaultPrevented) return;
      const tab = event.target instanceof Element ? event.target.closest('.view-tab[data-view]') : null;
      if (!(tab instanceof HTMLButtonElement)) return;
      const to = tab.dataset.view;
      if (!to || to === activeView()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      transitionToView(to).catch((error) => {
        console.error('PETIT view transition failed', error);
        replayTab(tab);
      });
    }, true);
  };

  const installTaskInterception = () => {
    document.addEventListener('click', (event) => {
      if (event.defaultPrevented) return;
      const target = event.target instanceof Element ? event.target.closest(TASK_SELECTOR) : null;
      if (!(target instanceof HTMLElement)) return;
      const view = activeView();
      if (!['universe', 'tasks'].includes(view)) return;
      if (!target.classList.contains('is-selected')) return;
      const taskId = taskIdOf(target);
      if (!taskId) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      transitionTaskToFocus(target).catch((error) => {
        console.error('PETIT task-to-focus transition failed', error);
        window.PetitUniverse?.focusTask?.(taskId);
      });
    }, true);

    document.addEventListener('click', (event) => {
      const button = event.target instanceof Element ? event.target.closest('.task-check') : null;
      const row = button?.closest('tr');
      if (!button || !row) return;
      row.classList.add('is-completing');
      window.setTimeout(() => row.classList.remove('is-completing'), 900);
    }, true);
  };

  const installIndicator = () => {
    const nav = document.querySelector('.view-tabs');
    if (!nav) return;
    let indicator = nav.querySelector('.petit-tab-indicator');
    if (!indicator) {
      indicator = document.createElement('span');
      indicator.className = 'petit-tab-indicator';
      indicator.setAttribute('aria-hidden', 'true');
      nav.prepend(indicator);
    }

    const update = () => {
      const active = nav.querySelector('.view-tab[data-view].is-active, .view-tab[data-view][aria-selected="true"]');
      if (!(active instanceof HTMLElement)) return;
      const navRect = nav.getBoundingClientRect();
      const rect = active.getBoundingClientRect();
      nav.style.setProperty('--tab-indicator-x', `${rect.left - navRect.left}px`);
      nav.style.setProperty('--tab-indicator-y', `${rect.top - navRect.top}px`);
      nav.style.setProperty('--tab-indicator-width', `${rect.width}px`);
      nav.style.setProperty('--tab-indicator-height', `${rect.height}px`);
      indicator.dataset.ready = 'true';
    };

    new MutationObserver(update).observe(nav, {
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'aria-selected', 'hidden'],
      childList: true,
    });
    window.addEventListener('resize', update, { passive: true });
    update();
  };

  const installObservers = () => {
    const main = document.querySelector('.universe-main');
    if (main) {
      new MutationObserver(scheduleDecorate).observe(main, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class', 'hidden', 'data-task-id'],
      });
    }
    document.addEventListener('petit:tasks-updated', (event) => {
      lastTasks = Array.isArray(event.detail?.tasks) ? event.detail.tasks : [];
      scheduleDecorate();
    });
  };

  const initialize = () => {
    lastTasks = window.PetitUniverse?.tasks?.() || [];
    installIndicator();
    installObservers();
    installTabInterception();
    installTaskInterception();
    scheduleDecorate();
    document.documentElement.dataset.petitMotionReady = 'true';
  };

  window.PetitMotion = {
    transitionToView,
    transitionTaskToFocus,
    refresh: scheduleDecorate,
    cancel: cancelActiveTransition,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize, { once: true });
  } else {
    initialize();
  }
})();
