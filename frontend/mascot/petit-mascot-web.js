/*
 * プティちゃん Web版: ブラウザ内を歩き回るマスコット＋設定カード。
 *
 * - 共通描画は petit-mascot.js。ここは「どこを歩くか」「いつ何をするか」だけを持つ。
 * - 操作を妨げない: レイヤー全体は pointer-events:none。マスコット本体(小さな領域)だけが反応し、
 *   ボタンや入力欄の上には立ち止まらない。チャット欄があればその上を床にする。
 * - 負荷: rAF は歩行・落下の間だけ。待機中は setTimeout とCSSアニメのみ。タブ非表示で停止。
 * - 状態: document の 'petit:mascot' イベント（PetitMascot.signal）で表情と動作を切り替える。
 */
(() => {
  'use strict';
  const M = window.PetitMascot;
  if (!M || window.PetitMascotWeb) return;

  const KEY = 'petit_mascot_web_v1';
  const SLEEP_AFTER_MS = 3 * 60 * 1000;
  const FOOT = 0.9; // SVG高さに対する足元の位置
  const INTERACTIVE = 'a,button,input,textarea,select,label,summary,iframe,canvas,[role="button"],[role="link"],[role="tab"],[contenteditable=""],[contenteditable="true"]';
  const isChatInput = (el) => el?.id === 'input' || el?.id === 'chat-input';
  const mobile = () => window.matchMedia('(max-width: 760px)').matches;

  // ------------------------------------------------------------ preferences
  const defaults = () => ({
    enabled: !mobile() && !window.petitWorkspace, roam: true, size: mobile() ? 56 : 72,
    preset: 'pear', body: '', ring: '', motion: 'auto',
  });
  function normalize(raw) {
    const d = defaults();
    const size = Math.round(Number(raw.size));
    return {
      enabled: typeof raw.enabled === 'boolean' ? raw.enabled : d.enabled,
      roam: raw.roam !== false,
      size: Number.isFinite(size) ? Math.min(160, Math.max(40, size)) : d.size,
      preset: Object.hasOwn(M.PRESETS, raw.preset) ? raw.preset : 'pear',
      body: M.isHex(raw.body) ? raw.body : '',
      ring: M.isHex(raw.ring) ? raw.ring : '',
      motion: M.MOTION_MODES.includes(raw.motion) ? raw.motion : 'auto',
    };
  }
  function load() {
    try { return normalize({ ...defaults(), ...JSON.parse(localStorage.getItem(KEY) || '{}') }); }
    catch { return defaults(); }
  }
  let prefs = load();
  function setPrefs(next) {
    prefs = normalize({ ...prefs, ...next });
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* 表示設定のみ */ }
    applyPrefs();
    syncSettingsCard();
    window.dispatchEvent(new CustomEvent('petit:mascot-prefs', { detail: { ...prefs } }));
  }
  const colorOptions = () => ({ preset: prefs.preset, body: prefs.body || undefined, ring: prefs.ring || undefined });

  // ------------------------------------------------------------ walker state
  let layer = null, holder = null, bubble = null, mascot = null;
  const st = {
    x: 0, y: 0, targetX: null, facing: 1, mode: 'idle', run: false, vy: 0,
    petit: 'idle', lastInput: Date.now(), clicks: [], raf: 0, last: 0, timer: 0, bubbleTimer: 0,
    pointer: null, lookQueued: false, drag: null, relayoutTimer: 0, stopLife: null,
  };
  const size = () => prefs.size;
  const canMove = () => mascot && mascot.motionAllowed();

  function floor() {
    const s = size();
    const form = document.getElementById('chat-form');
    if (form && form.getClientRects().length) {
      const r = form.getBoundingClientRect();
      const controls = form.previousElementSibling?.classList?.contains('petit-thread-controls')
        ? form.previousElementSibling.getBoundingClientRect() : null;
      const top = controls && controls.height ? Math.min(r.top, controls.top) : r.top;
      if (r.width > s * 2.5 && top > s * 1.6 && top < window.innerHeight)
        return { y: top - 2, min: r.left + 4, max: r.right - s - 4 };
    }
    const nav = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--petit-bottom-nav-height')) || 0;
    return { y: window.innerHeight - Math.max(6, mobile() ? nav : 0), min: 8, max: Math.max(8, window.innerWidth - s - 8) };
  }
  const topFor = (f) => f.y - size() * FOOT;
  const clampX = (x, f = floor()) => Math.min(f.max, Math.max(f.min, x));

  function place() {
    holder.style.transform = `translate3d(${Math.round(st.x)}px, ${Math.round(st.y)}px, 0)`;
  }

  // ボタン・入力欄・リンク・3D表示などの上には立たない。
  function spotFree(x, y) {
    const s = size();
    for (const [fx, fy] of [[0.5, 0.4], [0.28, 0.72], [0.72, 0.72], [0.5, 0.86]]) {
      const px = x + s * fx, py = y + s * fy;
      if (px < 0 || py < 0 || px > window.innerWidth || py > window.innerHeight) continue;
      const hit = document.elementsFromPoint(px, py).find((node) => !layer.contains(node));
      if (hit && hit.closest(INTERACTIVE)) return false;
    }
    return true;
  }
  function pickTarget() {
    const f = floor(), y = topFor(f);
    if (f.max - f.min < size()) return null;
    for (let i = 0; i < 8; i++) {
      const x = f.min + Math.random() * (f.max - f.min);
      if (Math.abs(x - st.x) < size() * 0.8) continue;
      if (spotFree(x, y)) return x;
    }
    return null;
  }

  // ------------------------------------------------------------ motion (rAF only while moving)
  function startLoop() {
    if (st.raf) return;
    st.last = performance.now();
    st.raf = requestAnimationFrame(tick);
  }
  function stopLoop() { cancelAnimationFrame(st.raf); st.raf = 0; }
  function tick(now) {
    st.raf = 0;
    const dt = Math.min(0.1, (now - st.last) / 1000);
    st.last = now;
    if (st.mode === 'walking') {
      const speed = size() * (st.run ? 2.3 : 1.05);
      const dx = st.targetX - st.x;
      const step = Math.sign(dx) * Math.min(Math.abs(dx), speed * dt);
      st.x += step;
      st.y = topFor(floor());
      place();
      if (Math.abs(st.targetX - st.x) < 0.5) { arrive(); return; }
    } else if (st.mode === 'falling') {
      const f = floor(), ground = topFor(f);
      st.vy = Math.min(2400, st.vy + 2600 * dt);
      st.y += st.vy * dt;
      if (st.y >= ground) { st.y = ground; place(); land(); return; }
      place();
    } else return;
    st.raf = requestAnimationFrame(tick);
  }
  function walkTo(x, { run = false } = {}) {
    const f = floor();
    st.targetX = clampX(x, f);
    if (Math.abs(st.targetX - st.x) < 2) return false;
    st.mode = 'walking'; st.run = run;
    st.facing = st.targetX > st.x ? 1 : -1;
    mascot.setFacing(st.facing);
    mascot.setEmotion(run ? 'happy' : 'neutral');
    mascot.setAction(run ? 'run' : 'walk');
    mascot.look(0.6, 0.1);
    startLoop();
    return true;
  }
  function arrive() {
    st.mode = 'idle'; st.targetX = null; stopLoop();
    mascot.look(null);
    mascot.setState(st.petit);
    schedule();
  }
  function stopWalking() {
    if (st.mode !== 'walking') return;
    st.mode = 'idle'; stopLoop(); mascot.look(null);
  }
  function fall() {
    st.mode = 'falling'; st.vy = 0;
    startLoop();
  }
  function land() {
    st.mode = 'idle'; stopLoop();
    mascot.setState(st.petit);
    mascot.react('joy', 'land', 700);
    const f = floor();
    if (st.x < f.min || st.x > f.max || !spotFree(st.x, st.y)) {
      setTimeout(() => { if (st.mode === 'idle') walkTo(pickTarget() ?? clampX(st.x, f)); }, 750);
    } else schedule();
  }

  // ------------------------------------------------------------ behaviour
  const idleish = () => st.petit === 'idle';
  function schedule(ms = 3500 + Math.random() * 8000) {
    clearTimeout(st.timer);
    st.timer = setTimeout(behave, ms);
  }
  function behave() {
    if (!mascot || document.hidden) return;
    if (st.mode !== 'idle' || !idleish()) { schedule(); return; }
    if (Date.now() - st.lastInput > SLEEP_AFTER_MS) { setPetit('sleep'); return; }
    if (canMove() && Math.random() < 0.55) {
      if (prefs.roam) {
        const x = pickTarget();
        if (x != null && walkTo(x, { run: Math.random() < 0.12 })) return;
      }
      const b = M.pickWeighted(M.IDLE_LIFE);
      mascot.react(b.emotion, b.action, b.ms);
    }
    schedule();
  }
  function relayout() {
    if (!mascot || st.mode !== 'idle') return;
    const f = floor(), ground = topFor(f);
    const x = clampX(st.x, f);
    if (ground > st.y + 4 && canMove()) { st.x = x; fall(); return; }
    if (Math.abs(ground - st.y) > 0.5 || x !== st.x) { st.x = x; st.y = ground; place(); }
  }

  function say(text, ms = 2400) {
    if (!bubble || !text) return;
    bubble.textContent = text;
    bubble.classList.add('pmw-show');
    clearTimeout(st.bubbleTimer);
    st.bubbleTimer = setTimeout(() => bubble.classList.remove('pmw-show'), ms);
  }

  function setPetit(name) {
    const def = M.STATES[name];
    if (!def || !mascot) return;
    if (def.transient) {
      // 成功・エラーは一時的。基準は待機へ戻す。
      st.petit = 'idle';
      mascot.setState('idle');
      if (st.mode === 'walking') stopWalking();
      mascot.setState(name);
      if (def.caption) say(def.caption);
      schedule(def.transient + 1500);
      return;
    }
    const was = st.petit;
    st.petit = name;
    if (name !== 'idle') stopWalking();
    mascot.setState(name);
    if (def.caption && was !== name) say(def.caption);
    if (name === 'idle') schedule();
  }

  function wake() {
    st.lastInput = Date.now();
    if (st.petit !== 'sleep') return;
    setPetit('idle');
    mascot.react('surprised', 'surprise', 900);
  }

  // ------------------------------------------------------------ input
  const REACTIONS = [
    { emotion: 'joy', action: 'jump', text: 'えへへ' },
    { emotion: 'love', action: 'hop' },
    { emotion: 'surprised', action: 'surprise', text: 'わっ' },
    { emotion: 'proud', action: 'dance', ms: 1600 },
    { emotion: 'happy', action: 'turn', text: 'なあに？' },
  ];
  function onClick() {
    if (st.petit === 'sleep') { wake(); return; }
    const now = Date.now();
    st.clicks = st.clicks.filter((t) => now - t < 2500).concat(now);
    if (st.clicks.length >= 5) {
      st.clicks = [];
      mascot.react('angry', 'shake', 1500); say('もう！');
      return;
    }
    const r = REACTIONS[Math.floor(Math.random() * REACTIONS.length)];
    stopWalking();
    mascot.react(r.emotion, r.action, r.ms);
    if (r.text && Math.random() < 0.6) say(r.text, 1600);
    schedule();
  }
  function onPointerDown(event) {
    if (event.button !== 0) return;
    holder.setPointerCapture(event.pointerId);
    st.drag = { id: event.pointerId, sx: event.clientX, sy: event.clientY, active: false };
  }
  function onPointerMove(event) {
    const d = st.drag;
    if (!d || d.id !== event.pointerId) return;
    if (!d.active && Math.hypot(event.clientX - d.sx, event.clientY - d.sy) < 6) return;
    if (!d.active) {
      d.active = true;
      stopWalking(); stopLoop(); clearTimeout(st.timer);
      st.mode = 'dragging';
      mascot.clearReaction();
      mascot.setEmotion('surprised'); mascot.setAction('dangle');
      holder.classList.add('pmw-dragging');
    }
    st.x = event.clientX - size() / 2;
    st.y = event.clientY - size() * 0.18;
    place();
  }
  function onPointerUp(event) {
    const d = st.drag;
    if (!d || d.id !== event.pointerId) return;
    st.drag = null;
    holder.classList.remove('pmw-dragging');
    st.lastInput = Date.now();
    if (!d.active) { onClick(); return; }
    st.x = clampX(st.x, { min: 0, max: window.innerWidth - size() });
    if (canMove()) fall();
    else { st.y = topFor(floor()); place(); land(); }
  }
  function onPointerEnter() {
    if (st.mode === 'idle' && idleish() && !st.drag) mascot.react('happy', 'wiggle', 900);
  }

  // 視線はカーソルを追う（rAFで間引き）。
  function updateLook() {
    st.lookQueued = false;
    if (!mascot || st.mode !== 'idle' || !st.pointer || !idleish()) return;
    const s = size();
    const cx = st.x + s / 2, cy = st.y + s * 0.55;
    const dx = st.pointer.x - cx, dy = st.pointer.y - cy;
    if (Math.hypot(dx, dy) > 420) { mascot.look(null); return; }
    mascot.look((dx / 160) * st.facing, dy / 160);
  }
  function onGlobalPointerMove(event) {
    st.pointer = { x: event.clientX, y: event.clientY };
    st.lastInput = Date.now();
    if (!st.lookQueued) { st.lookQueued = true; requestAnimationFrame(updateLook); }
  }
  function onGlobalInput() { if (st.petit === 'sleep') wake(); else st.lastInput = Date.now(); }
  function onFocusIn(event) {
    if (isChatInput(event.target) && (st.petit === 'idle' || st.petit === 'sleep')) { wake(); setPetit('typing'); }
  }
  function onFocusOut(event) {
    if (isChatInput(event.target) && st.petit === 'typing') setPetit('idle');
  }
  function onSignal(event) {
    const name = event.detail?.state;
    if (typeof name !== 'string' || !M.STATES[name]) return;
    st.lastInput = Date.now();
    // 入力中に「待機」が来ても、まだ入力欄にいるなら入力中を保つ。
    if (name === 'idle' && isChatInput(document.activeElement)) { setPetit('typing'); return; }
    setPetit(name);
  }
  function onVisibility() {
    if (!mascot) return;
    mascot.pause(document.hidden);
    if (document.hidden) { stopLoop(); clearTimeout(st.timer); }
    else { if (st.mode === 'walking' || st.mode === 'falling') startLoop(); else schedule(); }
  }
  const applyLite = () => mascot?.setLite(document.documentElement.dataset.petitPerformance === 'lite');

  const listeners = [];
  function on(target, type, fn, opts) { target.addEventListener(type, fn, opts); listeners.push(() => target.removeEventListener(type, fn, opts)); }

  // ------------------------------------------------------------ mount
  function mount() {
    if (layer || !document.body) return;
    layer = document.createElement('div');
    layer.className = 'pmw-layer';
    layer.setAttribute('aria-hidden', 'true');
    holder = document.createElement('div');
    holder.className = 'pmw-holder';
    holder.title = 'プティちゃん（クリックで反応・ドラッグで移動）';
    bubble = document.createElement('div');
    bubble.className = 'pmw-bubble';
    holder.append(bubble);
    layer.append(holder);
    document.body.append(layer);
    mascot = M.create(holder, { size: size(), colors: colorOptions(), motion: prefs.motion });
    holder.style.setProperty('--pmw-size', `${size()}px`);
    applyLite();
    const f = floor();
    st.x = f.max - size() * 0.3; st.y = topFor(f); st.facing = -1;
    if (!(st.x >= f.min)) st.x = f.min;
    mascot.setFacing(-1);
    place();
    on(holder, 'pointerdown', onPointerDown);
    on(holder, 'pointermove', onPointerMove);
    on(holder, 'pointerup', onPointerUp);
    on(holder, 'pointercancel', onPointerUp);
    on(holder, 'pointerenter', onPointerEnter);
    on(window, 'pointermove', onGlobalPointerMove, { passive: true });
    on(window, 'keydown', onGlobalInput, { passive: true, capture: true });
    on(window, 'pointerdown', onGlobalInput, { passive: true, capture: true });
    on(window, 'wheel', onGlobalInput, { passive: true });
    on(window, 'resize', relayout, { passive: true });
    on(window, 'petit:performance-change', applyLite);
    on(document, 'focusin', onFocusIn);
    on(document, 'focusout', onFocusOut);
    on(document, 'petit:mascot', onSignal);
    on(document, 'visibilitychange', onVisibility);
    // 画面切替・入力欄の伸縮などに追従（待機中だけ、1秒に1回の軽い計測）。
    st.relayoutTimer = setInterval(() => { if (!document.hidden) relayout(); }, 1000);
    // 入場: 画面端からひょっこり歩いてくる。
    if (canMove() && prefs.roam) {
      st.x = f.max + size(); place();
      setTimeout(() => walkTo(f.max - size() * 0.6), 600);
    } else schedule();
  }
  function unmount() {
    while (listeners.length) listeners.pop()();
    stopLoop(); clearTimeout(st.timer); clearTimeout(st.bubbleTimer); clearInterval(st.relayoutTimer);
    mascot?.destroy(); layer?.remove();
    layer = holder = bubble = mascot = null;
    st.mode = 'idle'; st.petit = 'idle';
  }
  function applyPrefs() {
    if (!prefs.enabled) { unmount(); return; }
    if (!layer) { mount(); return; }
    mascot.setColors(colorOptions());
    mascot.setSize(size());
    mascot.setMotion(prefs.motion);
    holder.style.setProperty('--pmw-size', `${size()}px`);
    if (!prefs.roam || !canMove()) stopWalking();
    relayout();
  }

  // ------------------------------------------------------------ settings card
  let card = null;
  function segmented(label, key, values) {
    const wrap = document.createElement('div');
    wrap.className = 'petit-preference-group';
    const title = document.createElement('span'); title.textContent = label;
    const group = document.createElement('div');
    group.className = 'petit-segmented-control';
    group.setAttribute('role', 'group'); group.setAttribute('aria-label', label);
    for (const [value, text] of values) {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = text;
      b.dataset.pmwPref = key; b.dataset.pmwValue = JSON.stringify(value);
      b.addEventListener('click', () => setPrefs({ [key]: value }));
      group.append(b);
    }
    wrap.append(title, group);
    return wrap;
  }
  function installSettingsCard() {
    const grid = document.querySelector('[data-view-panel="settings"] .settings-grid');
    if (!grid || grid.querySelector('[data-petit-mascot-card]')) return;
    card = document.createElement('section');
    card.className = 'settings-card petit-preference-card pmw-card';
    card.dataset.petitMascotCard = 'true';
    const head = document.createElement('div');
    head.className = 'settings-card__head';
    const h = document.createElement('h3'); h.textContent = 'プティちゃん';
    const p = document.createElement('p'); p.textContent = '画面を歩き回るマスコットの表示・大きさ・色を変えます。この端末のブラウザにだけ保存します。';
    const headText = document.createElement('div'); headText.append(h, p); head.append(headText);
    const preview = document.createElement('div'); preview.className = 'pmw-card-preview';
    const groups = document.createElement('div'); groups.className = 'petit-preference-groups';
    groups.append(
      segmented('表示', 'enabled', [[false, 'OFF'], [true, 'ON']]),
      segmented('歩き回る', 'roam', [[false, 'OFF'], [true, 'ON']]),
      segmented('動き', 'motion', [['auto', 'OSに従う'], ['full', '常に動かす'], ['reduced', '止める']]),
    );
    const sizeRow = document.createElement('label');
    sizeRow.className = 'pmw-row';
    sizeRow.innerHTML = '<span>大きさ</span><input type="range" min="40" max="160" step="4" data-pmw-size><output data-pmw-size-out></output>';
    sizeRow.querySelector('input').addEventListener('input', (e) => setPrefs({ size: Number(e.target.value) }));
    const swatches = document.createElement('div');
    swatches.className = 'pmw-swatches';
    swatches.setAttribute('role', 'group'); swatches.setAttribute('aria-label', 'カラー');
    for (const [key, preset] of Object.entries(M.PRESETS)) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'pmw-swatch'; b.title = preset.label; b.setAttribute('aria-label', preset.label);
      b.dataset.pmwPreset = key;
      b.style.setProperty('--sw-body', preset.body); b.style.setProperty('--sw-ring', preset.ring);
      b.addEventListener('click', () => setPrefs({ preset: key, body: '', ring: '' }));
      swatches.append(b);
    }
    const colorRow = document.createElement('div');
    colorRow.className = 'pmw-row';
    colorRow.innerHTML = '<span>カラー</span><label>本体 <input type="color" data-pmw-color="body"></label><label>輪 <input type="color" data-pmw-color="ring"></label>';
    colorRow.querySelectorAll('input').forEach((input) => input.addEventListener('input', () => setPrefs({ [input.dataset.pmwColor]: input.value })));
    const links = document.createElement('p');
    links.className = 'petit-preference-note';
    links.innerHTML = '表情と動きの一覧は <a href="/static/mascot/gallery.html" target="_blank" rel="noopener">プティちゃんギャラリー</a> で確認できます。クリックで反応、ドラッグで持ち上げられます。';
    card.append(head, preview, groups, sizeRow, swatches, colorRow, links);
    grid.prepend(card);
    const pm = M.create(preview, { size: 64 });
    card.pmwPreview = pm;
    M.startIdleLife(pm, { canAct: () => card?.isConnected && !document.hidden, minMs: 2500, maxMs: 6000 });
    syncSettingsCard();
  }
  function syncSettingsCard() {
    if (!card?.isConnected) return;
    card.querySelectorAll('[data-pmw-pref]').forEach((b) => {
      b.setAttribute('aria-pressed', String(JSON.stringify(prefs[b.dataset.pmwPref]) === b.dataset.pmwValue));
    });
    const range = card.querySelector('[data-pmw-size]');
    range.value = String(prefs.size);
    card.querySelector('[data-pmw-size-out]').textContent = `${prefs.size}px`;
    const colors = M.resolveColors(colorOptions());
    card.querySelector('[data-pmw-color="body"]').value = colors.body;
    card.querySelector('[data-pmw-color="ring"]').value = colors.ring;
    card.querySelectorAll('[data-pmw-preset]').forEach((b) => b.setAttribute('aria-pressed', String(!prefs.body && !prefs.ring && b.dataset.pmwPreset === prefs.preset)));
    card.pmwPreview?.setColors(colorOptions());
    card.pmwPreview?.setMotion(prefs.motion);
  }

  function boot() {
    applyPrefs();
    installSettingsCard();
    document.addEventListener('click', (event) => {
      const tab = event.target instanceof Element ? event.target.closest('[data-view="settings"]') : null;
      if (tab) queueMicrotask(installSettingsCard);
    }, true);
  }

  window.PetitMascotWeb = Object.freeze({
    prefs: () => ({ ...prefs }),
    setPrefs,
    mascot: () => mascot,
    say,
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
