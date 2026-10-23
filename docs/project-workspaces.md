# Projectとローカル開発フォルダ

Refs #345 / #341。新しい進捗台帳は作らず、Project Continuityのproject_source_linksと既存WorkspaceObserverを使用する。

1. 既存のWORKSPACE_CONTEXT_ENABLED / WORKSPACE_LOCAL_DEVELOPMENT_ENABLEDを明示ONにし、
   WORKSPACE_CONTEXT_DIRSへ対象Gitルートを登録する。任意フォルダ探索は行わない。
2. find_projectsで名称・確認済み別名から内部Project IDを取得する。同名が複数あれば選択を求める。
   未登録のProjectは本人の依頼と確認を経てregister_projectで既存Project Continuityへ登録できる。
3. list_project_workspacesで対象の正確なpathを確認する。
4. link_project_workspace(project_id, path)は確認付きWrite。
   承認時にもallowlist・実ディレクトリ・symlink/junction・Gitルートを検査する。
5. get_local_development_status(project_id=...)は確認済みの対応だけから観測キャッシュを読む。
   Task.project_idも同じ内部IDなので、Task→Project→フォルダを別名の推測なしに辿れる。

同じbasenameのフォルダが複数あっても、正確なcanonical rootのworkspace_idで区別する。
似た名前のProjectや未確認リンク、allowlistから外れたパスへ自動fallbackしない。
解除は対応のtombstoneを残すだけで、実ファイルは動かさない・削除しない。
別Projectへ移すときは既存の対応を明示解除し、再度確認して登録する。

## 証拠の区別

- collected_at: 観測を開始した時刻。キャッシュのstale/ageとともに扱う。
- documents.modified_at: 取得した文書自体の更新日時。実装・テスト完了の証明ではない。
- documents.source: workspace_idとルート相対ファイル名。
- documents.verification: 文書中の記述は未検証の主張であることを示す。
- head_sha / branch / changed_entries等: 実際のローカルGit観測。
- ahead/behindは手元のtracking refsとの比較。fetchやGitHub最新確認は行わない。

読む文書は既存と同じConcept.md / PROGRESS.md / README.mdだけ。
サイズ上限・秘密情報の伏せ字・symlink除外を維持し、読取中の変更も区別する。

Core PR #346の公開Tool集合へそのまま接続できる。Discord adapterも同じCoreを利用する想定であり、
このPRでDiscord Botや別の進捗管理サーバーを追加するものではない。

検証: 関連pytest 34件成功。Windowsの一時Gitリポジトリと一時SQLiteで実際のHEAD/未コミット/文書mtimeを照合した。本人の実Project・実登録フォルダ・Provider会話・配布端末の受入は未確認。
