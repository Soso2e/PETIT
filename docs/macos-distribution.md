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
2. 開発用・個人利用Releaseともに明示的に`mac.identity=-`でアプリ/入れ子バイナリをad-hoc署名し、Hardened Runtimeを無効にする。Apple Developer Program・公証は使用しない。
3. `afterSign`で`codesign --verify --deep --strict`とCodeResourcesの存在を確認し、全ファイルのSHA-256・パーミッション・symlink先を記録する。
4. DMG完成後、`afterAllArtifactBuild`で署名と署名直後の内容一致を再確認する。DMGを`hdiutil verify`し、読み取り専用でmountして内部アプリも検証・比較する。署名スキップや変更はビルド失敗にする。
5. タグReleaseでもad-hoc署名のアプリ/DMG内容検証を通してからuploadする。DMGのApple公証、staple、Gatekeeper許可は行わない（個人利用限定）。

`npm run build:mac:development`で作成するDMGは`development`付きの名前、タグReleaseで利用する`npm run build:mac:personal`では通常の`PETIT-<version>-mac-arm64.dmg`になる。どちらもad-hoc署名であり、Appleによる開発者検証・公証やGatekeeperでの通常起動許可を意味しない。

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

## 個人利用リリース運用（2026-10-12決定 / #311）

- PETITは本人のWindows/macOSのみで使用。Apple Developer Program・App Store公開・Developer ID証明書・公証を行わない。
- 手動`workflow_dispatch`は従来通り`development`名の開発用DMG/EXEをActions Artifactとして14日保存する。
- バージョン同期後、新しい`v<version>`タグをmain履歴上にpushすると`desktop.yml`で両OSのビルド・署名整合性/リソース検証・GitHub Release作成を自動実行する。既存`v0.25.2`タグは動かさない。
- macOSタグビルドは`npm run build:mac:personal`でad-hoc署名し、`PETIT-<version>-mac-arm64.dmg`を生成する。Windowsは従来のEXE。いずれも個人利用限定のためApple/Windowsの公式コード署名はない。
- ad-hoc署名は**改ざん検知とファイル整合性の検証**であり、開発元の認証やApple公証の代わりにはならない。Safariで取得したDMGから通常起動するとGatekeeperに拒否され得る。本人が入手元を確認し、必要な場合はmacOSの「プライバシーとセキュリティ」からそのアプリを個別に許可する。macOSのセキュリティ機能やquarantine属性を自動解除する処理は追加しない。
- Actionsのビルド・署名検証成功は実機起動合格を意味しない。実配布DMGのFinderインストール、マイク権限、再起動、更新通知・再インストールは未確認。

#309/PR #310のv0.24.0署名スキップ問題と再作成結果は、上の履歴として維持する。
