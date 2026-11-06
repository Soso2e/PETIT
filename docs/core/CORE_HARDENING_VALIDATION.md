# PETIT Core Hardening Validation

この変更は新機能追加ではなく、モデル経路・記憶・同期・SQLite・ブラウザセッションの整合性を固めるものです。

## 検証順序

### 1. 自動テスト

```bash
python -m compileall backend tests
python -m unittest discover -s tests -v
node --check frontend/app.js
```

### 2. 1モデル構成

ChatとAgentを同じLM Studio endpoint・同じモデルに設定して、次を順番に確認する。

1. 雑談はChat経路で1回だけ生成する
2. コードレビュー・設計分析はAgent経路になる
3. 時刻はLLMなしで返る
4. タスク・予定・BRAINは関連ツールだけを使う
5. 書き込みは確認前に実行されず、承認後に1回だけ実行する
6. 会話を再読み込みして同じsessionの履歴が復元される
7. バックグラウンド結果は作成元sessionだけに表示され、表示後に明示ackされる
8. 会話エピソードを確定し、再起動後も検索・朝ブリーフィングで参照できる
9. Notionで削除したタスクが、成功した次回同期後にキャッシュから消える
10. 同期失敗時は以前のキャッシュを維持する

### 3. 2モデル構成

1モデル構成が安定してから、Agentだけ別endpointへ変更する。

1. 雑談はChat endpoint
2. 分析・実装・ツール判断・エピソード要約はAgent endpoint
3. Agent停止時、取得済みの読み取り結果だけChatで整形できる
4. Agent停止時、ツール選択と書き込みは勝手に省略しない
5. `/api/health`と各ターン詳細のrequested/actual routeが一致する

## 実環境でのみ確認できる項目

- LM Studioの実モデル応答時間とThinking無効化
- 実Notion・Google ICS・TimeTree・Linkraft・GitHub credentials
- 実ブラウザの再読み込み、複数タブ、複数端末
- PETIT再起動後のSQLite・Chroma・エピソード復元

実環境E2Eが完了するまでは、2モデル分散や新しい外部連携を完成扱いにしない。
