# PETIT ドキュメント一覧

## どこに何があるか

| 知りたいこと | 正本 |
| --- | --- |
| 何を目指すか・判断基準 | [../Concept.md](../Concept.md) |
| いまどう実装されているか（概要） | [architecture.md](architecture.md) |
| 会話処理・Tool実行の実装フロー | [runtime-flows.md](runtime-flows.md)（Mermaid。実装を変えたら同じ変更で更新する） |
| 用語の意味 | [terminology.md](terminology.md) |
| 現在地・未確認・変更履歴 | [../PROGRESS.md](../PROGRESS.md) |
| 開発ルール | [../AGENTS.md](../AGENTS.md) |

## 配置ルール

- 新しい文書は、下の分野フォルダのどれかに置く。どれにも当てはまらないときは、フォルダを増やす前に Issue で相談する。
- 1つの機能につき1文書を基本とし、バージョンごとの作業メモは新しく作らず、その機能の文書を更新する。
- 文書の冒頭に `Status:`（目標 / 現行 / 調査 / アーカイブ）と関連Issueを書く。
- 古くなった文書は消さずに `archive/` へ移し、冒頭に後継の文書へのリンクを書く。
- 実装済みと未実装・未確認を混ぜない。目標を書くときは「目標」「未実装」と明記する。

## 分野別の一覧

### 構想・ビジョン（`vision/`）

目指す体験像。目標の正本は ../Concept.md

- [petit-identity.md](vision/petit-identity.md) — PETIT Identity
- [petit-renaissance-vision.md](vision/petit-renaissance-vision.md) — PETIT Renaissance — Vision & Experience

### Core（会話・状態・記憶）（`core/`）

Thread/Turn、Context Broker、会話状態、記憶、バックグラウンド処理

- [ai-first-agent-design.md](core/ai-first-agent-design.md) — AI-First Agent Architecture — 調査・比較PoC（#338）（DeepSeek中心の比較PoC。現行方針は ../Concept.md §4）
- [assistant-architecture.md](core/assistant-architecture.md) — PETIT Assistant Architecture
- [conversation-action-reliability.md](core/conversation-action-reliability.md) — Conversation-to-Action Reliability — 初回修正（#335）
- [conversation-state.md](core/conversation-state.md) — Conversation State
- [CORE_HARDENING_VALIDATION.md](core/CORE_HARDENING_VALIDATION.md) — PETIT Core Hardening Validation
- [dialogue-state-acceptance.md](core/dialogue-state-acceptance.md) — Dialogue State #294 受入記録
- [durable-read-tasks.md](core/durable-read-tasks.md) — #372 P0 — 永続Read Task（段階導入）
- [jarvis-agent.md](core/jarvis-agent.md) — PETITを共通Coreの常駐パーソナルエージェントへ
- [modular_architecture.md](core/modular_architecture.md) — PETIT Modular Architecture
- [renaissance-core.md](core/renaissance-core.md) — PETIT Renaissance Core
- [renaissance-memory.md](core/renaissance-memory.md) — 元発言検索と長期記憶

### Brain（AI・CLI接続）（`brain/`）

Brainの選択、CLI（Antigravity / Codex / Claude Code）接続、モデル切り替え

- [antigravity-brain-poc.md](brain/antigravity-brain-poc.md) — 公式Antigravity SDK Brain — Refs #349（SDKは撤去済み。履歴として保持）
- [agent-home.md](brain/agent-home.md) — PETIT Home：CLIを自立した作業者へ（方針承認済み・未実装）
- [antigravity-cli.md](brain/antigravity-cli.md) — Antigravity CLIと既存契約枠（#355 / #349）
- [claude-code-cli.md](brain/claude-code-cli.md) — Claude Code CLI Executor（v0.44.0）
- [front-brain-delegation.md](brain/front-brain-delegation.md) — Front Brain と CLI 委譲（v0.50.0・試験機能・実 CLI 未確認）
- [model_route_switcher.md](brain/model_route_switcher.md) — Chat / Agent モデル切り替え
- [persistent-agent-workspace.md](brain/persistent-agent-workspace.md) — #368 Persistent Agent Workspace / compact tools
- [sdk-retirement.md](brain/sdk-retirement.md) — #368 SDK撤去とProvider共通境界

### 生活・タスク・予定・記録（`life/`）

タスク、Notion、予定、リマインダー、作業記録

- [brain_project_mapping.md](life/brain_project_mapping.md) — BRAIN Project Mapping
- [daily_life_index.md](life/daily_life_index.md) — 日次生活インデックス
- [generic_lists.md](life/generic_lists.md) — 汎用リスト管理
- [google_calendar_push.md](life/google_calendar_push.md) — TimeTree → Google Calendar 同期
- [mobile_work_companion.md](life/mobile_work_companion.md) — スマホ向け制作伴走モード
- [notion-daily-sync.md](life/notion-daily-sync.md) — PETIT Notion Daily Sync (Renaissance)
- [notion_adapter_v2.md](life/notion_adapter_v2.md) — Notion Adapter v2
- [notion_search.md](life/notion_search.md) — Notion会話検索
- [notion_task_live_sync.md](life/notion_task_live_sync.md) — Notionタスクのローカルファースト双方向同期
- [reminders.md](life/reminders.md) — PETIT リマインダー
- [task_conversation_flow.md](life/task_conversation_flow.md) — タスクの追加・完了会話と優先度順
- [task_schedule_management_v1.md](life/task_schedule_management_v1.md) — PETIT タスク・スケジュール管理 v1
- [task_status_handling.md](life/task_status_handling.md) — タスク状態の取得と出力
- [work-statistics.md](life/work-statistics.md) — 作業統計 / v0.28.0

