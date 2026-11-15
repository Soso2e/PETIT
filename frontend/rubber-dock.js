/* Shared PETIT Rubber Dock. Reuses the existing [data-view] navigation. */
(() => {
  'use strict';
  const existing = document.querySelector('.view-tabs');
  if (!existing || document.querySelector('.petit-rubber-dock')) return;
  const definitions = [
    { name: 'Chat', view: 'chat', icon: '<path d="M4 5h16v12H8l-4 3z"/>', description: 'PETITと会話して、次の作業を進める。', links: [['新しい会話', 'chat'], ['設定', 'settings']] },
    { name: 'Univ', view: 'universe', icon: '<circle cx="12" cy="12" r="3"/><ellipse cx="12" cy="12" rx="10" ry="5" transform="rotate(-35 12 12)"/>', description: '3Dタスクと集中作業を確認する。', links: [['Focus', 'focus'], ['Tasks', 'tasks']] },
    { name: 'Develop', view: 'development', icon: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16"/>', description: 'CLIの開発タスクと実行状況を確認する。', links: [['開発を開く', 'development'], ['タスク一覧', 'tasks']] },
    { name: 'Dashboard', view: 'today', icon: '<path d="M4 20V11m5 9V5m5 15v-8m5 8V8"/>', description: '作業時間と最近の活動を振り返る。', links: [['活動を見る', 'today'], ['Remind', 'reminders']] },
  ];
  const dock = document.createElement('nav');
  dock.className = 'petit-rubber-dock';
  dock.setAttribute('aria-label', 'PETIT クイックナビゲーション');
  dock.innerHTML = '<section class="petit-rubber-dock__content" aria-live="polite"></section><div class="petit-rubber-dock__tabs" role="tablist" aria-label="主画面"><div class="petit-rubber-dock__indicator" aria-hidden="true"></div></div>';
  document.body.appendChild(dock);
  const content = dock.querySelector('.petit-rubber-dock__content');
  const tabs = dock.querySelector('.petit-rubber-dock__tabs');
  const indicator = dock.querySelector('.petit-rubber-dock__indicator');
  const buttons = definitions.map((d, i) => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'petit-rubber-dock__tab';
    button.setAttribute('role', 'tab'); button.setAttribute('aria-label', d.name);
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + d.icon + '</svg><span>' + d.name + '</span>';
    button.addEventListener('click', () => {
      if (ignoreClick) return;
      if (active === i) { setExpanded(!expanded); return; }
      setExpanded(false); select(i, true);
    });
    tabs.appendChild(button);
    return button;
  });
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const params = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim().split(/\s+/).map(Number);
  const spring = (x, spec) => ({ x, v: 0, target: x, k: spec[0], c: spec[1] });
  const l = spring(0, params('--dock-lead')), r = spring(56, params('--dock-trail'));
  const w = spring(248, params('--dock-open-w')), h = spring(68, params('--dock-open-h'));
  const center = i => 28 + i * 60;
  const tune = (s, spec) => { s.k = spec[0]; s.c = reduced.matches ? 2 * Math.sqrt(s.k) : spec[1]; };
  let active = 0, expanded = false, drag = null, ignoreClick = false, last = performance.now();
  function navigate(view) {
    const target = existing.querySelector('[data-view="' + view + '"]');
    if (target) target.click();
  }
  function paintPanel() {
    const d = definitions[active];
    content.replaceChildren();
    const heading = document.createElement('h2'); heading.className = 'petit-rubber-dock__heading'; heading.textContent = d.name;
    const description = document.createElement('p'); description.className = 'petit-rubber-dock__description'; description.textContent = d.description;
    const actions = document.createElement('div'); actions.className = 'petit-rubber-dock__actions';
    d.links.forEach(([label, view]) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'petit-rubber-dock__action'; button.textContent = label;
      button.addEventListener('click', () => { navigate(view); setExpanded(false); });
      actions.appendChild(button);
    });
    // All secondary destinations stay reachable on narrow screens.
    if (active === 0) {
      const more = document.createElement('button'); more.type = 'button'; more.className = 'petit-rubber-dock__action';
      more.textContent = 'その他の画面'; more.addEventListener('click', () => {
        paintSecondary(); setExpanded(true);
      });
      actions.appendChild(more);
    }
    content.append(heading, description, actions);
  }
  function paintSecondary() {
    content.replaceChildren();
    const heading = document.createElement('h2'); heading.className = 'petit-rubber-dock__heading'; heading.textContent = 'その他の画面';
    const actions = document.createElement('div'); actions.className = 'petit-rubber-dock__actions';
    [['Focus','focus'],['Tasks','tasks'],['Remind','reminders'],['Settings','settings']].forEach(([name, view]) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'petit-rubber-dock__action';
      button.textContent = name; button.addEventListener('click', () => { navigate(view); setExpanded(false); }); actions.appendChild(button);
    });
    content.append(heading, actions);
  }
  function select(i, route) {
    const direction = Math.sign(center(i) - (l.x + r.x) / 2);
    const lead = params('--dock-lead'), trail = params('--dock-trail');
    tune(l, direction > 0 ? trail : lead); tune(r, direction > 0 ? lead : trail);
    if (!direction) { tune(l, [600,44]); tune(r, [600,44]); }
    l.target = center(i) - 28; r.target = center(i) + 28;
    active = i;
    buttons.forEach((b, j) => { b.setAttribute('aria-selected', String(i === j)); b.tabIndex = i === j ? 0 : -1; });
    paintPanel();
    if (route) navigate(definitions[i].view);
  }
  function setExpanded(on) {
    if (expanded === on) return;
    expanded = on; dock.dataset.expanded = String(on);
    if (on) { paintPanel(); tune(w, params('--dock-open-w')); tune(h, params('--dock-open-h')); }
    else { tune(w, params('--dock-close')); tune(h, params('--dock-close')); }
    w.target = on ? Math.min(340, window.innerWidth - 24) : 248;
    h.target = on ? 265 : 68;
    content.setAttribute('aria-hidden', String(!on));
    if ('inert' in content) content.inert = !on;
  }
  let secondary = false;
  const originalPaint = paintPanel;
  // Keep secondary card open until the user changes tabs or closes it.
  function syncFromView() {
    const selected = Array.from(document.querySelectorAll('[data-view-panel]')).find(p => !p.hidden);
    const found = definitions.findIndex(d => d.view === selected?.dataset.viewPanel);
    if (found >= 0 && found !== active) select(found, false);
  }
  let startX = 0;
  tabs.addEventListener('pointerdown', e => { if (e.button !== 0) return; drag = { id:e.pointerId, x:e.clientX, moved:false, direction:0 }; startX = e.clientX; });
  tabs.addEventListener('pointermove', e => {
    if (!drag || drag.id !== e.pointerId) return;
    const movement = e.clientX - drag.x;
    if (!drag.moved && Math.abs(e.clientX - startX) > 5) { drag.moved = true; tabs.setPointerCapture(e.pointerId); tabs.classList.add('is-dragging'); }
    if (!drag.moved) return;
    drag.direction = Math.sign(movement); drag.x = e.clientX;
    const rect = tabs.getBoundingClientRect(), raw = e.clientX - rect.left, clamped = Math.max(28, Math.min(208, raw));
    const c = raw < 28 ? 28 - (1 - 1/(1+(28-raw)*.55/46))*46 : raw > 208 ? 208 + (1 - 1/(1+(raw-208)*.55/46))*46 : clamped;
    const lead = params('--dock-drag-lead'), trail = params('--dock-drag-trail');
    tune(l, drag.direction > 0 ? trail : lead); tune(r, drag.direction > 0 ? lead : trail);
    l.target = c - 28; r.target = c + 28;
  });
  function finish(e) {
    if (!drag || drag.id !== e.pointerId) return;
    if (drag.moved) {
      const index = Math.max(0, Math.min(3, Math.round(((l.target + r.target)/2 - 28)/60 + drag.direction*.18)));
      ignoreClick = true; queueMicrotask(() => { ignoreClick = false; });
      setExpanded(false); select(index, true); tabs.classList.remove('is-dragging');
    }
    drag = null;
  }
  tabs.addEventListener('pointerup', finish); tabs.addEventListener('pointercancel', finish);
  buttons.forEach((button, i) => button.addEventListener('keydown', e => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault(); const next = (i + (e.key === 'ArrowRight' ? 1 : 3)) % 4; setExpanded(false); select(next, true); buttons[next].focus();
    }
  }));
  document.addEventListener('pointerdown', e => { if (expanded && !dock.contains(e.target)) setExpanded(false); });
  document.addEventListener('keydown', e => { if (expanded && e.key === 'Escape') setExpanded(false); });
  window.addEventListener('resize', () => { if (expanded) w.target = Math.min(340, window.innerWidth - 24); });
  const observer = new MutationObserver(syncFromView);
  document.querySelectorAll('[data-view-panel]').forEach(el => observer.observe(el, { attributes: true, attributeFilter: ['hidden'] }));
  function frame(now) {
    const dt = Math.min((now - last) / 1000, 1/30); last = now;
    for (let sub = 0; sub < 4; sub++) for (const s of [l,r,w,h]) {
      if (reduced.matches) { s.x = s.target; s.v = 0; continue; }
      const a = -s.k * (s.x - s.target) - s.c * s.v; s.v += a * dt / 4; s.x += s.v * dt / 4;
    }
    dock.style.width = w.x + 'px'; dock.style.height = h.x + 'px';
    dock.style.borderRadius = Math.min(h.x/2, expanded ? 26 : 34) + 'px';
    let left = Math.min(l.x, r.x), width = Math.max(24, Math.abs(r.x - l.x));
    const height = 56 * Math.max(.66, Math.min(1.1, 1 / Math.sqrt(width/56)));
    indicator.style.width = width + 'px'; indicator.style.height = height + 'px';
    indicator.style.borderRadius = height/2 + 'px';
    indicator.style.transform = 'translate(' + left + 'px,' + ((56-height)/2) + 'px)';
    requestAnimationFrame(frame);
  }
  content.setAttribute('aria-hidden', 'true');
  if ('inert' in content) content.inert = true;
  syncFromView(); select(active, false);
  document.body.classList.add('petit-has-rubber-dock');
  requestAnimationFrame(frame);
})();
