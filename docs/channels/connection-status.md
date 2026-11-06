# 接続ステータス（#327）

上部の同期表示、PCサイドバーの状態表示、Settingsの「接続と同期」から開く。各サービスを展開すると、接続・同期の状態、成功/エラー時刻、エラー内容/コード、同期失敗/競合件数を確認できる。時刻は日本時間。閉じる/Escapeで元の操作へ戻る。

- `GET /api/connections`：SQLiteの既存同期履歴・Notion outbox/inbox・保存済み診断を読む。表示更新で外部通信や同期を実行しない。一部状態が読めなくても他サービスを返す。
- `POST /api/connections/{service}/check`：対象だけを読取診断し、診断履歴を保存する。5秒の通信待機上限、同一サービスの同時確認禁止、10秒以内の再確認は保存済み結果を返す。
- 未設定/未確認/接続済み/同期中/正常/エラー/同期競合/古いキャッシュを区別する。接続確認の新鮮さは5分、Notion同期は既存pull間隔の2倍、他の同期履歴は5分。通信が成功しても同期成功にはしない。接続先や認証設定が変更された場合、設定の非公開ハッシュで以前の接続診断を無効にする。
- エラー文章・タスク名は既知の認証情報、Bearerやtoken等のパターン、URLを伏せる。診断エラーはHTTPコードと設定確認の案内だけを返し、API応答本文や秘密設定は返さない。

## サービスごとの確認範囲

| サービス | 表示根拠 / 接続確認 |
|---|---|
| LM Studio | `PETIT_LM_BASE_URL`のmodels API。Chat/Agentの別プロバイダーとは独立。モデルのロードや会話品質は別途確認する。 |
| Notion | 既存タスクpull・outbox/inbox履歴。接続確認はusers/me（認証確認）。タスク/親ページの共有権限は同期結果・競合比較で確認する。 |
| Google Calendar | Google ICSと有効なOAuth書込連携の履歴。ICSはHEAD、OAuthは対象カレンダーの読取。HEAD非対応はエラーとして確認し、OAuth期限切れは既存認証手順で再設定する。認証の更新や予定同期は行わない。TimeTree/ローカルICSをGoogleの正常状態として扱わない。 |
| GitHub | `github:repo:*`の既存同期履歴。user APIで認証を確認する。リポジトリ別アクセス権・CI成功とは別。 |
| Linkraft | `linkraft:*`の既存同期履歴。owner専用projects読取APIのみ。snapshot同期を実行しない。 |
| AivisSpeech | speakers APIへの接続のみ。音声合成や再生は実行しない。 |
| BRAIN | Vault設定、フォルダの読取権限と検索索引への接続のみ。再インデックスは実行しない。 |

## Notionの復旧

未解消のoutbox操作を、成功操作の履歴に埋もれず表示する。タスク名・操作・状態・エラー・試行回数・最終試行・次回予定を表示し、失敗したタスク1件だけを既存APIでキューへ戻す。既存workerの再試行設定を変更しない。上限到達と競合には自動再試行予定を表示しない。

`task_sync_queue.last_attempt_at`を追加し、workerが実際にclaimした時刻を保存する。既存履歴の時刻は推定せず「未記録」にする。競合の比較・採用は既存UIとrevisionの二重操作ガードを共用する。再試行受付はNotion反映完了ではなく、同期結果を再確認する必要がある。

Google書込同期は従来と同じタイミングで行い、成功/失敗を既存`sync_state`の`google_calendar_push`へ記録する。画面を開いたことによる書込はない。

## 検証

Backendの関連pytest、Frontendの既存Nodeテストに加え、`node tests/browser/connection-status.cjs`で1440/390/320pxの導線・秘密情報を含まないfixture・HTML文字列の無害な表示・単一再試行・既存競合比較/採用・明示接続確認・部分障害・Escapeとフォーカス復元を検証する。DesktopのPlaywrightを使用し、ブラウザ未導入時は`PETIT_TEST_BROWSER_PATH`に既存Chromium系ブラウザの実行ファイルを指定する。

実行結果：Backend関連53件、UI関連63件と31サブテスト、Frontend17件、Desktop62件成功。隔離Braveで1440/390/320px、実UniverseページのSettingsとサイドバーのキーボード導線も確認。構文チェックとmainアプリのAPI登録も確認。配布物のビルドは今回の範囲外。

ライブ同期hookが共有connectionを受け取れず、競合のNotion側採用が失敗していた既存不整合も修正。比較前にlive schemaを確保し、採用時のタスク・キュー・snapshot・監査を同一トランザクションへ渡す。snapshot保存失敗時の全体rollbackを回帰テストで確認。

実Notionへの再試行・競合採用、実OAuth/外部API、実iPhone/PWA/配布Desktopの受入は別途行う。実データの診断画面を開くだけでは同期処理を実行しない。
