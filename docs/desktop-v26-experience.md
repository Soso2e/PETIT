# Desktop v0.26.0 — 日常利用の修正と声かけ設計

Issue #315 / ブランチ `Fix/v26`（未公開）。新しい通知/競合APIにはv0.26.0のサーバーも必要。コードと隔離環境の検証結果を実機受入と区別する。

## 実装した体験

| 場面 | 操作と結果 |
| --- | --- |
| Windows更新 | 設定/トレイの更新確認 → 同意 → ダウンロード進捗 → GitHub assetのサイズ・SHA-256検証 → installer起動 → PETIT終了。最後のインストール確認はinstallerで行う。Windows x64インストール版のみ。 |
| macOS更新 | ReleaseのDMGを手動取得。未公証/ad-hoc配布の自己更新は未実装。 |
| 作業中の星 | 選択中とは独立して、サーバーWork Sessionのtask_idに対応する星を強調。2Dは輪郭・光・作業中表示、3Dは1.32倍の大きさと発光・ラベル。停止/一時停止/自由入力作業では強調を解除。 |
| テキスト入力 | IME確定Enterとキー長押しでは送信しない。Shift+Enterで改行。送信待機中の再送を防ぎ、各画面の上限まで伸長、復元後も高さを再計算。 |
| 同期競合 | バージョン横の競合表示、Tasksの「同期競合を確認」、タスクの競合ボタンから比較。PETIT側の未同期変更を再送するか、Notion側を採用して未同期変更を取り下げるか選ぶ。 |
| Desktop通知 | Web Push購読・VAPID・pywebpush不要。Desktop設定でOFF/ONと「画面のすみに声かけ」「OS通知」を選び、作業画面Settingsでカテゴリを選ぶ。 |

同期競合の比較はNotion最新取得を使う。選択時にDB・キュー・Notionの比較revisionが違えば409として再比較する。Notion側採用では過去payloadを保持し、取り下げたキューを`superseded`にする。PETIT側採用は`pending`へ戻すだけで、Notion反映成功とは表示しない。実行直前にもNotion更新日時を照合し、再更新は再競合とする。Notion APIには条件付き更新の契約がないため、GETからPATCHの間の外部変更を完全に原子的に防ぐものではない。

404/権限不足は競合を消さない。対象/親ページの存在、ゴミ箱、Notion連携への共有を確認する。UIが外部サービスの共有権限を変更することはない。PETIT側採用で再同期後に親ページ404が出た場合も、failedとして理由を残す。

## そばにいる体験の方針

主役はユーザーの作業。通常は静かに存在し、必要な時だけ短い声かけを出す。

- 画面のすみのカードはフォーカスを奪わず12秒で消える。ホバー中は残し、「PETITを開く」で作業画面へ戻る。
- ロック/スリープ中は表示しない。初回ON時の過去通知、2分以上古い通知、既読/解決済み通知、OFFのカテゴリは表示しない。
- Desktop Mainが15秒ごとに通知イベントを取得し、接続先ごとのcursorを端末へ保存する。小型画面を閉じても動作する。アプリ終了・Core停止・オフライン中は受信しない。
- OS通知は音を鳴らさず、実際の表示はOS許可/集中モード/署名状態に依存する。通知テストは「表示要求」と表現し、受信成功を断定しない。
- カードを開いても通知を自動解決しない。全通知の履歴と対応は作業画面へ残す。現在は個別タスクへのDesktop deep linkではなく作業画面を開く。
- 既存の作業継続確認は20分のまま。「25分たったよ」は次の設定可能なFocus intervalとして検討する。

## 次の設計・実装

1. 作業継続間隔を20/25/50分から選べるようにし、続ける/休む/終了をカードから返せる。Work Session正本へ同じ操作を送る。
2. 音声の声かけは独立した明示ON設定にする。ユーザーの入力・録音・TTS・通話・プレゼン中は待つ。発話は「25分たったよ。少し休む？」程度の短文にし、返答を待っても勝手にマイクを開かない。
3. 「後で」「今は静かに」を短時間の抑制へ反映する。同じイベントをOS通知・カード・音声の全経路から同時に出さない。
4. Desktop/Coreの状態契約（#302〜#305）を進め、同一URLでもCoreが変わった時のcursorをcore_idへ移行する。現状はorigin単位で、同じURLに別DBを差し替えた場合は通知OFF→ONでbaselineを取り直す。

## 受入の境界

自動回帰: 比較後の変更/404/重複選択、キュー停止/再競合、通知baseline/カテゴリ/古さ/解除、更新ファイル改ざん/サイズ不一致、関連既存機能。

隔離Electron確認済み: 入力のIME/長押し/伸長、声かけカード、会話/承認/合成音声/復旧/IPC分離、作業星のDOM状態/一時停止/選択、競合比較、VAPID未設定でDesktop通知ON/OFF。実データや実マイクは使用しない。3D発光の実機での見え方は未確認。

Windows x64 NSISを生成し、新しい通知画面・Main modulesの同梱検証に成功。ローカル検証installerは `desktop/dist/PETIT-0.26.0-win-x64.exe`（未署名）。稼働中のWeb PushはVAPID/購読が存在する一方でpywebpush依存が不足していた。既存requirementsにあるpywebpushをプロジェクトvenvへ導入し、再起動なしでAPIの`dependency_available=true`、import、pip checkを確認。実端末への送信/受信は未確認。

実機で残る確認: 旧配布版から新Releaseへのインストール更新、Windows/macOSのOS通知、長時間常駐・複数画面、実Notion採用・404復旧、実IMEの操作感、実LLM/STT/TTS。今回Release/Push/PRは行わない。

参考: [Electron通知](https://www.electronjs.org/docs/latest/tutorial/notifications)、[Electron更新](https://www.electronjs.org/docs/latest/tutorial/updates)、[GitHub asset digest](https://docs.github.com/en/rest/releases/assets)。
