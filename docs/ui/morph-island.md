# PETIT shared Morph Island — draft integration

## Status / upstream limitation

- Reference: https://designbookmark.com/motion#db-morph-island
- Source: https://designbookmark.com/motion-src/morph-island/index.html
- Shared source: https://designbookmark.com/motion-src/shared/tokens.css , base.css , motion.js
- At implementation time the source URLs could not be fetched via the available web/browser access. **No source-faithful reproduction is claimed.**
- The current `DEFAULT_SPRING` values (260 stiffness, 24 damping, mass 1) are **PETIT placeholders**, not extracted from upstream. Before merging, read upstream tokens.css and the island source, replace these values/logic as needed, and verify parity.
- This PR is a reusable foundation only: no automatic insertion into Chat, Develop, Dashboard, or the Electron desktop. Page placement needs a separate design decision.

## Usage

Load `/static/components/morph-island.css` and `/static/components/morph-island.js` from the existing asset pipeline. Then:

```js
const island = window.PetitMorphIsland.mount(document.getElementById('status-host'), {
  initialState: 'idle',
  // override spring with verified upstream parameters once available
});
island.setState('listening');
island.setState('working', { label: 'Codexで開発中' });
island.setState('success', { label: 'PRを作成したよ' });
island.destroy(); // on teardown
```

The caller owns all state updates. Do not infer real agent/voice/task status from timers; subscribe to the authoritative service events. Only one status should own an island instance. Add focusable controls **outside** its status role until interaction requirements are decided.

## Review checklist

1. Retrieve and inspect all original HTML/CSS/JS and shared springs, including any usage/licensing conditions.
2. Match upstream stiffness/damping and content timing exactly, then compare movement visually.
3. Test the reusable component with and without motion reduction; ensure no orphan animation frames after destroy.
4. Integrate with the existing Chat/Develop/Desktop authoritative state events, without duplicating the existing status pill or interfering with mascot pointer events.
5. Run the actual PETIT app, check responsive views and browser console errors; only then mark the PR ready.
