# ローカル開発環境の観測（#341 / #418）

PETIT を起動している PC の登録フォルダを定期観測する。Git ルートではローカルの状態とルート文書を、非 Git フォルダでは登録状態を取得する。接続クライアントは同じ Core の観測キャッシュを参照する。

## 設定

Develop タブから登録する。サーバーで配布する登録ルートや観測間隔がある場合は `.env` も使用できる。

```env
PETIT_WORKSPACE_CONTEXT_DIRS=C:\Projects\PETIT;C:\Projects\WEVORA
PETIT_WORKSPACE_CONTEXT_INTERVAL_SECONDS=30
PETIT_WORKSPACE_CONTEXT_MAX_AGE_SECONDS=90
```

Windowsの複数パス区切りは `;`、macOS/Linuxは `:`。UI と環境設定はそれぞれ最大8件。自動観測は登録フォルダに限る。PC 上のファイル探索は、利用者が開始した [開発ジョブ](coding-tasks.md) が扱う。

設定後はCoreを再起動し、`GET /api/workspace-context` の `enabled`、`status`、`collected_at`、各workspaceの `status` を確認する。 `status=observed` であっても各workspaceの `status=unavailable` はあり得る。LLMからは `get_local_development_status` Toolでキャッシュ参照する。 `workspace` に登録フォルダ名を指定した場合はその1件の詳細、指定なし・複数件の場合は一覧。データを得るためのGit fetchやファイル探索は発生しない。

## 観測できること

- 現在のGitブランチ、未コミットファイル名と状態（既存Observer）
- ローカルHEAD SHA・直近コミット5件・ローカルブランチ直近12件
- 設定済みtracking upstreamに対するahead/behind
- ローカルに存在するmain追跡refとの差分。 `origin/main` がない場合はローカル `main` を使用
- リポジトリ直下の `Concept.md`（最大2400文字）、`PROGRESS.md`（最大3600文字）、`README.md`（最大1200文字）。各ファイル128KB超・symlink・バイナリは内容取得対象外
- ファイル欠損、tracking未設定、Git障害、キャッシュのstaleを区別する

会話コンテキストへの観測注入を有効にする場合は `PETIT_WORKSPACE_CONTEXT_ENABLED=1` を使う。注入時は文書の抜粋を短くし、Tool 呼出時は収集済みの抜粋を返す。前面アプリの観測には `PETIT_WORKSPACE_CONTEXT_FOREGROUND_ENABLED=1` も必要。

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

複数 PC の主体・アクセス制御と、観測結果をプロジェクト単位で検索する導線は今後の対象。
