# iPhone Phase 0: Tailscale Serve

PETITを変更せず、Windows PC上の`127.0.0.1:8000`を自分のTailscaleネットワーク内だけへHTTPS公開する手順です。

## 完成状態

```text
iPhone Safari
  ↓ HTTPS / Tailscale
Tailscale Serve
  ↓ localhost
PETIT FastAPI (127.0.0.1:8000)
  ↓
LM Studio / configured API
```

- ルーターのポート開放は不要です。
- `PETIT_HOST=0.0.0.0`への変更は不要です。
- Windows Firewallで8000番を外部公開する必要はありません。
- 一般インターネットへ公開するTailscale Funnelは使用しません。

## 1. Tailscaleを入れる

次の2台へTailscaleをインストールし、同じアカウントでログインします。

- PETITを動かすWindows PC
- iPhone

WindowsとiPhoneの両方でTailscaleが接続済みになっていることを確認してください。

## 2. PETITを通常どおり起動する

LM Studioを使う場合は、先にLM Studioのサーバーとモデルを起動します。

PETITリポジトリのルートで実行します。

```powershell
python -m backend.main
```

PCのブラウザで次を開き、PETITが動いていることを確認します。

```text
http://127.0.0.1:8000
```

## 3. Tailscale Serveを開始する

別の「管理者として実行したPowerShell」で、PETITリポジトリのルートへ移動して実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\tailscale-serve.ps1 start
```

初回のみ、Tailscale Serveを有効にするためのURLが表示される場合があります。そのURLをブラウザで開いて有効化し、同じコマンドをもう一度実行してください。

成功すると、次のようなTailscale内専用URLが表示されます。

```text
https://<PC名>.<tailnet名>.ts.net
```

## 4. iPhoneから開く

1. iPhoneでTailscaleを接続状態にします。
2. Safariで表示された`https://...ts.net`を開きます。
3. PETITへテキストを送り、返答が来ることを確認します。
4. Wi-Fiを切ってモバイル回線でも同じURLが開けることを確認します。
5. Safariの共有メニューから「ホーム画面に追加」します。

## 5. 状態確認と停止

状態確認:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\tailscale-serve.ps1 status
```

停止:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\tailscale-serve.ps1 stop
```

`stop`は、このPCに設定されているTailscale Serve設定をリセットします。

## Phase 0の確認項目

- [ ] PC上の`http://127.0.0.1:8000/api/health`が応答する
- [ ] iPhoneのSafariでPETIT画面が開く
- [ ] iPhoneからチャットを送信できる
- [ ] 予定・タスク・BRAIN検索を試せる
- [ ] 書き込み操作の実行・キャンセルが動く
- [ ] Wi-Fiを切ったモバイル回線でも使える
- [ ] Tailscaleを切るとアクセスできなくなる

## セキュリティ上の注意

このPhase 0では、Tailscaleのtailnet自体をアクセス境界として使います。個人用tailnetに自分の端末だけが参加している前提です。

- Funnelへ切り替えないでください。
- 発行されたURLを公開しないでください。
- tailnetへ他人を招待する場合は、PETIT側の端末認証またはBearer Token認証を追加してから運用してください。
- Notion、GitHub、LM APIなどの秘密情報をiPhoneへコピーする必要はありません。

## トラブルシューティング

### PETITに接続できない

PCで次を確認します。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

失敗する場合は、PETITまたはLM Studioの起動状態を確認してください。

### `tailscale`コマンドが見つからない

Tailscaleをインストール後、PowerShellを開き直してください。それでも見つからない場合はWindowsを再起動します。

### 管理者権限エラー

PowerShellを右クリックし、「管理者として実行」してから再実行します。

### iPhoneでURLが開けない

- iPhoneのTailscaleが接続済みか確認する
- Windows PCのTailscaleが接続済みか確認する
- `tailscale serve status`でURLと転送先を確認する
- PCがスリープしていないか確認する