### 開発の司令塔（`dev/`）

Coding Job、ローカル開発の観測、Project、GitHub

- [coding-tasks.md](dev/coding-tasks.md) — CLIによるローカル開発タスク（#225 / #362）
- [github_daily_review.md](dev/github_daily_review.md) — GitHub Daily Review
- [github_evidence.md](dev/github_evidence.md) — GitHub Project Evidence
- [local-development-insight.md](dev/local-development-insight.md) — ローカル開発環境の読取（Issue #341 / Phase 1）
- [project-workspaces.md](dev/project-workspaces.md) — Projectとローカル開発フォルダ

### Desktop（`desktop/`）

Electron版、配布、PC観測

- [desktop-foundation-design.md](desktop/desktop-foundation-design.md) — PETIT Desktop・共通Core 基盤設計
- [desktop-notification-diagnostics.md](desktop/desktop-notification-diagnostics.md) — Mac Desktop通知の切り分け（#329）
- [desktop-readiness.md](desktop/desktop-readiness.md) — PETIT Desktop 完成・受入台帳
- [desktop.md](desktop/desktop.md) — PETIT Desktop — 段階導入設計
- [jarvis-workspace-agent.md](desktop/jarvis-workspace-agent.md) — 任意拡張: PCの作業環境を理解するPETIT
- [macos-distribution.md](desktop/macos-distribution.md) — macOS配布・署名検証（#309）

### 音声（`voice/`）

音声会話、ウェイクワード、読み上げ

- [aivis_speech.md](voice/aivis_speech.md) — AivisSpeech読み上げ
- [ios_vocal_shortcut.md](voice/ios_vocal_shortcut.md) — 「へいプティ」iOS Vocal Shortcut 仮導線
- [openwakeword.md](voice/openwakeword.md) — 「へいプティ」openWakeWord v0.1
- [voice_mode.md](voice/voice_mode.md) — PETIT 音声モード（Phase 1–2）
- [voice_task_interaction.md](voice/voice_task_interaction.md) — 音声タスク操作と省トークン化

### UI（`ui/`）

画面構成、Universe、モーション

- [agent_first_ui.md](ui/agent_first_ui.md) — Agent-first会話とWeb UI操作面
- [galactic-spatial-design.md](ui/galactic-spatial-design.md) — PETIT Galactic Spatial Design v0.9.0
- [motion-continuity.md](ui/motion-continuity.md) — PETIT Motion Continuity v0.8.0
- [ui-chat-first-dashboard.md](ui/ui-chat-first-dashboard.md) — PETIT v0.41.0 — Chat-first UI / Dashboard
- [ui-system.md](ui/ui-system.md) — PETIT UI System v0.25.0
- [universe-motion.md](ui/universe-motion.md) — UnivのThree.jsアニメーション
- [universe_focus_orbit.md](ui/universe_focus_orbit.md) — PETIT Universe — Life / Task / Child Task

### 入口・通知（`channels/`）

iPhone / PWA、Discord、画像、Web Push、接続ステータス

- [app-notification-unification.md](channels/app-notification-unification.md) — Webアプリ構造と通知・会話継続の統一
- [connection-status.md](channels/connection-status.md) — 接続ステータス（#327）
- [discord-bot.md](channels/discord-bot.md) — Discord Bot：本人専用モードとGuildプロジェクトモード（方針承認済み・未実装）
- [iphone_phase0_tailscale.md](channels/iphone_phase0_tailscale.md) — iPhone Phase 0: Tailscale Serve
- [multimodal-acceptance.md](channels/multimodal-acceptance.md) — Multimodal / Discord 受入セット
- [multimodal-discord-plan.md](channels/multimodal-discord-plan.md) — Multimodal Intelligence / Discord 計画
- [web_push_notifications.md](channels/web_push_notifications.md) — Web Push通知

### セットアップ・運用（`ops/`）

初期設定、連携の撤去手順

- [integration-removal.md](ops/integration-removal.md) — Sona Core / Linkraft integration removal (v0.34.3, Issue #363)
- [setup-integrations.md](ops/setup-integrations.md) — 初期セットアップ・接続管理（v0.34.0 / #353）

### アーカイブ（`archive/`）

過去のバージョン別メモと旧Concept。現行の判断には使わない

- [contextual_agent_runtime.md](archive/contextual_agent_runtime.md) — 文脈駆動Agent Runtime（v0.45.0で撤去）
- [project_source_refresh.md](archive/project_source_refresh.md) — Project Source Refresh（v0.45.0で撤去）
- [runtime-flows-legacy-routing.md](archive/runtime-flows-legacy-routing.md) — 旧キーワードルーティングの実装フロー（v0.45.0で撤去）
- [concept-legacy.md](archive/concept-legacy.md) — Personal AI Assistant 開発方針
- [desktop-v26-experience.md](archive/desktop-v26-experience.md) — Desktop v0.26.0 — 日常利用の修正と声かけ設計
- [desktop-v27-experience.md](archive/desktop-v27-experience.md) — Desktop / Web v0.27.0
- [desktop-v28-ux.md](archive/desktop-v28-ux.md) — Desktop / Web v0.28.0：作業開始と振り返り
- [v27-ux-followup.md](archive/v27-ux-followup.md) — v27 実操作でのUX課題
