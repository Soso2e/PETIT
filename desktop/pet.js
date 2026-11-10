(() => {
  const api = window.petitPet;
  if (!api) return;
  const open = document.getElementById('pet-open');
  const status = document.getElementById('pet-status');
  const captions = Object.freeze({
    idle: 'そばにいるよ',
    wake: '呼びかけ待機中',
    active: '会話中',
    listening: '聞いているよ',
    thinking: '考え中…',
    error: '音声待機を確認',
  });
  function setMode(mode) {
    if (!Object.hasOwn(captions, mode)) return;
    document.body.dataset.mode = mode;
    status.textContent = captions[mode];
    open.setAttribute('aria-label', `PETITを開く（${captions[mode]}）`);
  }
  api.onMode(setMode);
  open.addEventListener('click', () => void api.open());
  document.getElementById('pet-hide').addEventListener('click', () => void api.hide());
})();
