/* PETIT shared Morph Island. Framework-free, opt-in, no page placement.
 * Motion constants are provisional until the original DesignBookmark tokens.css
 * can be inspected. Do not claim animation parity with the reference.
 */
(() => {
  'use strict';
  if (window.PetitMorphIsland) return;

  const DEFAULT_SPRING = Object.freeze({ stiffness: 260, damping: 24, mass: 1 });
  const DEFAULT_VIEWS = Object.freeze({
    idle: { width: 120, height: 38, radius: 24, label: 'PETIT', detail: '' },
    listening: { width: 220, height: 52, radius: 28, label: '聞いているよ', detail: '' },
    working: { width: 250, height: 52, radius: 28, label: '処理しているよ…', detail: '' },
    success: { width: 250, height: 52, radius: 28, label: '完了したよ', detail: '' },
    error: { width: 250, height: 52, radius: 28, label: '確認が必要だよ', detail: '' },
  });
  const finitePositive = (n, fallback) => Number.isFinite(n) && n > 0 ? n : fallback;
  const cleanView = (value, fallback) => ({
    width: finitePositive(value?.width, fallback.width),
    height: finitePositive(value?.height, fallback.height),
    radius: finitePositive(value?.radius, fallback.radius),
    label: String(value?.label ?? fallback.label),
    detail: String(value?.detail ?? fallback.detail),
  });

  function mount(container, options = {}) {
    if (!(container instanceof Element)) throw new TypeError('Morph Island requires a container Element');
    const views = { ...DEFAULT_VIEWS, ...(options.views || {}) };
    const spring = {
      stiffness: finitePositive(options.spring?.stiffness, DEFAULT_SPRING.stiffness),
      damping: finitePositive(options.spring?.damping, DEFAULT_SPRING.damping),
      mass: finitePositive(options.spring?.mass, DEFAULT_SPRING.mass),
    };
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
    const keys = ['width', 'height', 'radius'];
    const position = { width: first.width, height: first.height, radius: first.radius };
    const velocity = { width: 0, height: 0, radius: 0 };
    let target = first;

    function paint() {
      root.style.width = position.width + 'px';
      root.style.height = position.height + 'px';
      root.style.borderRadius = position.radius + 'px';
    }
    function frame(now) {
      if (disposed) return;
      const delta = previousTime ? Math.min((now - previousTime) / 1000, 0.032) : 1 / 60;
      previousTime = now;
      // Semi-implicit Euler with substeps keeps the spring stable after tab inactivity.
      const steps = Math.max(1, Math.ceil(delta / (1 / 120)));
      const dt = delta / steps;
      let moving = false;
      for (let i = 0; i < steps; i++) {
        for (const key of keys) {
          const acceleration = (-spring.stiffness * (position[key] - target[key]) - spring.damping * velocity[key]) / spring.mass;
          velocity[key] += acceleration * dt;
          position[key] += velocity[key] * dt;
        }
      }
      for (const key of keys) {
        if (Math.abs(position[key] - target[key]) > 0.1 || Math.abs(velocity[key]) > 0.1) moving = true;
        else { position[key] = target[key]; velocity[key] = 0; }
      }
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
      state = nextState;
      target = cleanView({ ...views[nextState], ...overrides }, DEFAULT_VIEWS.idle);
      root.dataset.state = nextState;
      label.textContent = target.label;
      detail.textContent = target.detail;
      detail.hidden = !target.detail;
      if (reduced.matches) {
        stopAnimation();
        Object.assign(position, { width: target.width, height: target.height, radius: target.radius });
        for (const key of keys) velocity[key] = 0;
        paint();
      } else if (!raf) {
        previousTime = 0;
        raf = requestAnimationFrame(frame);
      }
      return true;
    }
    function onMotionChange() { applyState(state); }
    reduced.addEventListener?.('change', onMotionChange);
    paint();
    applyState(state);
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

  window.PetitMorphIsland = Object.freeze({ mount, DEFAULT_VIEWS, DEFAULT_SPRING });
})();
