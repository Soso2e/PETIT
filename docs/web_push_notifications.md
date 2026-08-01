# Web Push通知

Issue #92で追加した、PWA向け通知基盤の設定・運用・検証手順です。

## 設計

通知は次の3層に分離しています。

1. 通知イベント生成
   - カテゴリ、タイトル、本文、PETIT内の遷移先を決める
2. 通知サービス
   - SQLiteへイベントを保存し、ユーザー設定を確認する
3. Provider
   - 現在は`WebPushProvider`
   - 将来は同じ境界へ`APNsProvider`を追加する

アプリ側の呼び出し元は`backend.notifications.dispatch_notification()`だけを使い、Web Push固有の購読情報やVAPIDを扱いません。

## 通知カテゴリ

すべて初期状態ではOFFです。通知設定UIで個別に有効化します。端末でPush通知を初めて有効にしたときだけ、無限計測を防ぐ`work_session`も同時にONにします。後から個別にOFFへ戻せます。

- `work_session` — 作業セッションの声かけ
- `schedule_reminder` — 予定前リマインド
- `high_task` — Highタスクのリマインド
- `morning_briefing` — 朝ブリーフィング
- `github_ci_failure` — GitHub CI失敗

明示的なテスト通知だけはカテゴリ設定を無視します。

## 必要な環境変数

```env
PETIT_VAPID_PUBLIC_KEY=<URL-safe Base64のP-256公開鍵>
PETIT_VAPID_PRIVATE_KEY=/absolute/path/to/PETIT/storage/keys/vapid_private.pem
PETIT_VAPID_SUBJECT=mailto:your-address@example.com
PETIT_WEB_PUSH_TTL_SECONDS=300
```

- 秘密鍵はGitへ追加せず、Git管理外の`storage/keys/`などへ置く
- `PETIT_VAPID_SUBJECT`は`mailto:`または公開可能な`https:` URLを使う
- `PETIT_WEB_PUSH_TTL_SECONDS`は任意。既定値は300秒、最大86400秒

## VAPID鍵の作成例

OpenSSLで秘密鍵を作り、ブラウザの`applicationServerKey`用公開鍵をURL-safe Base64へ変換します。

```bash
mkdir -p storage/keys
openssl ecparam -name prime256v1 -genkey -noout -out storage/keys/vapid_private.pem
openssl ec -in storage/keys/vapid_private.pem -pubout -outform DER \
  | tail -c 65 \
  | base64 \
  | tr -d '=\n' \
  | tr '/+' '_-'
```

表示された公開鍵を`PETIT_VAPID_PUBLIC_KEY`へ設定し、`storage/keys/vapid_private.pem`の絶対パスを`PETIT_VAPID_PRIVATE_KEY`へ設定します。Windowsでは`.env.example`のパス例を参照してください。

## API

### 状態取得

```http
GET /api/notifications/status
```

VAPID設定、`pywebpush`依存、購読件数、カテゴリ、設定値を返します。秘密鍵は返しません。

### 購読登録

```http
POST /api/notifications/subscriptions
Content-Type: application/json

{
  "endpoint": "https://...",
  "expirationTime": null,
  "keys": {
    "p256dh": "...",
    "auth": "..."
  }
}
```

同じendpointは更新され、解除済みなら再有効化されます。

### 購読解除

```http
DELETE /api/notifications/subscriptions
Content-Type: application/json

{
  "endpoint": "https://..."
}
```

サーバー側では論理削除し、配信対象から外します。

### 通知設定

```http
GET /api/notifications/preferences
PUT /api/notifications/preferences
```

```json
{
  "preferences": {
    "work_session": true,
    "schedule_reminder": false,
    "high_task": true,
    "morning_briefing": false,
    "github_ci_failure": true
  }
}
```

### テスト通知

```http
POST /api/notifications/test
Content-Type: application/json

{}
```

購読中の全Web Push端末へテスト通知を送信します。

## SQLite

- `push_subscriptions` — Web Push購読情報
- `notification_preferences` — カテゴリ別ON/OFF
- `notification_events` — 生成した通知イベント
- `notification_deliveries` — 端末ごとの送信結果
- `work_sessions` — 20分ごとの継続確認、返答待ち、自動停止状態

Push Serviceが404または410を返した購読は、恒久的に無効な購読として自動停止します。

## ブラウザ確認

Web PushはSecure Contextが必要です。

- `http://localhost`または`http://127.0.0.1`で確認する
- LAN IPやTailscale IPで開く場合はHTTPS化する
- 通知許可は通知設定UIのボタン操作から要求する

確認手順:

1. `pip install -r requirements.txt`
2. VAPID環境変数を設定する
3. PETITを起動する
4. ヘッダーの`通知 OFF`を開く
5. `この端末で有効にする`を押して許可する
6. 作業セッションの声かけがONになったことを確認し、ほかの必要なカテゴリもONにする
7. `テスト通知`を押す
8. PETITのタブを閉じた状態でも通知が届くことを確認する
9. 通知を押してPETITが開くことを確認する
10. `この端末の通知を解除`後に送信対象から外れることを確認する

## 実iPhone PWA確認

iPhone/iPadでは、Web Pushはホーム画面へ追加したWebアプリで確認します。

1. iOS/iPadOS 16.4以降を使用する
2. HTTPSで公開したPETITをSafariで開く
3. 共有メニューから`ホーム画面に追加`する
4. ホーム画面のPETITアイコンから起動する
5. PETIT内の通知設定UIから通知許可を要求する
6. テスト通知を送る
7. PETITを閉じ、ロック画面・通知センターで受信を確認する
8. 通知タップでPETITが開くことを確認する
9. iOS設定の通知一覧にPETITが表示されることを確認する
10. 購読解除後に通知が届かないことを確認する

未確認のまま完了扱いにせず、実機名、iOSバージョン、公開URL、確認日時、成功・失敗内容を記録してください。

## 既存機能への影響

- VAPID未設定でもFastAPIと既存チャットは起動する
- `pywebpush`未導入時も既存チャットは動き、通知UIだけが未設定を表示する
- カテゴリは初期OFF。通知設定UIから新しく購読した端末では、無限計測防止のため`work_session`だけ同時にONになる
- APNs実装は今回の対象外
