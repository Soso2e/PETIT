(() => {
  const bridge = window.petitDesktop;
  if (!bridge) { document.getElementById('voice-state').textContent = 'Desktop用画面です。Web版は通常のPETITを開いてください。'; return; }
  const mic = document.getElementById('mic');
  document.getElementById('chat-form').addEventListener('submit', (event) => {
    if (document.getElementById('send').disabled) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  function activate({ voice = false } = {}) {
    document.body.classList.remove('appearing');
    requestAnimationFrame(() => document.body.classList.add('appearing'));
    document.getElementById('input').focus();
    if (voice && !mic.disabled && !mic.classList.contains('mic--listening') && !document.getElementById('send').disabled) mic.click();
  }
  bridge.onActivate(activate);
  bridge.onHide(() => document.dispatchEvent(new Event('petit:desktop-deactivate')));
  document.getElementById('hide').onclick = () => bridge.hide();
  document.getElementById('open-web').onclick = () => bridge.openWeb();
  document.getElementById('desktop-settings').onclick = () => bridge.settings();
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !event.isComposing) void bridge.hide(); });
  new MutationObserver(() => { document.body.dataset.listening = String(mic.classList.contains('mic--listening')); })
    .observe(mic, { attributes: true, attributeFilter: ['class'] });
  bridge.ready().then((state) => {
    document.getElementById('desktop-version').textContent = `v${state.version}`;
    if (!state.sttConfigured) {
      mic.disabled = true; mic.title = '設定で音声認識サーバーを指定してください';
      document.getElementById('voice-state').textContent = '文字入力で使えます。音声認識は設定から接続してください。';
    }
    activate(state);
  });
})();
