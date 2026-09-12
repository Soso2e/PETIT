# Wake model build staging

このディレクトリはDesktop installerへ `hey_petit.onnx` を注入するためのビルド用ステージです。

- `hey_petit.onnx` と `wake-model.json` はビルド時生成物でGit管理しません。
- ローカル開発では `storage/wakeword/models/v0.1/hey_petit.onnx` を自動検出します。
- Actions / Releaseでは `PETIT_WAKE_MODEL_URL` と `PETIT_WAKE_MODEL_SHA256` を指定します。
- URL配布時はSHA-256一致を必須とし、不一致ならinstaller buildを停止します。
