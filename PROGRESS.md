# PETIT — 作業の引き継ぎ

## 次に着手すること

- **Develop の受入**。稼働中のPETITの画面から、登録済みリポジトリで「依頼 → 進捗のストリーミング → 差分レビュー → 同じスレッドで続き → 停止したジョブの再開」を通しで確認する。合成リポジトリでは、Claude Code・Codex・Antigravity CLI の3つとも「編集してcommit → 同じスレッドでCLIのセッションを再開」を実CLIで確認済み（`python scripts/smoke_development_thread.py --live`）。稼働中の画面での操作、iPhoneからの操作、実CLIの実行中にCoreを再起動した場合の再開は未確認。関連 [#428](https://github.com/Soso2e/PETIT/issues/428)・[#481](https://github.com/Soso2e/PETIT/issues/481)・[開発ジョブの現行仕様](docs/dev/coding-tasks.md)。
- **開発ジョブの通知の実機受入**。通知カテゴリ `development` は初期OFF。設定でONにして、iPhone PWAのPush受信とタップ後に該当スレッドが開くこと、Desktop通知、Discord DMを確認する。[#483](https://github.com/Soso2e/PETIT/issues/483)・[通知の仕様](docs/channels/web_push_notifications.md)。
- **Discord 進捗投稿の受入**。活動ログの取り込み（Google Drive の `BRAIN/inbox`・GitHub・PETIT・Discord）→ DeepSeek 3段要約 → `/petit digest` の定時投稿と、本人専用モード（既定で owner 以外に無反応）を実装（v0.68.0）。合成テストと、隔離環境での実 DeepSeek による3段要約は確認済み。実 Drive フォルダ・実 Discord（フォーラム投稿含む）と、ChatGPT / Claude の定期実行から inbox へ書き出せるかは未確認。[#504](https://github.com/Soso2e/PETIT/issues/504)・[手順](docs/life/activity-digest.md) §6。
- **自律性（未着手）**。永続タスクとイベント駆動の自発的な支援（[#372](https://github.com/Soso2e/PETIT/issues/372)）は、記憶の取り込みが動き出した後に着手する。通知カテゴリは初期OFFの原則を保つ。

## 次の判断に関わる未確認事項

- **会話の速度**。稼働中の記録では、DeepSeek担当のTurnはモデル呼び出しの合計が中央値2.7秒・90%が6.2秒以内。開発の依頼は、登録名を現在状況で渡して一覧取得の1往復を省くようにした（[#491](https://github.com/Soso2e/PETIT/issues/491)。実モデルでの確認は隔離環境で1回のみ）。CLI担当のTurn（中央値17秒）は件数が少なく、[#381](https://github.com/Soso2e/PETIT/issues/381) の評価には追加の計測が要る。
- **記憶の取り込みと整理**。会話の自動要約は1件の雑談で1か月以上止まっていた（[#487](https://github.com/Soso2e/PETIT/issues/487) で修正）。反映後は溜まった会話の要約が再開し、長く使える知識と判定されたものが記憶（`source=auto_knowledge`）へ入る。`/health` の `auto_summary` で未整理の件数を確認し、昇格された記憶の内容が妥当かを本人が確認する。既存の自動抽出（`auto_episode`）を整理する候補の本人確認も残る。自動想起はその後。[#446](https://github.com/Soso2e/PETIT/issues/446)・[記憶の仕様と確認手順](docs/core/renaissance-memory.md)。
- **配布版・iPhoneの受入**。実サービスを使った配布版・iPhone PWAの確認項目は [#343](https://github.com/Soso2e/PETIT/issues/343) と [Desktopの受入台帳](docs/desktop/desktop-readiness.md) を参照。Desktopを配布する際は、現在値が異なる `VERSION`・Web・Desktop のバージョンを揃えてからリリース検査を通す。

[現行の構成](docs/architecture.md) · [未完了のIssue](https://github.com/Soso2e/PETIT/issues) · [旧ログの参照先](docs/archive/development-log-legacy.md)
