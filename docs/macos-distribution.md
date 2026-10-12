# macOS配布・署名検証（#309）

## v0.24.0の原因

2026-10-12、macOS 26.6.2 / arm64で確認。
公開元: `v0.24.0` / `4d57bf4ef0d47b1c75f9c2e5fd5840032085df34`。
[公開ビルドログ](https://github.com/Soso2e/PETIT/actions/runs/37426898433)では、資格情報不足後に`CSC_IDENTITY_AUTO_DISCOVERY=false`で署名をスキップしてDMGを作成していた。

- 公開DMGのSHA-256: `814fd7760af440a17b2d4d5942cbb705d30d18f3f37535c366176623df5fb810`。`hdiutil verify`成功。
- DMG内と`/Applications/PETIT.app`はともに`code has no resources but signature indicates they must be present`。
- 元のElectron実行ファイルも`Identifier=Electron`、`adhoc,linker-signed`、`Info.plist=not bound`、`Sealed Resources=none`。製品アプリの署名工程を通っていない。
- 呼び出し順はモデル準備 → Electron展開/名称・Info.plist変更 → app.asar/extraResources配置 → 署名（旧公開処理ではスキップ）→ DMG作成 → blockmap生成 → upload。
- PETIT独自の署名後変更hookはなかった。旧配布物について、正しく署名されたアプリを後で書き換えた証拠はない。確認できた直接原因は署名スキップ。

## 修正後の順序

1. モデルを準備し、アプリの全リソースを配置する。
2. 開発用は明示的に`mac.identity=-`でアプリ/入れ子バイナリをad-hoc署名する。開発用のみHardened Runtimeを無効にする。正式配布はDeveloper ID Application、Hardened Runtime、公証を使用する。
3. `afterSign`で`codesign --verify --deep --strict`とCodeResourcesの存在を確認し、全ファイルのSHA-256・パーミッション・symlink先を記録する。正式版はアプリ公証/stapleの後にこのhookが呼ばれる。
4. DMG完成後、`afterAllArtifactBuild`で署名と署名直後の内容一致を再確認する。DMGを`hdiutil verify`し、読み取り専用でmountして内部アプリも検証・比較する。署名スキップや変更はビルド失敗にする。
5. 正式版ではDMG自体も署名し、`notarytool submit --wait`、staple、stapler validate、hdiutil verify、Gatekeeper評価を通してからuploadする。

`npm run build:mac:development`で作成するDMGは`development`付きの名前になる。ad-hoc署名は内容の整合性検証用であり、Developer ID署名/公証の代わりにはならない。

任意の生成物を再検証:

```bash
cd desktop
node scripts/verify-mac-package.cjs dist/mac-arm64/PETIT.app dist/PETIT-VERSION-development-mac-arm64.dmg
```

## 再作成・実機確認結果

v0.24.0を別領域へ`git archive`で復元し、ビルド設定/検証hookだけを適用。アプリの機能ソースとversionは維持した。

- `PETIT-0.24.0-development-mac-arm64.dmg`を再作成。
- SHA-256: `3fb26d656240d603228244016f19c2f4450d92e9c477a5101b4aca91253ee7bc`。
- 保存先: `desktop/dist/rebuilt-0.24.0/`（Git管理外）。現行v0.25.1の開発用DMGも`desktop/dist/`へ生成。
- 両ビルドとも署名直後/DMG完成後/DMG内の署名検証とファイル内容一致に成功。同梱リソース検証成功。Wakeモデルは未同梱。
- 再作成アプリ: `Identifier=jp.soso2e.petit`、`Signature=adhoc`、`Sealed Resources version=2`。TeamIdentifierはない。
- Desktopテスト53件成功。実codesignを使い、署名後のリソース変更が拒否され、再署名で整合性を復旧しても署名直後snapshotとの相違が拒否される回帰テストを含む。workflow YAML読込・構文・diff検査成功。
- Safariでloopback HTTPから実際にDMGをダウンロード。配信元とダウンロード先のSHA-256が一致。DMGの隔離属性は`0083;...;Safari;...`。
- DMGから`~/Downloads/PETIT-signature-test-309/PETIT.app`へ`ditto`でコピーし、隔離属性`0283;...`が保持されていることを確認。コピー先のcodesign検証成功、`spctl --assess --type execute`は`rejected`。
- Finderから通常起動を試行。ユーザー実機表示は「Appleは、“PETIT”にMacに損害を与えたり、プライバシーを侵害する可能性のあるマルウェアが含まれていないことを検証できませんでした」。未公証による拒否であり、起動成功には至っていない。
- 隔離属性削除、Gatekeeper無効化、警告の回避は行っていない。既存`/Applications/PETIT.app`とユーザーデータは変更していない。公開Releaseの差し替えは未実施。

## 正式配布に必要な準備

確認時、`security find-identity -v -p codesigning`は有効identity 0件、`gh secret list`は登録なし。`notarytool`と`stapler`はローカルで利用可能だが、署名/公証の資格情報がない。

1. Apple Developer Programのアカウントで **Developer ID Application** 証明書を発行し、対応する秘密鍵とともにKeychainへ登録する。[Appleの証明書発行手順](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)
2. 証明書と秘密鍵をパスワード付き`.p12`として書き出し、GitHub Actions Secretsへ`MAC_CSC_LINK`（p12のbase64等）と`MAC_CSC_KEY_PASSWORD`を登録する。証明書/秘密鍵はリポジトリへ保存しない。
3. 公証用の`APPLE_ID`、`APPLE_APP_SPECIFIC_PASSWORD`、`APPLE_TEAM_ID`もSecretsへ登録する。現在のworkflowはこの5項目を必須にする。[Appleの公証ガイド](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
4. 修正をPRでmainへ反映する際はプロジェクト規約に従いversionを更新する。正式ビルド・アプリ/DMG公証・staple・Gatekeeper検証を実施する。
5. 公証済みDMGをブラウザでダウンロードし、隔離属性を保持してApplicationsへインストール、通常起動と設定画面まで確認する。証明書不足のため、この成功確認は未完了。

v0.24.0のad-hoc再作成物は開発検証用で、正式な置換配布物として公開しない。正式配布の受入完了までは#309を完了扱いにしない。
