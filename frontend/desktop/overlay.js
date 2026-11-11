(() => {
  const bridge = window.petitDesktop;
  if (!bridge) { document.getElementById('voice-state').textContent = 'Desktop用画面です。Web版は通常のPETITを開いてください。'; return; }
  const mic = document.getElementById('mic');
  const date = document.getElementById('desktop-date');
  const syncDate = () => {
    const now = new Date();
    date.textContent = new Intl.DateTimeFormat('ja-JP', {
      month: 'long', day: 'numeric', weekday: 'long'
    }).format(now);
  };
  document.getElementById('chat-form').addEventListener('submit', (event) => {
    if (document.getElementById('send').disabled) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  function activate({ voice = false } = {}) {
    document.dispatchEvent(new Event('petit:desktop-activate'));
    syncDate();
    document.body.classList.remove('appearing');
    requestAnimationFrame(() => document.body.classList.add('appearing'));
    document.getElementById('input').focus();
    if (voice && !mic.disabled && !mic.classList.contains('mic--listening') && !document.getElementById('send').disabled) (window.PetitVoiceConversation ? window.PetitVoiceConversation.start() : mic.click());
  }
  bridge.onActivate(activate);
  bridge.onHide(() => document.dispatchEvent(new Event('petit:desktop-deactivate')));
  document.getElementById('hide').onclick = () => bridge.hide();
  document.getElementById('open-web').onclick = () => bridge.openWeb();
  document.getElementById('open-workspace').onclick = () => bridge.workspace();
  document.getElementById('desktop-settings').onclick = () => bridge.settings();
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !event.isComposing) void bridge.hide(); });
  const send = document.getElementById('send');
  let reportedActivity = '';
  let speaking = false;
  const syncPetActivity = () => {
    const listening = mic.classList.contains('mic--listening');
    document.body.dataset.listening = String(listening);
    const activity = listening ? 'listening' : send.disabled ? 'thinking' : speaking ? 'speaking' : 'active';
    if (activity !== reportedActivity) { reportedActivity = activity; void bridge.petActivity?.(activity); }
  };
  // session.js / voice.js からの表示用ヒント。発話中は状態として、成功・失敗・確認待ちは一回きりの反応として渡す。
  const PET_EVENTS = { success: 'success', error: 'failed', approval: 'approval' };
  document.addEventListener('petit:mascot', (event) => {
    const state = event.detail?.state;
    if (state === 'speaking' || state === 'idle') { speaking = state === 'speaking'; syncPetActivity(); }
    else if (Object.hasOwn(PET_EVENTS, state)) void bridge.petActivity?.(PET_EVENTS[state]);
  });
  const activityObserver = new MutationObserver(syncPetActivity);
  activityObserver.observe(mic, { attributes: true, attributeFilter: ['class'] });
  activityObserver.observe(send, { attributes: true, attributeFilter: ['disabled'] });
  syncPetActivity();
  bridge.ready().then((state) => {
    document.getElementById('desktop-version').textContent = `v${state.version}`;
    if (!state.sttConfigured) {
      mic.disabled = true; mic.title = '設定で音声認識サーバーを指定してください';
      document.getElementById('voice-state').textContent = '文字入力で使えます。音声認識は設定から接続してください。';
    }
    activate(state);
  });
})();
