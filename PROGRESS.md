# PETIT — 作業の引き継ぎ

## 次に着手すること

- **Develop の受入**。稼働中のPETITの画面から、登録済みリポジトリで「依頼 → 進捗のストリーミング → 差分レビュー → 同じスレッドで続き → 停止したジョブの再開」を通しで確認する。合成リポジトリでは、Claude Code・Codex・Antigravity CLI の3つとも「編集してcommit → 同じスレッドでCLIのセッションを再開」を実CLIで確認済み（`python scripts/smoke_development_thread.py --live`）。稼働中の画面での操作、iPhoneからの操作、実CLIの実行中にCoreを再起動した場合の再開は未確認。関連 [#428](https://github.com/Soso2e/PETIT/issues/428)・[#481](https://github.com/Soso2e/PETIT/issues/481)・[開発ジョブの現行仕様](docs/dev/coding-tasks.md)。
- **開発ジョブの通知の実機受入**。通知カテゴリ `development` は初期OFF。設定でONにして、iPhone PWAのPush受信とタップ後に該当スレッドが開くこと、Desktop通知、Discord DMを確認する。[#483](https://github.com/Soso2e/PETIT/issues/483)・[通知の仕様](docs/channels/web_push_notifications.md)。

## 次の判断に関わる未確認事項

- **会話の速度**。稼働中の記録では、DeepSeek担当のTurnはモデル呼び出しの合計が中央値2.7秒・90%が6.2秒以内で、1 Turnあたりの呼び出しは1〜2回が多い。開発の依頼は `list_coding_repositories` → `propose_development_job` の2回のTool呼び出しを経ており、ここを1回にできるかが次の候補。CLI担当のTurn（中央値17秒）は件数が少なく、[#381](https://github.com/Soso2e/PETIT/issues/381) の評価には追加の計測が要る。
- **記憶の整理**。長く使える知識だけを保存する処理は実装済み。実モデルでの分類精度の確認と、既存記憶を整理する候補の本人確認が残る。自動想起はその後。[#446](https://github.com/Soso2e/PETIT/issues/446)・[記憶の仕様と確認手順](docs/core/renaissance-memory.md)。
- **配布版・iPhoneの受入**。実サービスを使った配布版・iPhone PWAの確認項目は [#343](https://github.com/Soso2e/PETIT/issues/343) と [Desktopの受入台帳](docs/desktop/desktop-readiness.md) を参照。Desktopを配布する際は、現在値が異なる `VERSION`・Web・Desktop のバージョンを揃えてからリリース検査を通す。

[現行の構成](docs/architecture.md) · [未完了のIssue](https://github.com/Soso2e/PETIT/issues) · [旧ログの参照先](docs/archive/development-log-legacy.md)
