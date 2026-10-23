# 元発言検索と長期記憶

Refs #345。Core PR #346と組み合わせて利用するTool。独立した会話DBや検索サーバーは追加しない。

- search_conversationsは既存conversationsを直接検索し、入力・出力・日時・発言元・Thread・原文IDを返す。
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
隔離DBの検証と、実Provider/Discord/iPhone/配布版の受入は区別する。

検証: このPRの元発言/記憶/日次/予定検索の関連pytestは25 passed + 3 subtests。旧Notionテストのquery_database参照は現行APIに存在せず、今回の変更範囲外の失敗として区別する。実ProviderやDiscord実アカウントは未確認。
