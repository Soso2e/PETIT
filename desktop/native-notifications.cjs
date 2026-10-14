'use strict';
// Keep native objects alive until interaction; OS permission cannot be inferred from isSupported().
const guidance = 'macOS/Windowsの通知許可・サウンド・集中モードを確認してください。Macではアプリの署名も必要です。';
function nativeNotifications({ Notification, open, timeoutMs = 3000 }) {
  const active = new Set();
  let state = { delivery: 'idle', error: '' };
  function deliver(event, sound = false) {
    if (!Notification.isSupported()) throw new Error('OS通知を利用できません。「画面のすみに声かけ」を選んでください。');
    const notification = new Notification({ title: String(event.title || 'PETIT').slice(0, 120), body: String(event.body || '').slice(0, 500), silent: sound !== true });
    active.add(notification);
    const result = { delivery: 'requested', error: '' };
    state = result;
    return new Promise(resolve => {
      let timer;
      const finish = () => { clearTimeout(timer); resolve({ ...result }); };
      notification.once('show', () => { result.delivery = 'shown'; finish(); });
      notification.once('failed', () => {
        result.delivery = 'failed'; result.error = `OS通知を表示できません。${guidance}`;
        active.delete(notification); finish();
      });
      notification.once('close', () => active.delete(notification));
      notification.once('click', () => { active.delete(notification); open(); });
      timer = setTimeout(finish, timeoutMs);
      try { notification.show(); }
      catch {
        result.delivery = 'failed'; result.error = `OS通知を要求できません。${guidance}`;
        active.delete(notification); finish();
      }
    });
  }
  return { deliver, read: () => ({ ...state }), reset: () => { state = { delivery: 'idle', error: '' }; } };
}
function deliveryMessage(result) {
  if (result?.error) return result.error;
  if (result?.delivery === 'shown') return `OS通知の表示イベントを受け取りました。音・実際の受信は端末で確認してください。${guidance}`;
  return `テスト通知の表示を要求しました。受信は未確認です。${guidance}`;
}
module.exports = { nativeNotifications, deliveryMessage };
