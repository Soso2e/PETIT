/* PETIT shared Toggle Switch. Framework-free, opt-in, no page placement.
 *
 * Ported from DesignBookmark Motion "Toggle Switch"
 * (https://designbookmark.com/motion-src/toggle-switch/). The springs and the
 * knob maths are the upstream values: a position spring (320 stiffness, 18
 * damping) and a stretch spring (300, 20). Flipping kicks the stretch so the
 * knob grows long toward where it is going, then lands with a small bounce
 * and rounds back up while the track fills with colour.
 *
 * The switch is built on a real <input type="checkbox" role="switch">, so
 * forms, keyboard (Space), screen readers and existing code that reads or sets
 * `input.checked` keep working.
 *
 *   PetitToggleSwitch.mount(container, { label, description, checked, onChange })
 *   PetitToggleSwitch.enhance(existingCheckbox)
 */
(() => {
  'use strict';
  if (window.PetitToggleSwitch) return;

  // Upstream switch.js: S(0, 320, 18) and S(0, 300, 20).
  const POSITION_SPRING = Object.freeze({ stiffness: 320, damping: 18 });
  const STRETCH_SPRING = Object.freeze({ stiffness: 300, damping: 20 });
  const STRETCH_KICK = 60;   // velocity given to the stretch spring on flip
  const TRAVEL = 20;         // px the knob travels (52 track - 26 knob - 2*3 inset)
  const KNOB = 26;           // px knob size at rest
  const MAX_GROW = 10;       // px the knob stretches while travelling
  const SUBSTEPS = 4;        // shared/motion.js integrates 4 substeps per frame
  const MAX_DT = 1 / 30;     // shared/motion.js caps a frame at 1/30 s
  const REST = 0.0005;

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const spring = (x, cfg) => ({ x, v: 0, t: x, k: cfg.stiffness, c: cfg.damping });
  const step = (s, dt) => {
    const a = -s.k * (s.x - s.t) - s.c * s.v;
    s.v += a * dt;
    s.x += s.v * dt;
  };
  const resting = s => Math.abs(s.x - s.t) < REST && Math.abs(s.v) < REST;

  const checkedDescriptor = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement ? window.HTMLInputElement.prototype : {}, 'checked');

  function build(input) {
    const track = document.createElement('span');
    track.className = 'petit-switch__track';
    track.setAttribute('aria-hidden', 'true');
    const knob = document.createElement('i');
    knob.className = 'petit-switch__knob';
    track.appendChild(knob);
    return { track, knob };
  }

  // Attach motion to an input that already sits in the DOM.
  function attach(input, root, track, knob, onChange) {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const start = input.checked ? 1 : 0;
    const p = spring(start, POSITION_SPRING);
    const w = spring(0, STRETCH_SPRING);
    let on = !!input.checked;
    let raf = 0;
    let last = 0;
    let disposed = false;

    function paint() {
      const grow = clamp(w.x, 0, 1) * MAX_GROW;
      const x = p.x * TRAVEL;
      const tx = on ? x - grow * clamp(p.x, 0, 1) : x;
      knob.style.width = (KNOB + grow).toFixed(2) + 'px';
      knob.style.transform = `translateX(${tx.toFixed(2)}px)`;
      track.style.setProperty('--petit-switch-fill', (clamp(p.x, 0, 1) * 100).toFixed(1) + '%');
    }
    function frame(now) {
      if (disposed) return;
      const dt = last ? Math.min((now - last) / 1000, MAX_DT) : 1 / 60;
      last = now;
      for (let i = 0; i < SUBSTEPS; i++) { step(p, dt / SUBSTEPS); step(w, dt / SUBSTEPS); }
      if (resting(p) && resting(w)) {
        p.x = p.t; p.v = 0; w.x = w.t; w.v = 0;
        raf = 0; last = 0;
      } else {
        raf = requestAnimationFrame(frame);
      }
      paint();
    }
    function snap() {
      if (raf) cancelAnimationFrame(raf);
      raf = 0; last = 0;
      p.x = p.t; p.v = 0; w.x = 0; w.t = 0; w.v = 0;
      paint();
    }
    // animate: true for a person flipping it, false for code setting it.
    function render(next, animate) {
      on = !!next;
      root.dataset.checked = on ? 'true' : 'false';
      p.t = on ? 1 : 0;
      if (!animate || reduced.matches) { snap(); return; }
      w.t = 0; w.v = STRETCH_KICK;
      if (!raf) { last = 0; raf = requestAnimationFrame(frame); }
    }

    function onInput() {
      if (disposed) return;
      render(input.checked, true);
      if (typeof onChange === 'function') onChange(input.checked);
    }
    input.addEventListener('change', onInput);
    // Outside a <label>, clicking the drawn track would not reach the input.
    function onTrackClick() { if (!disposed && !input.closest('label') && !input.disabled) input.click(); }
    track.addEventListener('click', onTrackClick);

    // Keep the knob right when code sets `input.checked` directly
    // (settings loaded from the server do this without a change event).
    let ownDescriptor = false;
    if (checkedDescriptor && checkedDescriptor.set) {
      Object.defineProperty(input, 'checked', {
        configurable: true,
        enumerable: true,
        get() { return checkedDescriptor.get.call(this); },
        set(value) {
          checkedDescriptor.set.call(this, value);
          if (!disposed && !!value !== on) render(!!value, false);
        },
      });
      ownDescriptor = true;
    }

    root.dataset.checked = on ? 'true' : 'false';
    paint();

    return {
      element: root,
      input,
      isChecked: () => input.checked,
      // Set from code. Pass { animate: true } to play the flip.
      setChecked(value, { animate = false } = {}) {
        if (disposed) return false;
        if (ownDescriptor) checkedDescriptor.set.call(input, !!value);
        else input.checked = !!value;
        render(!!value, animate);
        return true;
      },
      destroy(removeElement = true) {
        if (disposed) return;
        disposed = true;
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        input.removeEventListener('change', onInput);
        track.removeEventListener('click', onTrackClick);
        if (ownDescriptor) delete input.checked;
        if (removeElement) root.remove();
      },
    };
  }

  // Create a full settings row: text on the left, switch on the right.
  function mount(container, options = {}) {
    if (!(container instanceof Element)) throw new TypeError('Toggle Switch requires a container Element');
    const root = document.createElement('label');
    root.className = 'petit-switch';
    const text = document.createElement('span');
    text.className = 'petit-switch__text';
    const title = document.createElement('span');
    title.className = 'petit-switch__label';
    title.textContent = String(options.label ?? '');
    text.appendChild(title);
    if (options.description) {
      const detail = document.createElement('span');
      detail.className = 'petit-switch__description';
      detail.textContent = String(options.description);
      text.appendChild(detail);
    }
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.className = 'petit-switch__input';
    input.setAttribute('role', 'switch');
    if (options.id) input.id = String(options.id);
    if (options.name) input.name = String(options.name);
    input.checked = !!options.checked;
    if (options.disabled) input.disabled = true;
    const { track, knob } = build(input);
    root.append(text, input, track);
    container.appendChild(root);
    return attach(input, root, track, knob, options.onChange);
  }

  // Turn an existing <input type="checkbox"> into a switch, in place.
  // The input keeps its id, name, listeners and position; only the look changes.
  function enhance(input, options = {}) {
    if (!(input instanceof Element) || input.type !== 'checkbox') {
      throw new TypeError('Toggle Switch enhance() requires a checkbox input');
    }
    if (input.__petitSwitch) return input.__petitSwitch;
    const root = document.createElement('span');
    root.className = 'petit-switch petit-switch--inline';
    input.classList.add('petit-switch__input');
    input.setAttribute('role', 'switch');
    input.parentNode.insertBefore(root, input);
    root.appendChild(input);
    const { track, knob } = build(input);
    root.appendChild(track);
    const api = attach(input, root, track, knob, options.onChange);
    const destroy = api.destroy;
    api.destroy = () => {
      destroy(false);
      root.parentNode.insertBefore(input, root);
      root.remove();
      input.classList.remove('petit-switch__input');
      input.removeAttribute('role');
      delete input.__petitSwitch;
    };
    input.__petitSwitch = api;
    return api;
  }

  window.PetitToggleSwitch = Object.freeze({
    mount,
    enhance,
    springs: Object.freeze({ position: POSITION_SPRING, stretch: STRETCH_SPRING }),
  });
})();
