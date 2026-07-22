# Chat / Agent モデル切り替え

PETITのWeb画面上部にある `Chat:` と `Agent:` から、それぞれ別のモデル接続先を選択できます。

## 選択肢

| 選択肢 | 接続先 | 用途 |
|---|---|---|
| ローカル LM Studio | PC内のLM Studio | 外部へ内容を送りたくない会話 |
| DeepSeek V4 Flash | DeepSeek API | 普段使い・低コスト |
| DeepSeek V4 Pro | DeepSeek API | より精度が必要な分析 |

Chatは通常会話とルーター、Agentはツール実行・分析・自動要約などに使われます。

## `.env`設定

```env
# 起動時の初期値。Webで変更した選択はstorage/model_routing.jsonへ保存されます。
PETIT_CHAT_PROFILE=local
PETIT_AGENT_PROFILE=local

# ローカルプロファイル
PETIT_LOCAL_CHAT_BASE_URL=http://127.0.0.1:1234/v1
PETIT_LOCAL_CHAT_MODEL=qwen/qwen3.5-9b
PETIT_LOCAL_CHAT_API_KEY=lm-studio
PETIT_LOCAL_AGENT_BASE_URL=http://127.0.0.1:1234/v1
PETIT_LOCAL_AGENT_MODEL=qwen/qwen3.5-9b
PETIT_LOCAL_AGENT_API_KEY=lm-studio

# DeepSeekプロファイル
PETIT_DEEPSEEK_API_KEY=ここにAPIキー
PETIT_DEEPSEEK_BASE_URL=https://api.deepseek.com
PETIT_DEEPSEEK_FLASH_MODEL=deepseek-v4-flash
PETIT_DEEPSEEK_PRO_MODEL=deepseek-v4-pro
```

APIキーはサーバー側の環境変数からだけ読みます。Web API、HTML、保存ファイルにはAPIキーを返しません。

## API

### 現在の設定を取得

```http
GET /api/model-routing
```

### Chatだけ変更

```http
POST /api/model-routing
Content-Type: application/json

{"chat":"deepseek_flash"}
```

### Agentだけ変更

```http
POST /api/model-routing
Content-Type: application/json

{"agent":"deepseek_pro"}
```

APIキー未設定のDeepSeekプロファイルは選択できません。

## 保存と再起動

Webで変更した選択値だけを `storage/model_routing.json` に保存します。PETIT再起動後も同じ選択を使います。APIキー・URL・プロンプト・会話内容はこのファイルへ保存しません。

## DeepSeek利用時の注意

DeepSeekへ切り替えた経路では、その経路の回答生成に必要な会話履歴やツール結果が外部APIへ送信されます。BRAIN、Notion、Calendar、GitHubなどの結果をAgentが文章化する場合も同様です。

初期実装ではTool Callingの安定性を優先し、DeepSeekのThinkingを無効化しています。EmbeddingとAivisSpeechはこの切り替えの対象外で、従来どおりローカル接続を維持します。
