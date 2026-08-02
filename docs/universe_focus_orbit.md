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

## ビューの役割

### Focus

- 選択中Projectを中央に置く
- そのProjectの未完了Highタスクだけを軌道へ表示する
- Projectセレクトと前後ボタンでFocus内からProjectを移動できる
- `Life › Project`のパンくずから全体へ戻れる
- タスクの選択と作業開始を分離する

### Universe

- Life配下のProjectを縦に一覧表示する
- Project内の未完了High / Mid / Lowタスクを優先度順に表示する
- ProjectまたはTaskを選択すると、そのProjectのFocusへ移動する
- Lowは一覧には含めるが、Focusには出さない

### Tasks

- High「重要」とLow「あとで」を混ぜずに表示する
- 完了、元に戻す、High↔Low変更を行う

### Chat

- 選択中Taskを文脈としてPETITへ相談する
- 作業継続確認中にチャットへ返答した場合も、作業継続として扱う

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

## API

```text
GET  /api/notifications/tasks?priority=all&limit=500
POST /api/work-sessions/start
GET  /api/work-sessions/{session_id}
POST /api/work-sessions/{session_id}/respond
POST /api/work-sessions/{session_id}/pause
POST /api/work-sessions/{session_id}/resume
POST /api/work-sessions/{session_id}/end
```

`priority=all`はLife Universe専用で、未完了High / Mid / Medium / Low / 未設定を取得する。FocusとTasksは引き続きHigh／Lowの明示的な導線を使う。

## 非目標

- Objective / Actionの正式スキーマ移行
- 親Task Relationの可視化
- Three.jsや外部3Dライブラリ
- ドラッグによるProject変更
- Done履歴の残光表示

現段階では既存のProject Relationを使い、`Life > Project > Task`の体験を先に確認する。

## 実機確認

- タスクを選ぶだけでは時間が増えない
- 作業開始後だけ時間が増える
- 再読み込み後も作業状態が復元される
- 20分後に継続確認が表示される
- 継続操作で次の20分へ進む
- 無応答時に自動停止する
- Focus内でProjectを前後移動できる
- UniverseからProject／Taskを選んでFocusへ移動できる
- UniverseにMid／Lowを含む全未完了タスクがProject別に並ぶ
- iPhone PWAでProjectセレクトと作業操作が押せる
