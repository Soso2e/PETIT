(async () => {
  const state = await window.petitRecovery.read();
  const byId = (id) => document.getElementById(id);
  byId('server').textContent = state.serverUrl;
  byId('title').textContent = state.reason === 'renderer' ? '画面を再び開けます' : 'PETITに接続できません';
  byId('description').textContent = state.reason === 'renderer'
    ? '画面の処理が停止しました。小型会話で保存された下書きは開き直すと復元されます。履歴を確認してから続けてください。'
    : 'サーバーが停止しているか、対応する画面を取得できませんでした。接続先の起動と通信を確認してください。';
  byId('retry').onclick = async () => {
    byId('retry').disabled = true;
    try { await window.petitRecovery.retry(); }
    catch { byId('result').textContent = '再接続できませんでした。接続設定を確認してください。'; byId('retry').disabled = false; }
  };
  byId('settings').onclick = () => window.petitRecovery.settings();
})();
