(async () => {
  const api = window.petitSettings;
  const byId = (id) => document.getElementById(id);
  const fields = ['serverUrl', 'sttUrl', 'sttModel', 'modelPath', 'backbonePath', 'wakeThreshold'];
  const flags = ['wakeEnabled', 'login', 'updates'];
  const state = await api.read();
  for (const name of fields) if (state[name] !== undefined && state[name] !== '') byId(name).value = state[name];
  for (const name of flags) byId(name).checked = Boolean(state[name]);
  byId('version').textContent = `v${state.version}`;
  byId('wake-platform').textContent = `${state.platform} / ${state.arch}`;
  byId('wake-result').textContent = state.lastWakeError || '自動設定、または手動でONNXモデルとbackboneを選択してください。';
  if (!state.shortcutOK) byId('result').textContent = 'ショートカットが他のアプリと競合しています。トレイから呼び出してください。';
  for (const button of document.querySelectorAll('[data-model]')) button.onclick = async () => {
    const value = await api.selectModel(button.dataset.model);
    if (value) byId(button.dataset.model === 'dir' ? 'backbonePath' : 'modelPath').value = value;
  };
  const auto = byId('wake-auto');
  const cancel = byId('wake-cancel');
  api.onProgress((message) => { byId('wake-result').textContent = message; });
  auto.onclick = async () => {
    auto.disabled = true;
    cancel.hidden = false;
    byId('wake-result').textContent = 'openWakeWordの自動設定を開始します…';
    try {
      const result = await api.autoSetup();
      byId('wake-result').textContent = result.message;
      if (result.ok) {
        byId('modelPath').value = result.modelPath;
        byId('backbonePath').value = result.backbonePath;
      }
    } catch (error) { byId('wake-result').textContent = error.message; }
    finally { auto.disabled = false; cancel.hidden = true; }
  };
  cancel.onclick = async () => {
    cancel.disabled = true;
    try { await api.cancelSetup(); }
    finally { cancel.disabled = false; }
  };
  byId('updates-check').onclick = async () => { byId('result').textContent = await api.checkUpdates(); };
  byId('settings').onsubmit = async (event) => {
    event.preventDefault();
    try {
      const values = Object.fromEntries(fields.map((name) => [name, byId(name).value.trim()]));
      for (const name of flags) values[name] = byId(name).checked;
      await api.save(values);
    } catch (error) { byId('result').textContent = error.message; }
  };
})();
