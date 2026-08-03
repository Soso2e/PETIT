# PETIT Galactic Spatial Design v0.9.0

## 目的

PETIT全体を、画面ごとに別々の宇宙表現を持つUIではなく、同じ銀河空間の中で距離と情報密度だけが変わるプロダクトとして統一する。

派手な発光や長い演出ではなく、深い背景、静かな光、面の重なり、余白、文字階層、操作位置で宇宙らしさを作る。

## モーション

- Life→Focusを含む全View切替は約220msの短いフェードと5pxのY移動
- 共有要素Ghost、拡大、奥行き移動、blur、専用Portalは使用しない
- タブインジケーターと完了フィードバックだけを残す
- `prefers-reduced-motion`ではViewアニメーションを無効化する

## 画面構成

### Life

- 絶対配置された惑星群をCSS上で解除
- PCは3列、タブレットは2列、スマホは1列
- 各Projectを星系カードとして扱い、Taskをカード内の航路一覧として表示
- Task数が増えても重なりや画面外配置が発生しない

### Focus

- Orbitを中央作業空間として維持
- Project切替、Zoom、作業状態を同一パネル内で整理
- PCでは右側にTask詳細
- 1180px以下では詳細を下へ移し、stickyを解除
- スマホではOrbit、作業操作、詳細の順に自然にスクロールする

### Tasks

- PCは一覧性を優先したTable
- スマホはHeaderを隠し、TaskごとのCardへ変換
- 完了、名前、同期、期限、親Taskの優先順位を固定する

### Today / Remind / Chat

- 共通Surface、角丸、境界、余白を使用
- Chatは通信パネルとして本文とContextを分離
- スマホでは1カラム化し、Composerを下部ナビより上へsticky配置

## レスポンシブ

- `1180px`: Focus / Chatを1カラム化
- `720px`: 下部ナビ、2x2 Context、全画面モバイル構成
- `390px`: Orbit・切替Control・余白をさらに圧縮
- `safe-area-inset-top/bottom`をHeader、Navigation、Composerで考慮

## 実機確認

- PC実データ
- 390x844
- iPhone PWA
- ソフトウェアキーボード表示中
- ライトテーマ
- 低電力モード
- 長時間Orbit表示
