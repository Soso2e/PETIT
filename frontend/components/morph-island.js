/* PETIT shared Morph Island — rebuilt from DesignBookmark's Morph Island.
 * Uses the exact spring constants from DesignBookmark tokens.css:
 *   width:  stiffness 380, damping 24 (--island-w)
 *   height: stiffness 300, damping 22 (--island-h, 1.3x stiffness when shrinking)
 *   press:  stiffness 520, damping 18
 *   radius: min(height / 2, 32)
 *   volume: width * (1 + clamp(-H.v / 7000, -0.05, 0.05))
 */
(() => {
  'use strict';
  if (window.PetitMorphIsland) return;

  const DEFAULT_SPRING = Object.freeze({
    width: Object.freeze({ stiffness: 380, damping: 24 }),
    height: Object.freeze({ stiffness: 300, damping: 22 }),
    press: Object.freeze({ stiffness: 520, damping: 18 }),
    maxRadius: 32,
  });

  const DEFAULT_VIEWS = Object.freeze({
    idle: { width: 128, height: 36, radius: 18, label: 'PETIT', detail: '', trailing: '', icon: 'dot' },
    session: { width: 256, height: 38, radius: 19, label: '作業セッション中', detail: '', trailing: '00:00', icon: 'timer' },
    develop: { width: 292, height: 54, radius: 27, label: '開発ジョブ実行中', detail: '進行状況を確認', trailing: '', icon: 'code' },
    notification: { width: 304, height: 56, radius: 28, label: '通知が届いています', detail: 'タップして確認', trailing: '', icon: 'bell' },
    listening: { width: 228, height: 38, radius: 19, label: '聞いています…', detail: '', trailing: '', icon: 'mic' },
    working: { width: 248, height: 40, radius: 20, label: '考えています…', detail: '', trailing: '', icon: 'dot' },
    success: { width: 244, height: 40, radius: 20, label: '完了しました', detail: '', trailing: '', icon: 'check' },
    error: { width: 264, height: 44, radius: 22, label: '確認が必要です', detail: '', trailing: '', icon: 'alert' },
  });

  const ICONS = Object.freeze({
    dot: '<span class="petit-morph-island__dot"></span>',
    timer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="7.5"/><path d="M12 9.5V13l2.2 1.6M9.5 3h5"/></svg>',
    code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/></svg>',
    bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 10.3a5.5 5.5 0 0 1 11 0v3.2l1.8 2.7H4.7l1.8-2.7v-3.2Z"/><path d="M9.5 19h5"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.2 4.2L19 7"/></svg>',
    alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.2h.01"/></svg>',
  });

  const finitePositive = (n, fallback) => Number.isFinite(n) && n > 0 ? n : fallback;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  const cleanView = (value, fallback) => ({
    width: finitePositive(value?.width, fallback.width),
    height: finitePositive(value?.height, fallback.height),
    radius: finitePositive(value?.radius, fallback.radius),
    label: String(value?.label ?? fallback.label),
    detail: String(value?.detail ?? fallback.detail),
    trailing: String(value?.trailing ?? fallback.trailing ?? ''),
    badge: String(value?.badge ?? ''),
    icon: String(value?.icon ?? fallback.icon ?? 'dot'),
  });

  function readTokenSpring(name, fallback) {
    try {
      if (typeof getComputedStyle !== 'function' || !document.documentElement) return fallback;
      const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      if (!raw) return fallback;
      const parts = raw.split(/\s+/).map(Number);
      if (parts.length >= 2 && Number.isFinite(parts[0]) && Number.isFinite(parts[1])) {
        return { stiffness: parts[0], damping: parts[1] };
      }
    } catch { /* fallback */ }
    return fallback;
  }

  function createLayer() {
    const layer = document.createElement('div');
    layer.className = 'petit-morph-island__layer';

    const marker = document.createElement('span');
    marker.className = 'petit-morph-island__marker';
    marker.setAttribute('aria-hidden', 'true');

    const text = document.createElement('span');
    text.className = 'petit-morph-island__text';

    const label = document.createElement('span');
    label.className = 'petit-morph-island__label';

    const detail = document.createElement('span');
    detail.className = 'petit-morph-island__detail';

    text.append(label, detail);

    const trailing = document.createElement('span');
    trailing.className = 'petit-morph-island__trailing';

    layer.append(marker, text, trailing);
    return { layer, marker, label, detail, trailing };
  }

  function paintLayer(slot, view) {
    slot.marker.innerHTML = ICONS[view.icon] || ICONS.dot;
    slot.label.textContent = view.label;
    slot.detail.textContent = view.detail;
    slot.detail.hidden = !view.detail;
    if (view.badge) {
      slot.trailing.textContent = '';
      const pill = document.createElement('span');
      pill.className = 'petit-morph-island__badge';
      pill.textContent = view.badge;
      slot.trailing.appendChild(pill);
      slot.trailing.hidden = false;
    } else if (view.trailing) {
      slot.trailing.textContent = view.trailing;
      slot.trailing.hidden = false;
    } else {
      slot.trailing.textContent = '';
      slot.trailing.hidden = true;
    }
  }

  function mount(container, options = {}) {
    if (!(container instanceof Element)) throw new TypeError('Morph Island requires a container Element');
    const views = { ...DEFAULT_VIEWS, ...(options.views || {}) };

    const tokenW = readTokenSpring('--island-w', DEFAULT_SPRING.width);
    const tokenH = readTokenSpring('--island-h', DEFAULT_SPRING.height);
    const wSpring = {
      stiffness: finitePositive(options.spring?.width?.stiffness ?? options.spring?.stiffness, tokenW.stiffness),
      damping: finitePositive(options.spring?.width?.damping ?? options.spring?.damping, tokenW.damping),
    };
    const hSpring = {
      stiffness: finitePositive(options.spring?.height?.stiffness ?? options.spring?.stiffness, tokenH.stiffness),
      damping: finitePositive(options.spring?.height?.damping ?? options.spring?.damping, tokenH.damping),
    };
    const pSpring = {
      stiffness: finitePositive(options.spring?.press?.stiffness, DEFAULT_SPRING.press.stiffness),
      damping: finitePositive(options.spring?.press?.damping, DEFAULT_SPRING.press.damping),
    };
    const maxRadius = finitePositive(options.maxRadius, DEFAULT_SPRING.maxRadius);

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const root = document.createElement('div');
    root.className = 'petit-morph-island';
    root.setAttribute('role', 'status');
    root.setAttribute('aria-live', 'polite');
    if (typeof options.onClick === 'function') {
      root.setAttribute('tabindex', '0');
    }

    const content = document.createElement('div');
    content.className = 'petit-morph-island__content';
    const slots = [createLayer(), createLayer()];
    let activeSlot = 0;
    slots[0].layer.classList?.add('is-on');
    content.append(slots[0].layer, slots[1].layer);
    root.appendChild(content);
    container.appendChild(root);

    let state = Object.hasOwn(views, options.initialState) ? options.initialState : 'idle';
    let raf = 0;
    let previousTime = 0;
    let disposed = false;

    const first = cleanView(views[state], DEFAULT_VIEWS.idle);
    const W = { x: first.width, v: 0, t: first.width, k: wSpring.stiffness, c: wSpring.damping };
    const H = { x: first.height, v: 0, t: first.height, k: hSpring.stiffness, c: hSpring.damping };
    const P = { x: 1, v: 0, t: 1, k: pSpring.stiffness, c: pSpring.damping };

    const tune = (s, k, c) => {
      s.k = k;
      s.c = reduced.matches ? 2 * Math.sqrt(k) : c;
    };
    const stepSpring = (s, dt) => {
      const a = -s.k * (s.x - s.t) - s.c * s.v;
      s.v += a * dt;
      s.x += s.v * dt;
    };

    function paint() {
      const h = Math.max(H.x, 20);
      const give = clamp(-H.v / 7000, -0.05, 0.05);
      root.style.width = (W.x * (1 + give)) + 'px';
      root.style.height = h + 'px';
      root.style.borderRadius = Math.min(h / 2, maxRadius) + 'px';
      root.style.transform = `scale(${P.x})`;
    }

    function stopAnimation() {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      previousTime = 0;
    }

    function frame(now) {
      if (disposed) return;
      const dt = previousTime ? Math.min((now - previousTime) / 1000, 1 / 30) : 1 / 60;
      previousTime = now;

      const sub = 4;
      for (let i = 0; i < sub; i++) {
        stepSpring(W, dt / sub);
        stepSpring(H, dt / sub);
        stepSpring(P, dt / sub);
      }

      const moving =
        Math.abs(W.x - W.t) > 0.08 || Math.abs(W.v) > 0.08 ||
        Math.abs(H.x - H.t) > 0.08 || Math.abs(H.v) > 0.08 ||
        Math.abs(P.x - P.t) > 0.002 || Math.abs(P.v) > 0.002;

      if (!moving) {
        W.x = W.t; W.v = 0;
        H.x = H.t; H.v = 0;
        P.x = P.t; P.v = 0;
      }
      paint();
      raf = moving ? requestAnimationFrame(frame) : 0;
      if (!moving) previousTime = 0;
    }

    function scheduleFrame() {
      if (reduced.matches) {
        stopAnimation();
        W.x = W.t; W.v = 0;
        H.x = H.t; H.v = 0;
        P.x = P.t; P.v = 0;
        paint();
      } else if (!raf) {
        previousTime = 0;
        raf = requestAnimationFrame(frame);
      }
    }

    function applyState(nextState, overrides = {}) {
      if (disposed) return false;
      if (!Object.hasOwn(views, nextState)) return false;
      const isSameState = nextState === state && root.dataset.state === nextState;
      const next = cleanView({ ...views[nextState], ...overrides }, DEFAULT_VIEWS.idle);
      const grow = next.width * next.height > W.t * H.t;

      state = nextState;
      root.dataset.state = nextState;

      if (isSameState) {
        paintLayer(slots[activeSlot], next);
        if (Math.abs(W.t - next.width) > 0.5 || Math.abs(H.t - next.height) > 0.5) {
          tune(W, wSpring.stiffness, wSpring.damping);
          tune(H, hSpring.stiffness * (grow ? 1 : 1.3), hSpring.damping);
          W.t = next.width;
          H.t = next.height;
          scheduleFrame();
        }
        return true;
      }

      const prevSlot = activeSlot;
      activeSlot = 1 - activeSlot;
      paintLayer(slots[activeSlot], next);
      slots[prevSlot].layer.classList?.remove('is-on');
      slots[activeSlot].layer.classList?.add('is-on');

      tune(W, wSpring.stiffness, wSpring.damping);
      tune(H, hSpring.stiffness * (grow ? 1 : 1.3), hSpring.damping);
      tune(P, pSpring.stiffness, pSpring.damping);
      W.t = next.width;
      H.t = next.height;
      P.v -= grow ? 1.6 : 1.0;

      scheduleFrame();
      return true;
    }

    const onPointerDown = () => {
      if (disposed || reduced.matches) return;
      tune(P, pSpring.stiffness, pSpring.damping);
      P.t = 0.96;
      scheduleFrame();
    };
    const onPointerUp = () => {
      if (disposed || reduced.matches) return;
      tune(P, pSpring.stiffness, pSpring.damping);
      P.t = 1;
      scheduleFrame();
    };
    const onClick = (event) => {
      if (typeof options.onClick === 'function') options.onClick(state, event);
    };
    const onKeyDown = (event) => {
      if ((event.key === 'Enter' || event.key === ' ') && typeof options.onClick === 'function') {
        event.preventDefault();
        options.onClick(state, event);
      }
    };

    root.addEventListener?.('pointerdown', onPointerDown);
    window.addEventListener?.('pointerup', onPointerUp);
    root.addEventListener?.('click', onClick);
    root.addEventListener?.('keydown', onKeyDown);

    // Turning reduced motion on mid-morph must land on the target right away.
    function onMotionChange() { if (reduced.matches) scheduleFrame(); }
    reduced.addEventListener?.('change', onMotionChange);

    paintLayer(slots[activeSlot], first);
    root.dataset.state = state;
    paint();

    return {
      element: root,
      getState: () => state,
      setState: applyState,
      destroy() {
        if (disposed) return;
        disposed = true;
        stopAnimation();
        reduced.removeEventListener?.('change', onMotionChange);
        root.removeEventListener?.('pointerdown', onPointerDown);
        window.removeEventListener?.('pointerup', onPointerUp);
        root.removeEventListener?.('click', onClick);
        root.removeEventListener?.('keydown', onKeyDown);
        root.remove();
      },
    };
  }

  window.PetitMorphIsland = Object.freeze({ mount, DEFAULT_VIEWS, DEFAULT_SPRING });
})();
