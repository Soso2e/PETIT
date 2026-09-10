# 「へいプティ」openWakeWord v0.1

Issue #258。AccessKey不要で `hey_petit.onnx` を作る、Windowsローカルの実験用学習環境。
Desktopのウェイク検出にローカルopenWakeWordランタイムを接続する。

## 構成

- Python 3.13、openWakeWord 0.6.0、ONNX Runtime CPU。アプリ本体のvenvとは別。
- openWakeWord公式v0.5.1の固定特徴抽出器（mel + speech embedding）を使用。
- 16フレーム × 96次元の特徴を標準化し、64ユニットのMLP分類器を学習。
- sklearnで学習した重みを標準ONNX演算へ書き出す。PyTorch/CUDA/WSLは不要。
- 上流の大規模学習レシピではなく、小規模な日本語試作用の分類ヘッド学習。

`scripts/wakeword/requirements.txt` は主要依存を固定する。実行環境の全依存は生成先の `requirements-lock.txt` へ保存する。

## 再実行（PowerShell 7 / Windows）

リポジトリルートで実行する。Windows PowerShell 5.1はOneCore音声の列挙が異なるため対象外。
日本語SAPI音声 Ayumi / Ichiro / Haruka / Sayaka が必要。不足時は明示エラーで止まる。
初回だけ公開パッケージと特徴抽出モデルをダウンロードする。合成・学習はローカルで行う。

```powershell
./scripts/wakeword/setup.ps1
./scripts/wakeword/synthesize.ps1
./storage/wakeword/.venv/Scripts/python.exe scripts/wakeword/train.py
./storage/wakeword/.venv/Scripts/python.exe -m pip freeze > storage/wakeword/models/v0.1/requirements-lock.txt
```

既存manifestやモデル出力先がある場合は上書きしない。再学習は出力先を変える。

```powershell
./storage/wakeword/.venv/Scripts/python.exe scripts/wakeword/train.py --output storage/wakeword/models/v0.1-rerun
```

## データと評価の意味

`corpus.json` に正例4表記と負例48文を定義。4音声 × 3話速で624個のWAVをローカル生成する。
「プティ」単独、「ねえプティ」、類似語、一般会話は負例。
学習はAyumi/Ichiro、しきい値調整はHaruka、最終評価はSayakaに固定し、データ拡張前に分離する。
同じ音声の速度違いを別話者として数えない。合成エンジン由来の偏りは残る。
学習側だけ音量・短い反響・白色雑音で拡張し、無音・雑音の負例も追加する。

`report.json` にデータ数、話者分離、しきい値候補、検出結果、変換誤差、警告、依存バージョン、SHA-256を保存する。
ONNX checker、sklearnとの出力一致に加え、実際の `openwakeword.Model.predict()` へ80msフレームを渡して評価する。
しきい値はvalidationのみで選ぶ。testは選択に使用しない。

合成音声の検出率と負例クリップ誤検出率は、人間の声の精度や1時間当たり誤起動回数を示さない。
実録音、距離、TV・音楽、長時間待機での評価は未実施。

## 成果物と実録音の検証

生成先: `storage/wakeword/models/v0.1/hey_petit.onnx`。
入力はPCMではなく `[batch, 16, 96]` の埋め込み、出力は `[batch, 1]` のスコア。
実運用では `storage/wakeword/backbone/melspectrogram.onnx` と `embedding_model.onnx` も必要。
`storage/wakeword/` 全体はGit管理外。モデルを渡す場合は分類器・2個の特徴抽出器・report・依存一覧をまとめて渡す。

ローカルの16kHz / mono / PCM16 WAVを検証する（マイクは自動で開かない）。

```powershell
./storage/wakeword/.venv/Scripts/python.exe scripts/wakeword/evaluate.py C:/audio/hey-petit.wav
```

本モデルとデータは個人ローカル実験用。合成音声、特徴抽出モデルを再配布・商用利用する前にそれぞれの利用条件を確認する。
openWakeWordコードのApache-2.0だけで全ての素材の権利が決まるわけではない。

## v0.1の実測（2026-09-09 UTC）

- 学習窓4,736件（正例960件）。しきい値0.45。
- validation: 合成正例12/12検出、合成負例10/144誤検出。
- test: 合成正例12/12検出、合成負例11/144誤検出（7.64%）。
- ONNX構造検証、sklearn出力との一致、openWakeWordでのストリーミング推論を確認。
- 数値型によるJSON保存の回帰と動的batchのONNX出力一致、計2テスト成功。依存整合・Python/PowerShell構文も確認。
- 誤検出が残るため常時待機の実用精度は未達。実声・実マイク・Desktop接続は未確認。

```powershell
./storage/wakeword/.venv/Scripts/python.exe scripts/wakeword/test_training.py
```

## 次の段階

1. ユーザーの実声で「へいプティ」、言い間違い、通常会話を録音し、学習に混ぜない評価セットを作る。
2. TV・音楽・生活音を含む長時間負例で誤起動回数を測り、しきい値・連続検出・VADを調整する。
3. 必要なら実音声・多様な背景音を学習へ追加して新バージョンを生成する。
4. 実声・長時間負例の評価を行い、しきい値を決める。

公式資料: [openWakeWord](https://github.com/dscripka/openWakeWord)、[言語対応](https://github.com/dscripka/openWakeWord#language-support)、[学習](https://github.com/dscripka/openWakeWord#training-new-models)。
