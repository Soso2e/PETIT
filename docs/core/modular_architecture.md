# PETIT Modular Architecture

Issue: #227

## 目的

PETITを、機能追加ごとに依存が広がる構造から、段階的に **Modular Monolith** へ移行する。

この文書は Phase 1 の設計正本として、`Core / Module / Integration / Client` の境界、依存方向、現状責務、最小Module Contractを定義する。

Phase 1では挙動を変更しない。フォルダ移動そのものではなく、今後の小さなrefactor PRが迷わないための境界を固定する。

---

## 1. 境界

### Core

PETIT全体の起動・構成・共通契約を扱う。

責務:

- FastAPI application生成
- Module Registryの構築
- Module lifecycleの開始・終了
- 共通Event / Permission / Dependency契約
- API Contractの公開

CoreはChat、TTS、Notion、Notificationsなど各機能の詳細実装を持たない。

### Module

PETIT自身が提供する機能単位。

例:

- Chat
- Tasks
- Projects
- Work Sessions
- Notifications
- Memory
- Voice
- Briefing

Moduleは必要に応じてRouter、Tool、Service、Health Check、startup/shutdown処理を提供する。

### Integration

PETIT外部のサービス・Provider・保存先との接続を担当するAdapter。

例:

- Notion
- GitHub
- BRAIN / Obsidian
- Linkraft
- Calendar
- LM Studio
- AivisSpeech

Integration停止時に、無関係なModuleまで停止しない構造を目標にする。

### Client

PETIT Coreを利用するUI / Platform。

例:

- Web / PWA
- Windows
- macOS
- iPhone

ClientにNotion tokenやGitHub tokenなどCore側の秘密情報を持たせない。

---

## 2. 依存方向

基本依存方向は次とする。

```text
Client
  ↓
API Contract
  ↓
Module
  ↓
Service / Domain
  ↓
Port
  ↓
Integration / Infrastructure
```

ルール:

1. ClientはCore内部実装を直接参照しない。
2. IntegrationはClient / UIを参照しない。
3. `main.py` / Composition Rootは各Moduleの内部実装を直接処理しない。
4. Module間の依存は必要最小限にし、可能なら公開Service / Event経由にする。
5. 外部Provider固有処理をModule本体へ広げない。
6. 既存API path / response contractはrefactor中も維持する。
7. 一括移行せず、Feature単位の小さなPRで進める。

---

## 3. 現状責務マップ

### `backend/main.py`

現在、Composition Root以外にも以下を直接担当している。

| 現在の責務 | 将来の所属候補 |
| --- | --- |
| FastAPI生成 | Core / Composition Root |
| notifications / work_sessions / shortcut_voice Router登録 | Core → Module Registry |
| DB初期化 | Infrastructure lifecycle |
| Chroma / Vault startup sync | Memory / BRAIN Module lifecycle |
| Scheduler起動停止 | Infrastructure または対象Module lifecycle |
| Worker起動停止 | Core / Infrastructure lifecycle |
| `/api/health` | System / Health Module |
| `/api/model-routing` | Model / LLM Integration Module |
| `/api/notion/webhook` | Notion Integration |
| `/api/tts*` | Voice Module |
| `/api/chat` | Chat Module |
| Pending Action管理 | Agent / Action Module |
| `/api/summarize`, `/api/summaries` | Memory Module |
| `/api/vault/sync` | BRAIN Integration |
| `/api/proactive` | Proactive / Briefing Module |
| `/api/briefing` | Briefing Module |
| `/api/calendar/sync` | Calendar Integration |
| `/api/conversations` | Chat / Conversation Module |
| `/api/jobs*` | Jobs / Runtime Module |
| Static frontend / service worker配信 | Web Client hosting |
| uvicorn起動 | Composition Root / entrypoint |

Phase 2ではこの表を基準に、依存の薄い責務からRouterへ移す。

### `backend/tools`

現状は `Tool` dataclassとRegistryを持っており、Tool名・schema・handler・riskを一元管理できている。

一方、built-in toolの登録は `backend/tools/__init__.py` が各moduleをimportする副作用に依存している。

Phase 3では既存Tool Registryを壊さず、明示的なModule registrationへ段階的に移行する。

---

## 4. 最小Module Contract

初期版では高度なPlugin Systemを作らない。

概念上、Moduleは次を提供できればよい。

```python
ModuleDefinition(
    id="notifications",
    routers=[router],
    tools=[...],
    health_checks=[...],
    startup=[...],
    shutdown=[...],
    dependencies=[...],
)
```

最小要素:

- `id`: 一意なModule名
- `routers`: FastAPI Router
- `tools`: Agentが利用可能なTool
- `health_checks`: Module / Integration状態確認
- `startup`: 起動時処理
- `shutdown`: 終了時処理
- `dependencies`: 必須Module / capability

初期実装では静的・明示的なRegistryとし、runtime install/uninstallは扱わない。

---

## 5. Composition Rootの目標

最終的に `backend/main.py` または `backend/app.py` は概ね次の責務だけを持つ。

```python
def create_app() -> FastAPI:
    app = FastAPI(...)
    modules = build_modules(settings)
    register_modules(app, modules)
    return app
```

Composition Rootが知ってよいもの:

- Settings
- Module一覧
- 共通Infrastructure
- application lifecycle

Composition Rootが知らないもの:

- Chat requestの処理内容
- AivisSpeechのレスポンス詳細
- Notion webhook署名検証詳細
- Chroma collection名
- Tool固有のconfirmation処理詳細

---

## 6. 段階移行ルール

- 1 PR = 1責務または1Moduleを基本にする。
- refactor PRでは原則としてAPI仕様・挙動を変更しない。
- 移動前後で既存テストを通す。
- 新構造と旧構造を一時共存させてもよい。
- 「最終フォルダ構成へ一気に合わせる」ことを目的にしない。
- 機能を外した際のGraceful Degradationを重視する。

成功例:

```text
Notion停止       → Local Task / Chatは動く
AivisSpeech停止  → Text Chatは動く
Notifications停止 → Tasks / Chatは動く
Web Client停止   → iPhone ClientからCoreは利用できる
```

---

## 7. 次のPR候補

Phase 2は `backend/main.py` から依存の薄いものを順に剥がす。

推奨順:

1. Health Router
2. TTS / Voice Router
3. Model Routing Router
4. Notion Webhook Router
5. Conversations / Summaries / Jobsなど補助API
6. Chat Router
7. Startup / Shutdown lifecycle

Chatとlifecycleは依存範囲が広いため後半に回す。

---

## Phase 1 完了条件

- [x] Core / Module / Integration / Client の責務を定義
- [x] Dependency方向を定義
- [x] `backend/main.py`の現在責務を分類
- [x] Tool Registryの現状と移行方針を記録
- [x] 最小Module Contractを定義
- [x] Composition Rootの責務を定義
- [x] Phase 2の安全な移行順を決定

次はコードを動かすPhase 2へ進む。