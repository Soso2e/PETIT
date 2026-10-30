# #368 SDK撤去とProvider共通境界

最新main `3620ea1` を基準に実施。元のCLI作業ブランチの43ファイル/未コミット変更を取り込まず保全する。

|分類|対象|根拠と対応|
|---|---|---|
|REMOVE|SDK Brain/Worker、optional requirements、probe/smoke/SDK専用UIと単体テスト|本Issueの採用廃止。CLI/ACPには不要。SDK importと実行経路を削除|
|REPLACE|引数検証、Provider identity、子プロセス停止|Codexも利用するため `provider_runtime.py` へ移し共通契約としてテスト|
|REPLACE|設定UI・選択肢|新規SDK接続は409。旧SDKが接続済みで優先順位に残ると実行を止め再選択案内。明示保存でSDKを順位から外す|
|KEEP|暗号化済み設定の旧キー、モデル選択ID、会話・承認・Receipt・既存DB|読み込み時の書換・削除なし。旧選択は廃止と表示し、別AIへ自動切替しない|
|KEEP|Antigravity公式CLI/ACP、DeepSeek、LM Studio、Codex|SDKとは別経路。CLI許諾ゲートとACPの隔離ゲートは維持|
|KEEP|旧SDKレポート・履歴|当時の証拠として保持。現行機能とは区別|

## 移行と復旧

SettingsでCodex/DeepSeekの接続・費用許可を確認し、AI設定を明示保存する。
旧model routingを使う場合はChat/Agentでlocalまたは設定済みDeepSeekを明示選択する。
SDK用の暗号化キーは自動削除しない。不要なら管理者が旧disconnect APIで明示解除できる。
DB migrationやpip uninstallは実施しない。ロールバックは変更前コードへ戻せるが、依存の再導入は別途必要。

旧SDK専用シナリオを削除する代わりに、共通bridgeの承認→Receipt→再送・再開、strict schema、guest拒否を直接回帰検証する。
