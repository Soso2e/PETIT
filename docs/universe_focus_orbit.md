# PETIT Universe — Life / Project / Task

## 目的

PETITのタスクを、単なる一覧ではなく次の階層として理解できるようにする。

```text
Life
└─ Project（1つのUniverse）
   └─ Task
```

例:

```text
Life
└─ Roomies
   └─ 歩きモーションを作る
```

LifeはNotionからSQLiteへ同期された未完了タスク全体、Projectは継続的な取り組み、Taskは実際に行う作業を表す。

Project Relationが未設定のTaskは、否定的な「未分類」ではなく `All` と表示する。`Life > All` は、特定Projectに属さない生活全体のTaskを意味する。

## ビューの役割

### Focus

- 選択中Projectを中央に置く
- そのProjectの未完了Highタスクだけを軌道へ表示する
- Projectセレクトと前後ボタンでFocus内からProjectを移動できる
- `Life › Project`のパンくずから全体へ戻れる
- タスクの選択と作業開始を分離する
- ボタンまたはスマホのピンチでOrbitを拡大・縮小する
- 遠景では主要Taskを優先し、拡大すると追加Taskとラベルを表示する

### Universe

- Life配下のProjectを縦に一覧表示する
- Project内の未完了High / Mid / Lowタスクを優先度順に表示する
- ProjectまたはTaskを選択すると、そのProjectのFocusへ移動する
- Lowは一覧には含めるが、Focusには出さない
- Project未設定Taskは`All`にまとめる

### Tasks

- High「重要」とLow「あとで」を混ぜずに表示する
- 完了、元に戻す、High↔Low変更を行う

### Chat

- 選択中Taskを文脈としてPETITへ相談する
- 作業継続確認中にチャットへ返答した場合も、作業継続として扱う
- `classify_task_project`を使い、確認後にTaskを登録済みProjectへ分類する

## TaskのProject分類

Task詳細のProjectセレクトは、`GET /api/notifications/projects`で登録済みProjectを取得する。

- ローカルTaskは登録済み内部Projectへ移動できる
- Notion Taskは、確認済みNotion source linkを持つProjectだけ選択できる
- 選択後は既存`PATCH /api/notifications/tasks/{task_id}`へ`project_id`を送る
- SQLiteへ即時反映し、Notion Taskは既存Outboxで非同期同期する
- 未確認Notion Relationを名前だけで自動設定しない

## 作業セッション

タスクを選択しただけでは計測しない。詳細の「作業開始」を押した時だけ、既存の`/api/work-sessions`へ作業セッションを作る。

```text
選択中
  ↓ 作業開始
計測中
  ↓ 20分
継続確認
  ├─ 返答あり → 次の20分へ
  └─ 20分無応答 → 自動停止
```

新UIは次の操作を提供する。

- 作業開始
- まだ続ける
- 一時停止
- 再開
- 終了

セッションIDとactive task IDだけをlocalStorageへ保存し、開始時刻・一時停止時間・自動停止判定はSQLite上のサーバー状態を正とする。旧クライアント専用の`petit_universe_active_started_at`は使用しない。

## モーション設計

外部3Dライブラリを追加せず、CSSとVanilla JavaScriptで空間感を作る。

- 星雲の呼吸
- 軌道の低速回転
- Task nodeの段階的な出現
- 選択中Taskの明確な発光
- ビュー切替時の短い奥行きトランジション
- Pointerによる微細なparallax
- ピンチズーム
- `prefers-reduced-motion`時はアニメーションを停止

モバイルでは表示Node数を抑え、ズーム時だけ追加Nodeを見せる。

## API

```text
GET   /api/notifications/tasks?priority=all&limit=500
GET   /api/notifications/projects
PATCH /api/notifications/tasks/{task_id}
POST  /api/work-sessions/start
GET   /api/work-sessions/{session_id}
POST  /api/work-sessions/{session_id}/respond
POST  /api/work-sessions/{session_id}/pause
POST  /api/work-sessions/{session_id}/resume
POST  /api/work-sessions/{session_id}/end
```

`priority=all`はLife Universe専用で、未完了High / Mid / Medium / Low / 未設定を取得する。FocusとTasksは引き続きHigh／Lowの明示的な導線を使う。

## 非目標

- Objective / Actionの正式スキーマ移行
- 親Task Relationの可視化
- Three.jsや外部3Dライブラリ
- Project新規作成UI
- Done履歴の残光表示

現段階では既存のProject Relationを使い、`Life > Project > Task`の体験を先に確認する。

## 実機確認

- Project未設定Taskが`All`と表示される
- Task詳細からProjectを変更できる
- Notion未連携ProjectがNotion Taskの候補として選択できない
- チャットでTask分類を依頼し、確認後に反映される
- タスクを選ぶだけでは時間が増えない
- 作業開始後だけ時間が増える
- 再読み込み後も作業状態が復元される
- 20分後に継続確認が表示される
- 継続操作で次の20分へ進む
- 無応答時に自動停止する
- Focus内でProjectを前後移動できる
- ズーム段階で表示Task数が変わる
- iPhoneでピンチズームできる
- `prefers-reduced-motion`で不要な動きが止まる
