(async () => {
  const api = window.petitSettings;
  const byId = (id) => document.getElementById(id);
  const fields = ['serverUrl', 'sttUrl', 'sttModel', 'keywordPath', 'modelPath', 'key'];
  const flags = ['wakeEnabled', 'login', 'updates', 'clearKey'];
  const state = await api.read();
  for (const name of fields) if (state[name]) byId(name).value = state[name];
  for (const name of flags) byId(name).checked = Boolean(state[name]);
  byId('version').textContent = `v${state.version}`;
  byId('key').placeholder = state.hasKey ? '保存済み（空欄で維持）' : 'AccessKey';
  if (!state.shortcutOK) byId('result').textContent = 'ショートカットが他のアプリと競合しています。トレイから呼び出してください。';
  for (const button of document.querySelectorAll('[data-model]')) button.onclick = async () => {
    const value = await api.selectModel(button.dataset.model);
    if (value) byId(button.dataset.model === 'ppn' ? 'keywordPath' : 'modelPath').value = value;
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
