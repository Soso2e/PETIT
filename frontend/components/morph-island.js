/* PETIT shared Morph Island. Framework-free, opt-in, no page placement.
 * Motion is ported from DesignBookmark Motion Studies (morph-island/island.js,
 * shared/tokens.css `--island-*`, shared/motion.js). See docs/ui/morph-island.md.
 */
(() => {
  'use strict';
  if (window.PetitMorphIsland) return;

  // tokens.css: --island-w:380 24; --island-h:300 22; --island-radius:32
  const DEFAULT_SPRINGS = Object.freeze({
    width: Object.freeze({ stiffness: 380, damping: 24 }),
    height: Object.freeze({ stiffness: 300, damping: 22 }),
  });
  const DEFAULT_MAX_RADIUS = 32;
  // island.js constants (not tokens): press spring, kicks, shrink factor, volume give.
  const PRESS_SPRING = Object.freeze({ stiffness: 520, damping: 18 });
  const PRESS_KICK_GROW = 1.6;
  const PRESS_KICK_SHRINK = 1;
  const SHRINK_HEIGHT_STIFFNESS = 1.3;
  const MIN_HEIGHT = 20;
  const GIVE_DIVISOR = 7000;
  const GIVE_LIMIT = 0.05;
  // shared/motion.js: dt capped at 1/30 s, 4 substeps per frame.
  const MAX_DT = 1 / 30;
  const SUBSTEPS = 4;
  const FIRST_DT = 1 / 60;
  const REST = 0.1;

  const DEFAULT_VIEWS = Object.freeze({
    idle: { width: 120, height: 38, label: 'PETIT', detail: '' },
    listening: { width: 220, height: 52, label: '聞いているよ', detail: '' },
    working: { width: 250, height: 52, label: '処理しているよ…', detail: '' },
    success: { width: 250, height: 52, label: '完了したよ', detail: '' },
    error: { width: 250, height: 52, label: '確認が必要だよ', detail: '' },
  });
  const finitePositive = (n, fallback) => Number.isFinite(n) && n > 0 ? n : fallback;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const cleanView = (value, fallback) => ({
    width: finitePositive(value?.width, fallback.width),
    height: finitePositive(value?.height, fallback.height),
    label: String(value?.label ?? fallback.label),
    detail: String(value?.detail ?? fallback.detail),
  });
  const cleanSpring = (value, fallback) => ({
    stiffness: finitePositive(value?.stiffness, fallback.stiffness),
    damping: finitePositive(value?.damping, fallback.damping),
  });
  // Same integrator as shared/motion.js `step` (semi-implicit Euler, unit mass).
  const spring = (x, k, c) => ({ x, v: 0, t: x, k, c });
  const step = (s, dt) => { const a = -s.k * (s.x - s.t) - s.c * s.v; s.v += a * dt; s.x += s.v * dt; };
  const atRest = s => Math.abs(s.x - s.t) <= REST && Math.abs(s.v) <= REST;
  const snap = s => { s.x = s.t; s.v = 0; };

  function mount(container, options = {}) {
    if (!(container instanceof Element)) throw new TypeError('Morph Island requires a container Element');
    const views = { ...DEFAULT_VIEWS, ...(options.views || {}) };
    const widthSpring = cleanSpring(options.springs?.width, DEFAULT_SPRINGS.width);
    const heightSpring = cleanSpring(options.springs?.height, DEFAULT_SPRINGS.height);
    const maxRadius = finitePositive(options.maxRadius, DEFAULT_MAX_RADIUS);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const root = document.createElement('div');
    root.className = 'petit-morph-island';
    root.setAttribute('role', 'status');
    root.setAttribute('aria-live', 'polite');
    const marker = document.createElement('span');
    marker.className = 'petit-morph-island__marker';
    marker.setAttribute('aria-hidden', 'true');
    marker.textContent = '✦';
    const label = document.createElement('span');
    label.className = 'petit-morph-island__label';
    const detail = document.createElement('span');
    detail.className = 'petit-morph-island__detail';
    root.append(marker, label, detail);
    container.appendChild(root);

    let state = Object.hasOwn(views, options.initialState) ? options.initialState : 'idle';
    let raf = 0;
    let previousTime = 0;
    let disposed = false;
    const first = cleanView(views[state], DEFAULT_VIEWS.idle);
    const W = spring(first.width, widthSpring.stiffness, widthSpring.damping);
    const H = spring(first.height, heightSpring.stiffness, heightSpring.damping);
    const press = spring(1, PRESS_SPRING.stiffness, PRESS_SPRING.damping);
    const all = [W, H, press];

    function paint() {
      const h = Math.max(H.x, MIN_HEIGHT);
      // Volume: while the height moves fast, the width gives back a little.
      const give = clamp(-H.v / GIVE_DIVISOR, -GIVE_LIMIT, GIVE_LIMIT);
      root.style.width = W.x * (1 + give) + 'px';
      root.style.height = h + 'px';
      root.style.borderRadius = Math.min(h / 2, maxRadius) + 'px';
      root.style.transform = press.x === 1 ? '' : `scale(${press.x})`;
    }
    function frame(now) {
      if (disposed) return;
      const dt = previousTime ? Math.min((now - previousTime) / 1000, MAX_DT) : FIRST_DT;
      previousTime = now;
      const sub = dt / SUBSTEPS;
      for (let i = 0; i < SUBSTEPS; i++) for (const s of all) step(s, sub);
      const moving = !all.every(atRest);
      if (!moving) all.forEach(snap);
      paint();
      raf = moving ? requestAnimationFrame(frame) : 0;
      if (!moving) previousTime = 0;
    }
    function stopAnimation() {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      previousTime = 0;
    }
    function applyState(nextState, overrides = {}) {
      if (disposed) return false;
      if (!Object.hasOwn(views, nextState)) return false;
      const target = cleanView({ ...views[nextState], ...overrides }, DEFAULT_VIEWS.idle);
      const sizeChanged = target.width !== W.t || target.height !== H.t;
      if (sizeChanged) {
        // Shrinking: the height is stiffer so it settles with the width instead of lingering.
        const grow = target.width * target.height > W.t * H.t;
        H.k = heightSpring.stiffness * (grow ? 1 : SHRINK_HEIGHT_STIFFNESS);
        W.t = target.width;
        H.t = target.height;
        press.v -= grow ? PRESS_KICK_GROW : PRESS_KICK_SHRINK;
      }
      state = nextState;
      root.dataset.state = nextState;
      label.textContent = target.label;
      detail.textContent = target.detail;
      detail.hidden = !target.detail;
      if (reduced.matches) {
        stopAnimation();
        all.forEach(snap);
        paint();
      } else if (sizeChanged && !raf) {
        previousTime = 0;
        raf = requestAnimationFrame(frame);
      }
      return true;
    }
    function onMotionChange() {
      if (!reduced.matches) return;
      stopAnimation();
      all.forEach(snap);
      paint();
    }
    reduced.addEventListener?.('change', onMotionChange);
    applyState(state);
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
        root.remove();
      },
    };
  }

  window.PetitMorphIsland = Object.freeze({ mount, DEFAULT_VIEWS, DEFAULT_SPRINGS, DEFAULT_MAX_RADIUS });
})();
