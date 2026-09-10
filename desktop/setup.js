(async () => {
  const api = window.petitSettings;
  const byId = (id) => document.getElementById(id);
  const fields = ['serverUrl', 'sttUrl', 'sttModel', 'keywordPath', 'modelPath', 'key'];
  const flags = ['wakeEnabled', 'login', 'updates', 'clearKey'];
  const state = await api.read();
  for (const name of fields) if (state[name]) byId(name).value = state[name];
  for (const name of flags) byId(name).checked = Boolean(state[name]);
  byId('version').textContent = `v${state.version}`;
  byId('wake-platform').textContent = `${state.platform} / ${state.arch}`;
  byId('wake-result').textContent = state.lastWakeError || '';
  byId('key').placeholder = state.hasKey ? '保存済み（空欄で維持）' : 'AccessKey';
  if (!state.shortcutOK) byId('result').textContent = 'ショートカットが他のアプリと競合しています。トレイから呼び出してください。';
  for (const button of document.querySelectorAll('[data-model]')) button.onclick = async () => {
    const value = await api.selectModel(button.dataset.model);
    if (value) byId(button.dataset.model === 'ppn' ? 'keywordPath' : 'modelPath').value = value;
  };
  api.onProgress((message) => { byId('wake-result').textContent = message; });
  byId('picovoice-console').onclick = () => api.openConsole();
  byId('wake-cancel').onclick = () => api.cancelSetup();
  byId('wake-auto').onclick = async () => {
    const controls = [...document.querySelectorAll('input, button')].filter((el) => el.id !== 'wake-cancel');
    controls.forEach((el) => { el.disabled = true; });
    byId('wake-cancel').hidden = false;
    byId('wake-result').textContent = '自動設定を開始しています…';
    try {
      const result = await api.autoSetup({ key: byId('key').value, clearKey: byId('clearKey').checked });
      byId('wake-result').textContent = result.message;
      if (result.ok) {
        byId('keywordPath').value = result.keywordPath;
        byId('modelPath').value = result.modelPath;
      }
      const saved = await api.read();
      if (saved.hasKey) { byId('key').value = ''; byId('key').placeholder = '保存済み（空欄で維持）'; }
    } catch { byId('wake-result').textContent = '設定処理に失敗しました。設定画面を開き直して再試行してください。'; }
    finally { controls.forEach((el) => { el.disabled = false; }); byId('wake-cancel').hidden = true; }
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
