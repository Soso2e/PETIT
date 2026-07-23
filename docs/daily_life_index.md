# 日次生活インデックス

## 目的

PETITへPC・スマートフォンなど複数端末から話した内容を横断し、タスクとは別に、その日に実際にあった生活・制作・開発・学習上の出来事を検索できるようにする。

## 処理方針

会話中には追加のLLM処理を行わない。既存の`conversations`テーブルへ会話を保存し、1日の終了後に前日分を1回だけ処理する。

既定値はAsia/Tokyoの00:10。PETITが停止していた場合は、起動後に直近7日以内の未処理日を古い順に補完する。

```text
各端末の会話
  ↓ 同じPETIT API / SQLite
conversations
  ↓ 1日1回
確実なノイズだけ除外
  ↓
ローカルLM Studio
  ↓
daily_indexes + memory(type=daily_index)
  ↓
Chroma / Markdown
```

## 対象データ

`session_id`で分断せず、対象日のすべての会話を時系列で使う。これにより、PCとスマートフォンの会話が同じ日次インデックスへまとまる。

原則としてユーザー発言はすべて送る。除外するのは次だけ。

- 空文字
- 絵文字・句読点など記号だけの発言
- 直前と完全に同じユーザー発言の連続重複

「うん」「喧嘩」「病院」など、短くても意味のある発言は残す。

PETITの返答は文脈用に含めるが、既定で240文字までに制限する。ツール名、時刻、session_idも補助情報として含める。

## ローカルLLM固定

日次処理はWeb UIでChat／AgentにDeepSeekを選択していても、`PETIT_DAILY_INDEX_*`で指定したローカルLM Studioへ送る。生活会話を外部APIへ自動送信しない。

入力が長い日は文字数で分割し、各結果をルールベースで重複排除して統合する。通常会話のトークン使用量は増えない。

## 抽出項目

```json
{
  "summary": "",
  "events": [],
  "activities": [],
  "foods": [],
  "people": [],
  "places": [],
  "emotions": [],
  "projects": [],
  "memory_candidates": [],
  "uncertain": []
}
```

- `events`: 外出、買物、人間関係などの出来事
- `activities`: 制作、開発、学習、作業
- `foods`: 食べたもの
- `people`: 関わった人物
- `places`: 行った場所
- `emotions`: 明示された感情
- `projects`: 関係する制作・開発プロジェクト
- `memory_candidates`: 長期的に残す可能性がある情報。自動昇格はしない
- `uncertain`: 予定、希望、仮定、否定、未確定情報

推測は保存せず、予定や「行こうかな」を実績として扱わない。

## 保存先

### SQLite

`daily_indexes`を日付単位の正本にする。同じ日は上書き可能な生成物として扱い、成功済みの日を通常実行で重複生成しない。

### 検索

生成内容を`memory`へ次の形式で1件保存する。

```text
type: daily_index
source: daily_index:YYYY-MM-DD
```

既存の`search_memory`が`petit_memory`を検索するため、新しい検索ツールを増やさず「昨日何食べた？」「渋谷に行った日」などを検索できる。

### Markdown

`PETIT_AI_DAILY_DIR/YYYY-MM-DD-index.md`へ、人間が確認しやすい副本を出力する。

## 失敗時

ローカルLM Studioが停止している、またはJSONが不正な場合は`failed`として記録する。元の`conversations`は変更しないため、次のスケジュール実行で再試行できる。

ChromaやMarkdownへの出力が失敗しても、SQLiteの生成結果は保持する。

## 設定

```env
PETIT_DAILY_INDEX_ENABLED=1
PETIT_DAILY_INDEX_TIMEZONE=Asia/Tokyo
PETIT_DAILY_INDEX_HOUR=0
PETIT_DAILY_INDEX_MINUTE=10
PETIT_DAILY_INDEX_POLL_MINUTES=10
PETIT_DAILY_INDEX_CATCHUP_DAYS=7
PETIT_DAILY_INDEX_BASE_URL=http://127.0.0.1:1234/v1
PETIT_DAILY_INDEX_MODEL=qwen/qwen3.5-9b
PETIT_DAILY_INDEX_API_KEY=lm-studio
PETIT_DAILY_INDEX_MAX_INPUT_CHARS=12000
PETIT_DAILY_INDEX_MAX_TOKENS=1200
PETIT_DAILY_INDEX_ASSISTANT_MAX_CHARS=240
```
