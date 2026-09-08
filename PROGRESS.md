# PROGRESS — 変更履歴

**Current Version: v0.20.0**

**Last Updated: 2026-09-08**

## 現在の状態 / 未確認・TODO（最新を上書き）

履歴表が持てない「いま開いている状態」だけをここに書く。最新内容で上書いてよい。

- Issue #253: Windows/macOS向けElectron Desktopの初期実装。既存Webの会話・確認・TTSを共有する小型UI、トレイ・ショートカット、任意Porcupineウェイク、Whisper互換STT、GitHub Releases更新通知を追加。macOSの実Electronと生成音声の操作テスト済み。実マイク/モデル/LLM/TTS、Windows実機、署名・公証・実更新は未確認。iPhoneはPWAを継続。Desktop配布はPR=テストのみ、手動Actions=macOS arm64/Windows x64開発Artifact、main上のversion一致`v*`タグ=両OSビルド＋GitHub Release自動添付へ整理。未署名中は手動Artifactで検証し、公開タグは切らない。既存Core CI相当はTool Registry未初期化と旧Prompt前提の失敗が別途残るため、PRはDraftで提出する。
