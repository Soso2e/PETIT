# PETIT Renaissance Core

Refs #345 / #303 / #304 / #338。v0.32.0の会話処理は
Core所有のThread/Turnと単一native Tool Loopを使用する。

## 会話と実行

- Web/小型Desktop/音声の既存 /api/chat は同期adapter。history引数は互換受付のみでモデルへ渡さない。
- /api/threads、/api/threads/{id}/turns、/api/turns/{request_id} は同じledgerを使う。
- accepted入力は実行前に保存。同一request ID・同一入力は結果を再利用し、異なる入力は409。同一Threadの実行競合は429。
- 終了した会話本文の正本は既存conversations。TurnはそのIDを参照し、本文の二重保存を残さない。
- 旧session IDはそのままThreadに対応。NULL/空の旧sessionは推測で割り当てない。
- Threadは明示操作で作成・選択。2時間idleによる分割とfetch monkeypatchを廃止。
- Threadごとの履歴を最大12往復/9000文字で取得。進捗Eventsはモデルhistoryへ入れない。
- BrainがToolを直接選択。公開集合はbrain.PUBLIC_TOOLSで固定し、内部execute_agent_write等は公開しない。
- assistant tool_calls / role=tool / tool_call_id / reasoning_contentを維持。12 Tool calls・8 roundsで停止。
- 決定論的な日本語ルーター、Capability判断LLM、別Agentへの再解釈は本番text経路から外す。
- 旧agent.py等は既存契約の回帰・比較用に残るが、新しいchat/Workerは呼ばない。旧agent_legacy.runは削除。
- Visionは既存の画像観測→Read専用回答を同じTurn受付へ接続し、画像所有権・cloud同意・TTLを維持。

## 書込みと承認

- risk・schemaは既存Registryを再利用。Task Toolは同名を複数登録しない。
- SQLite内の書込みは既存サービスとeffect receiptを同じtransactionで確定する。
- Notionへは既存outboxを使用する。ローカル保存の成功と外部同期の成功を同一視しない。
- 外部Writeにはexactly-onceを主張しない。実行途中の停止はunknownとし、自動再実行しない。
- 承認は引数・Tool・元Turn・期限とともに永続保存。承認IDを再送しても二重実行しない。
- 承認画面は構造化状態から表示し、応答の固定テンプレートは作らない。
- 取消要求は既存効果の取消しではない。receiptは結果照会APIに残す。

## プライバシー・運用

- 初期実装は単一Coreプロセス（uvicorn workers=1）。受付後の再送は同じIDを使用する。
- local_only Threadでは外部Providerへの送信前に停止する。自動Provider fallbackは導入しない。
- proactive openerもThreadの公開範囲を継承する。Memory拡張前の段階導入ではprivate記憶の保存を止め、通常記憶として漏らさない。
- Coreが現在時刻を毎Turn提示する。再起動による中断は結果照会とUIの最新依頼欄から確認できる。
- 他Threadの履歴は通常文脈へ入れない。横断検索は別Toolで明示取得する。
- 長期記憶の保存件数に固定上限はない。通常のTool結果として渡す記憶は合計最大5項目。
- local_only会話は自動episode要約の入力から除外し、通常会話の自動export/index処理も行わない。
- 既存会話があるDBの初回拡張前にSQLite Backup APIで .before-renaissance.bak を作成する。
  既存バックアップは上書きしない。追加型schemaで旧行・IDは変更しない。
- 切戻し時にバックアップで現在DBを上書きしない。新規Turn/receiptを保持したまま旧版を停止・再移行する。
- 認証の追加・インターネット公開は今回の範囲外。既存localhost/Tailnet限定運用を維持する。

## 検証境界

合成Tool会話・障害注入・一時DB・隔離HTTPで受付/再送/同時操作/承認/停止/保存結果を確認する。
Mockは実Providerの自然言語理解を証明しない。
配布Desktop・実iPhone/PWA・実音声・Notion等の実データ操作は別の受入として記録する。

今回の記録: Core/関連回帰118件+3 subtests、Thread ClientのNodeテスト4件、隔離Chromium 1440/390px（実HTTP・一時DB・合成Provider）を確認。全pytestは既存venvのsona_agent_coreでSQLiteApprovalStoreをimportできずcollection中断。依存を勝手に更新せず、実機受入と区別する。
