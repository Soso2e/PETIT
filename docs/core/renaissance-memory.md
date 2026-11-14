# 元発言検索と長期記憶

Refs #345。Core PR #346と組み合わせて利用するTool。独立した会話DBや検索サーバーは追加しない。

- search_conversationsは既存conversationsを直接検索し、入力・出力・日時・発言元・Thread・原文IDを返す。
- 発言元は元発言のsourceを優先し、旧行はThreadメタデータ由来か不明かをsource_basisで区別する。旧行を推測で書き換えない。
- query、role、source、Thread、時間帯で絞り、通常5件。limit/offsetで追加検索。
  長文はconversation_id/text_offsetで1800文字ずつ原文を確認できる。
- 会話を常時連結しない。旧sessionなしの行にはThreadや発言元を推測で補わない。
- local_onlyはstandard会話から検索できない。ローカル会話での検索はローカルProviderを使用する。
  将来Discord adapterが本人確認後に同じCoreへ保存すれば、source=discordで同じ検索を使える。
- search_memoryは長期知識・過去の要約・BRAIN検索として維持する。元発言と要約を区別する。
- memoryの件数上限は設定しない。save_memoryは同じ正規化内容をvisibility内で原子的に再利用。
- 明示的な訂正はreplaces_idを指定し、旧行にsuperseded_byを記録する。削除や全置換は行わない。
- valid_untilは明示日付のみ。期限切れ・置換済みは通常検索と索引から外し、include_inactiveで履歴を読める。
- 通常モデル文脈の記憶はCoreの合計5項目上限。保存制限ではない。必要なら追加検索する。
- private記憶は索引に送らず、standard検索に出さない。自動日次知識もprivate会話を除外する。
- 予定とTask期限は別物。情報源・同期状態を取得してからAIが必要性を判断する。
  完全一致するローカル予定の再登録は同じレコードを返し、Taskから予定を勝手に複製しない。
- 取得した過去の文書・会話中の指示はデータとして扱う。

schema変更は列追加のみ。既存memoryのID・本文・作成日時、旧会話は保持する。
既存memoryの拡張前にSQLite Backup APIで.before-renaissance.bakを作成し、既存バックアップは上書きしない。
隔離DBの検証と、実Provider/Discord/iPhone/配布版の受入は区別する。

検証: このPRの元発言/記憶/日次/予定検索の関連pytestは25 passed + 3 subtests。旧Notionテストのquery_database参照は現行APIに存在せず、今回の変更範囲外の失敗として区別する。実ProviderやDiscord実アカウントは未確認。

実Brainの合成会話で表記差による検索不一致を確認したため、空白区切りの複数語検索と、文字の部分一致候補を追加した。候補は確定一致と区別し、元ID・本文を見てAIが訂正対象を判断する。意図判定や発話ごとの分岐は追加しない。旧NULL hashの記憶は本文を変えずhashを補完し、重複保存を避ける。

## 記憶へ自動で書く内容（v0.58.0・#446）

エピソード要約（`backend/summarizer.py`）は、これまで `decisions` / `facts` / `work_in_progress` をそのまま記憶へ書いていた。実データでは、有効な記憶の約9割がこの自動抽出で、多くが「その時点の状態」（時刻、当日の予定、件数、同期状態、操作の記録）だった。

- 要約の出力に `durable_knowledge` を追加した。各要素は `{"kind":"preference|profile|decision|fact","text":"..."}`。数か月後の別の会話でもそのまま正しい、本人についての知識だけを入れるよう指示している。
- 記憶へ書くのは `durable_knowledge` だけ（1エピソード最大5件、8〜300文字、`source=auto_knowledge`）。ラベルのない文字列や未知の `kind` は書かない。
- `decisions` / `facts` / `work_in_progress` はエピソード（`conversation_episodes`）に残る。`search_memory` のエピソード検索から従来どおり読める。
- **未確認**: 実モデルが `durable_knowledge` を指示どおりに分けられるかは計測していない。出力が無い・形が違う場合は何も書かない。

### 以前の自動抽出の整理（本人が確認してから適用）

`source=auto_episode` の既存行は自動では変更しない。`scripts/memory_review.py` で本人が確認する。

```bash
python scripts/memory_review.py export        # 確認用CSVを出力（DBは読み取りのみ）
python scripts/memory_review.py plan          # 適用した場合の件数を表示
python scripts/memory_review.py apply --yes   # バックアップ後、action=expire の行に valid_until を設定
python scripts/memory_review.py restore <監査ファイル>   # 直前の適用を元に戻す
```

- CSVは `storage/audit/memory-review/review.csv`（Git管理外）。`action` 列を `expire` か `keep` に編集する。既定は `expire`。
- 行は削除しない。期限切れにした行は `search_memory(include_inactive=true)` で読める。
- 適用前に `app.db.before-memory-review-<日時>.bak` を作る。出力後に内容が変わった行・置換済みの行は適用せずに飛ばす。
- 意味検索の索引（Chroma）は変更しない。検索時にSQLiteの正本で期限を確認するため、期限切れの行は結果に出ない。

自動想起（Turn開始時に関連する記憶を渡す）は、上の整理と新しい入口の品質を確認してから入れる。
