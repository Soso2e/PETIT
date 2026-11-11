// Desktopのプティちゃん。表示状態（mode）・一回きりの反応（event）・見た目・散歩をmainから受け取って描くだけ。
(() => {
  const api = window.petitPet;
  const M = window.PetitMascot;
  if (!api || !M) return;
  const open = document.getElementById('pet-open');
  const caption = document.getElementById('pet-status');
  const mascot = M.create(document.getElementById('pet-art'), { size: 96 });

  // mode: mainの pet-state.cjs と一致させる。state は PetitMascot.STATES のキー。
  const MODES = Object.freeze({
    idle: { state: 'idle', label: '待機中' },
    wake: { state: 'wake', label: '呼びかけ待機中' },
    active: { state: 'active', label: '会話中' },
    listening: { state: 'listening', label: '聞いているよ', keep: true },
    thinking: { state: 'thinking', label: '考え中…', keep: true },
    speaking: { state: 'speaking', label: 'お話し中' },
    error: { state: 'offline', label: '音声待機を確認', keep: true },
    sleep: { state: 'sleep', label: 'おやすみ中' },
  });
  const EVENTS = Object.freeze({ success: 'success', failed: 'error', approval: 'approval' });
  let mode = 'idle';
  let walking = false;
  let captionTimer = 0;

  function say(text, keep = false) {
    clearTimeout(captionTimer);
    caption.textContent = text || '';
    caption.classList.toggle('show', Boolean(text));
    if (text && !keep) captionTimer = setTimeout(() => caption.classList.remove('show'), 2600);
  }
  function setMode(next) {
    if (!Object.hasOwn(MODES, next)) return;
    const changed = next !== mode;
    mode = next;
    const def = MODES[next];
    document.body.dataset.mode = next;
    if (!walking) mascot.setState(def.state);
    open.setAttribute('aria-label', `PETITを開く（${def.label}）`);
    const text = next === 'error' ? def.label : M.STATES[def.state]?.caption;
    if (def.keep) say(text, true);
    else if (changed && text) say(text);
    else if (changed) say('');
  }
  const restful = () => mode === 'idle' || mode === 'wake';

  api.onMode(setMode);
  api.onEvent((name) => {
    const state = EVENTS[name];
    if (!state) return;
    mascot.setState(state);
    say(M.STATES[state].caption || '');
  });
  api.onAppearance((value) => {
    if (!value || typeof value !== 'object') return;
    mascot.setSize(value.size);
    document.documentElement.style.setProperty('--pet-size', `${Math.round(Number(value.size)) || 96}px`);
    mascot.setColors({ preset: value.preset, body: value.body || undefined, ring: value.ring || undefined });
    mascot.setMotion(value.motion);
  });
  api.onWalk((value) => {
    walking = Boolean(value?.walking) && restful();
    if (walking) {
      mascot.setFacing(value.dir < 0 ? -1 : 1);
      mascot.setEmotion('neutral'); mascot.setAction('walk'); mascot.look(0.6, 0.1);
    } else {
      mascot.look(null);
      mascot.setState(MODES[mode].state);
    }
  });

  M.startIdleLife(mascot, { canAct: () => restful() && !walking && !document.hidden });
  open.addEventListener('pointerenter', () => { if (restful() && !walking) mascot.react('happy', 'wiggle', 900); });
  open.addEventListener('click', () => {
    if (mode === 'sleep') mascot.react('surprised', 'surprise', 600);
    else mascot.react('joy', 'hop', 600);
    void api.open();
  });
  document.getElementById('pet-hide').addEventListener('click', () => void api.hide());
  document.addEventListener('visibilitychange', () => mascot.pause(document.hidden));
  setMode('idle');
})();
