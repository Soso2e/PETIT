# ローカル開発環境の読取（Issue #341 / Phase 1）

PETITを起動している **PC側Coreのローカルファイル** について、登録済みGitルートのみを読み取る任意機能。iPhone/PWAやDesktopは同じCoreの観測キャッシュを参照する。GitHub APIの情報とは別ソースであり、サーバーの外にある別PCのファイルを直接読める機能ではない。

## 設定

`.env` に必要なものだけ設定する。

```env
PETIT_WORKSPACE_CONTEXT_ENABLED=1
PETIT_WORKSPACE_LOCAL_DEVELOPMENT_ENABLED=1
PETIT_WORKSPACE_CONTEXT_DIRS=C:\\Projects\\PETIT;C:\\Projects\\WEVORA
PETIT_WORKSPACE_CONTEXT_INTERVAL_SECONDS=30
PETIT_WORKSPACE_CONTEXT_MAX_AGE_SECONDS=90
```

Windowsの複数パス区切りは `;`、macOS/Linuxは `:`。ルートを最大8件明示する。自動発見・ディスク全体探索は行わない。`PETIT_WORKSPACE_CONTEXT_FOREGROUND_ENABLED` は別機能で、未設定なら前面アプリを取得しない。いずれかのOpt-inが0なら開発資料本文は読まない。

設定後はCoreを再起動し、`GET /api/workspace-context` の `enabled`、`status`、`collected_at`、各workspaceの `status` を確認する。 `status=observed` であっても各workspaceの `status=unavailable` はあり得る。LLMからは `get_local_development_status` Toolでキャッシュ参照する。 `workspace` に登録フォルダ名を指定した場合はその1件の詳細、指定なし・複数件の場合は一覧。データを得るためのGit fetchやファイル探索は発生しない。

## 観測できること

- 現在のGitブランチ、未コミットファイル名と状態（既存Observer）
- ローカルHEAD SHA・直近コミット5件・ローカルブランチ直近12件
- 設定済みtracking upstreamに対するahead/behind
- ローカルに存在するmain追跡refとの差分。 `origin/main` がない場合はローカル `main` を使用
- リポジトリ直下の `Concept.md`（最大2400文字）、`PROGRESS.md`（最大3600文字）、`README.md`（最大1200文字）。各ファイル128KB超・symlink・バイナリは内容取得対象外
- ファイル欠損、tracking未設定、Git障害、キャッシュのstaleを区別する

通常のBrainへ常時入る観測packetでは文書本文をさらに短くし、Tool呼出時のみ収集済みの長めの抜粋を返す。

## 何がわからないか

- リモートGitHubの**現在の**HEAD/PR/CI/デプロイ: 本機能はnetworkに触れず、tracking refもfetchしていない。最新比較は従来のGitHub evidenceを使う。
- 仕様書に書かれた機能の実装真偽、テストの成否、実機での動作: `Concept.md` は目標、`PROGRESS.md` は引継ぎ文書であり、それだけで実装完了にしない。
- 他端末のPCや、Coreの実行ユーザーから読めないディレクトリ。
- ソースコード本体の自由な本文取得: Phase 1で未対応。後続は明示選択・範囲制限・認可を入れて検討する。

## セキュリティ

設定されたroot以外を読まない。パス指定を受け取る汎用ファイル読取Toolを提供しない。Gitはsubprocessの配列引数を使い、shell、fetch、pull、checkout、実行フック、書込み操作はしない。取得ファイルは3つの固定名・ルート直下だけ。既知の秘密情報代入と秘密鍵ブロックの赤字化は**完全な秘密検出を保証しない**ので、設定前に各プロジェクトのドキュメントへ秘密情報が含まれていないことを確認する。ネット越しにPETITを公開する場合、既存Coreの接続経路・認証境界を確認し、一般公開しない。

文書本文やGitコミットメッセージはユーザー入力より信用しない。AIに対する命令として実行せず、証拠として扱う。Observerが無効化・停止・古い場合、保存済みの過去結果を「現在の状況」として返さない。

## テスト・受入

```powershell
python -m unittest tests.test_workspace_context tests.test_local_development -v
python -m compileall backend/workspace_context.py backend/local_development.py backend/tools/local_development.py
```

実PC受入で、PETIT / WEVORAなど登録済みの2プロジェクトについて、現在ブランチ・HEAD・未コミット変更・Concept/PROGRESSを手動照合する。ローカルmainやorigin refを古くしたケース、ファイル未配置、stale、無効化後の露出なしも確認する。GitHub evidenceと矛盾すれば、根拠源と取得時刻を明示し、結論を勝手に統一しない。

## 次段階

明示許可したファイル範囲のコード・diffの根拠照合、PETIT内部Project IDとローカルrootの確認付き紐付け、登録設定UI、複数PCの主体/アクセス制御、観測結果をプロジェクト単位で検索できる導線は後続Issueに分割する。
