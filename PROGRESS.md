# PETIT — 作業の引き継ぎ

## 次に着手すること

- **Develop の受入**。登録済みの検証用リポジトリで、実CLIによる直接編集 → 応答のストリーミング → 差分レビュー → 同じスレッドでの再開を確認する。個別テストの記録はあるが、稼働中のPETITでの一連の操作は未確認。関連 [#428](https://github.com/Soso2e/PETIT/issues/428)・[開発ジョブの現行仕様](docs/dev/coding-tasks.md)。

- **Develop進捗SSEの不正イベント耐性（v0.66.2）**。JSONが壊れた単一イベントを無視して後続イベントを受け取れるようにした。実ブラウザ・実CLIでの受入は未確認。\n\n## 次の判断に関わる未確認事項

- **記憶の整理**。長く使える知識だけを保存する処理は実装済み。実モデルでの分類精度の確認と、既存記憶を整理する候補の本人確認が残る。自動想起はその後。[#446](https://github.com/Soso2e/PETIT/issues/446)・[記憶の仕様と確認手順](docs/core/renaissance-memory.md)。
- **配布版・iPhoneの受入**。実サービスを使った配布版・iPhone PWAの確認項目は [#343](https://github.com/Soso2e/PETIT/issues/343) と [Desktopの受入台帳](docs/desktop/desktop-readiness.md) を参照。Desktopを配布する際は、現在値が異なる `VERSION`・Web・Desktop のバージョンを揃えてからリリース検査を通す。

[現行の構成](docs/architecture.md) · [未完了のIssue](https://github.com/Soso2e/PETIT/issues) · [旧ログの参照先](docs/archive/development-log-legacy.md)
