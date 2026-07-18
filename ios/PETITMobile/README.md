# PETIT Mobile — Phase 1 Text MVP

Tailscale Serve経由でPETIT FastAPIへ接続する、iPhone向けSwiftUIテキストクライアントです。

## 現在の範囲

- Tailscale ServeのHTTPS URL保存
- `GET /api/health`による接続確認
- `POST /api/chat`によるテキストチャット
- `session_id`と会話履歴の送信
- 使用ツール表示
- Pending Actionの実行／キャンセル
- 通信エラー表示

音声認識、読み上げ、App Intents、通知は次のPhaseで追加します。

## 必要なもの

- macOSとXcode
- XcodeGen
- Phase 0が完了したPETIT
- `tailscale serve status`に表示されるHTTPS URL

XcodeGenは`project.yml`からXcodeプロジェクトを生成します。

```bash
brew install xcodegen
cd ios/PETITMobile
xcodegen generate
open PETITMobile.xcodeproj
```

## 実機起動

1. XcodeでPETITMobileターゲットを選択する。
2. Signing & Capabilitiesで自分のTeamを選択する。
3. 接続済みiPhoneを実行先に選ぶ。
4. Runする。
5. 歯車からTailscale ServeのHTTPS URLを入力する。
6. `PETIT接続OK`を確認してメッセージを送る。

URL例:

```text
https://petit-pc.example.ts.net
```

秘密情報はiPhoneへコピーしません。PETITのNotionキー、GitHubトークン、LM Studio設定はPC側に残します。

## 検証項目

- [ ] XcodeGenでプロジェクト生成
- [ ] Simulator build
- [ ] Unit Test
- [ ] iPhone実機build
- [ ] Tailscale URLで`/api/health`成功
- [ ] テキストチャット往復
- [ ] Pending Actionの実行
- [ ] Pending Actionのキャンセル
- [ ] Tailscale切断時のエラー表示
