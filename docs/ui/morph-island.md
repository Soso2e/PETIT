# PETIT shared Morph Island

## Status / upstream source

- Reference: https://designbookmark.com/motion#db-morph-island
- Source read on 2026-11-15: `motion-src/morph-island/index.html`, `island.css`, `island.js`, and `motion-src/shared/tokens.css`, `base.css`, `motion.js`.
- The motion is ported from that source, and `tests/test_morph_island.cjs` checks it frame by frame against a separate re-implementation of upstream's integrator.
- This is a reusable foundation only. Nothing inserts it into Chat, Develop, Dashboard, or the Electron desktop automatically. Placing it on a page needs a separate design decision.

### Motion values (parity with upstream)

| Item | Upstream | PETIT |
|---|---|---|
| Width spring | `--island-w: 380 24` | `DEFAULT_SPRINGS.width` 380 / 24 |
| Height spring | `--island-h: 300 22` | `DEFAULT_SPRINGS.height` 300 / 22 |
| Height when shrinking (area decreases) | stiffness ×1.3 | same |
| Corner radius | no spring: `min(h/2, --island-radius)`, `--island-radius: 32` | same, `DEFAULT_MAX_RADIUS` 32 |
| Minimum painted height | 20px | same |
| Volume give | width × `1 + clamp(-H.v/7000, ±0.05)` | same |
| Press scale on a morph | spring 520 / 18, velocity kick −1.6 (grow) / −1 (shrink) | same, written as `transform: scale()` |
| Integration | semi-implicit Euler, unit mass, dt ≤ 1/30 s, 4 substeps per frame | same |

### Intentional differences

- **Sizes and content**: the upstream demo states (idle/timer/upload/call) and their blur cross-fade belong to that demo. PETIT keeps its own status views (idle/listening/working/success/error) with a text label.
- **Reduced motion**: upstream keeps animating with critically damped springs. PETIT jumps straight to the target and schedules no frames (unchanged from the previous behaviour).
- **Loop**: upstream runs one rAF loop forever. PETIT runs frames only while a spring is moving and stops when everything is within 0.1 of its target. The first frame after a stop uses dt = 1/60 s.
- **Not ported**: autoplay (`--island-cycle-ms`), pointer press feedback, re-tapping the same state, and upstream's `translateX(-50%)` positioning. The PETIT island is a status display without its own controls, and the caller decides its position.
- A label-only `setState` (same size) does not start a morph or a press dip.

## Usage

Load `/static/components/morph-island.css` and `/static/components/morph-island.js` from the existing asset pipeline. Then:

```js
const island = window.PetitMorphIsland.mount(document.getElementById('status-host'), {
  initialState: 'idle',
  // optional: springs: { width: { stiffness, damping }, height: { stiffness, damping } }, maxRadius: 32
});
island.setState('listening');
island.setState('working', { label: 'Codexで開発中' });
island.setState('success', { label: 'PRを作成したよ' });
island.destroy(); // on teardown
```

Views take `width`, `height`, `label` and `detail`. Corner radius comes from height, so views have no `radius`. The old single `spring` option and `DEFAULT_SPRING` export were replaced by `springs` and `DEFAULT_SPRINGS`. Nothing in the repository used them.

The caller owns all state updates. Do not infer real agent/voice/task status from timers; subscribe to the authoritative service events. Only one status should own an island instance. Add focusable controls **outside** its status role until interaction requirements are decided.

## Remaining before page placement

1. Integrate with the existing Chat/Develop/Desktop authoritative state events, without duplicating the existing status pill or interfering with mascot pointer events.
2. Compare the movement visually against the upstream page in a real browser (only the numerical parity is tested).
3. Run the actual PETIT app, check responsive views and browser console errors.
