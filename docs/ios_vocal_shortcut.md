# 「へいプティ」iOS Vocal Shortcut 仮導線

Issue #218 の仮実装手順です。

PETITのPWA自身で常時マイク監視は行わず、呼びかけの検出と音声認識はiOSへ任せます。PETIT側は、音声認識済みテキストを受け取って既存の会話処理へ渡すだけにします。

## 構成

```text
「へいプティ」
  ↓
iOS Vocal Shortcuts
  ↓
Apple ショートカット
  ↓
音声入力
  ↓
POST /api/voice
  ↓
既存 POST /api/chat
  ↓
PETIT Agent / Tools / Memory
  ↓
JSON reply
  ↓
iPhoneで読み上げ
```

`/api/voice` は独立したAgentやLLM経路を持ちません。既存の `/api/chat` を再利用するため、通常チャットと同じルーティング、会話保存、Tool Calling、確認付き書き込みを使います。

書き込み操作で確認が必要な場合、ショートカット経由で自動承認はしません。`needs_confirmation: true` と `pending_actions` を返し、PETIT UIから確認します。

## API

### Request

```http
POST /api/voice
Content-Type: application/json
```

```json
{
  "message": "今日なにする？",
  "session_id": "iphone-shortcut"
}
```

`session_id` は省略できます。省略時は `ios-shortcut` を使用します。

### Response

```json
{
  "ok": true,
  "reply": "今日はまずPETITの確認から始めよう。",
  "source": "ios_shortcut",
  "request_id": "ios_...",
  "needs_confirmation": false,
  "pending_actions": [],
  "error": null
}
```

確認が必要な書き込み候補がある場合は、次のようになります。

```json
{
  "ok": true,
  "reply": "確認してから実行するよ。",
  "source": "ios_shortcut",
  "request_id": "ios_...",
  "needs_confirmation": true,
  "pending_actions": [
    {
      "approval_id": "...",
      "name": "complete_task",
      "arguments": {}
    }
  ],
  "error": null
}
```

## iPhone側のショートカット

Apple ショートカットで、概ね次の順にアクションを作ります。iOSのバージョンによって表示名は多少異なります。

1. 新しいショートカットを作り、分かりやすい名前を付ける（例: `へいプティに聞く`）
2. 音声入力・音声テキスト化のアクションを追加する
3. PETITのTailscale Serve URLに `/api/voice` を付ける
4. `URLの内容を取得` を追加する
5. Methodを `POST` にする
6. Request Bodyを `JSON` にする
7. `message` に音声入力結果を渡す
8. 必要なら `session_id` に `iphone-shortcut` を入れる
9. 返却されたJSONから `reply` を取り出す
10. `reply` をiPhoneの読み上げアクションへ渡す

URL例:

```text
https://<PC名>.<tailnet名>.ts.net/api/voice
```

PETITは従来どおりTailnet内だけで利用し、Tailscale Funnelによるインターネット公開は前提にしません。

次にiOSのVocal Shortcutsで、このショートカットを呼び出すアクションを設定し、発話として `へいプティ` を登録します。

## PowerShellで先に確認する

PETITとLM Studioを起動し、Tailscale Serve URLを確認した状態で実行します。

```powershell
$body = @{
    message = "今日なにする？"
    session_id = "iphone-shortcut"
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "https://<PC名>.<tailnet名>.ts.net/api/voice" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body |
    ConvertTo-Json -Depth 10
```

成功時は `ok: true` と `reply` が返ります。

## 自動テスト

```powershell
python -m unittest tests.test_shortcut_voice -v
python -m compileall backend tests
```

## 実iPhone E2E

- [ ] PETIT / LM Studio / Tailscale Serveを起動
- [ ] ショートカット単体で音声入力できる
- [ ] `/api/voice`へPOSTできる
- [ ] `reply`を取得できる
- [ ] iPhoneが`reply`を読み上げる
- [ ] 「今日なにする？」など読取系Toolが通常チャットと同じ結果になる
- [ ] 書き込み候補が勝手に承認されない
- [ ] PETITの会話履歴へ同じターンが保存される
- [ ] PWA通常チャットが回帰していない
- [ ] 「へいプティ」からショートカットを起動できる

## 現時点の制約

- 「へいプティ、今日なにする？」を一息で自由文まで取り込む独自Wake Word処理は実装しない
- `へいプティ` で起動したあと、ショートカット側の音声入力で依頼を話す2段階を前提にする
- PWAでバックグラウンド常時録音はしない
- PETIT / LM Studio / Tailscaleが停止中なら会話は成立しない
- `/api/voice`専用の追加認証はまだ設けず、既存のTailnet内利用を前提とする
- 実iPhoneでのE2E確認が終わるまでは完成扱いにしない

## 関連

- Issue #218: 「へいプティ」Vocal ShortcutからPWAへ話しかける仮導線
- Issue #93: 音声会話を待たせないリアルタイム体験
- `docs/runtime-flows.md`: `/api/chat` 以降の会話処理フロー
