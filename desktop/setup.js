(async () => {
  const api = window.petitSettings;
  const byId = (id) => document.getElementById(id);
  // プティちゃんの見た目設定と、その場で確認できる小さなプレビュー。
  function installPetPreview(state) {
    const M = window.PetitMascot;
    const preset = byId('petPreset');
    let body = state.petBody || '', ring = state.petRing || '';
    if (M) for (const [key, value] of Object.entries(M.PRESETS)) preset.append(new Option(value.label, key));
    preset.value = state.petPreset || 'pear';
    const preview = M ? M.create(byId('pet-preview'), { size: 84 }) : null;
    if (preview && M.startIdleLife) M.startIdleLife(preview, { minMs: 2500, maxMs: 6000 });
    const sync = () => {
      byId('petSizeOut').textContent = `${byId('petSize').value}px`;
      const colors = M ? M.resolveColors({ preset: preset.value, body: body || undefined, ring: ring || undefined }) : null;
      if (colors) { byId('petBodyPick').value = colors.body; byId('petRingPick').value = colors.ring; }
      preview?.setColors({ preset: preset.value, body: body || undefined, ring: ring || undefined });
      preview?.setMotion(byId('petMotion').value);
    };
    byId('petSize').oninput = sync;
    byId('petMotion').onchange = sync;
    preset.onchange = () => { body = ''; ring = ''; sync(); };
    byId('petBodyPick').oninput = (event) => { body = event.target.value; sync(); };
    byId('petRingPick').oninput = (event) => { ring = event.target.value; sync(); };
    byId('petColorReset').onclick = () => { body = ''; ring = ''; sync(); };
    sync();
    return { colors: () => ({ petBody: body, petRing: ring }) };
  }
  const fields = ['serverUrl', 'sttUrl', 'sttModel', 'modelPath', 'backbonePath', 'wakeThreshold', 'notificationMode', 'petSize', 'petPreset', 'petMotion'];
  const flags = ['wakeEnabled', 'login', 'updates', 'notifications', 'notificationSound', 'petEnabled', 'petRoam'];
  const state = await api.read();
  for (const name of fields) if (state[name] !== undefined && state[name] !== '') byId(name).value = state[name];
  for (const name of flags) byId(name).checked = Boolean(state[name]);
  const pet = installPetPreview(state);
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
      const result = await api.autoSetup({ modelPath: byId('modelPath').value.trim() });
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
  api.onUpdateProgress((message) => { byId('result').textContent = message; });
  byId('updates-check').onclick = async () => {
    byId('updates-check').disabled = true; byId('result').textContent = '更新を確認中…';
    try { byId('result').textContent = await api.checkUpdates(); }
    catch { byId('result').textContent = '更新確認に失敗しました。接続を確認してください。'; }
    finally { byId('updates-check').disabled = false; }
  };
  byId('notification-test').onclick = async () => {
    try { byId('notification-result').textContent = (await api.testNotification()).message; }
    catch (error) { byId('notification-result').textContent = error.message; }
  };
  byId('settings').onsubmit = async (event) => {
    event.preventDefault();
    try {
      const values = Object.fromEntries(fields.map((name) => [name, byId(name).value.trim()]));
      for (const name of flags) values[name] = byId(name).checked;
      Object.assign(values, pet.colors());
      await api.save(values);
    } catch (error) { byId('result').textContent = error.message; }
  };
})();
