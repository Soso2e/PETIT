# Mac Desktop通知の切り分け（#329）

## 確認できた原因と未確認

- ローカルに残るv0.25.1のapp.asarは通常通知feedとpetitNotifications bridgeを持たない。現行Web UIと組み合わせるとブラウザ用Web Push設定が表示される。Electron権限handlerはoverlayの音声入力のみ許可するためWeb Notification APIは拒否される。これはmacOSの通知拒否とは別。
- #315 / PR #317（v0.26.0）でDesktop Mainの15秒poll → 通知イベント → gentle/native表示が追加された。現行mainではworkspace preloadのpetitNotificationsを使い、VAPID/pywebpush/Notification.permissionを通らない。
- 現行mainのnative通知はsilent:true固定、gentleカードも無音。v0.29.1ではOS通知音を独立した明示ON設定にし、既定は無音を保つ。
- この調査MacにはApplications内・起動中のPETITと実利用プロファイルが見つからなかった。報告対象のバージョン、エラー文言、OS許可、Focus状態を確定したものではない。

## 呼び出し順と各層

1. Backend dispatch_notificationは通知イベントをDBへ記録。カテゴリOFFやPush購読なしでもイベントは存在する。Web Push経路は購読・VAPID・pywebpushを別途使う。
2. Desktop通知ON時、Mainがイベントをpoll。初回は過去イベントをbaseline化し、次回以降の未読・未解決・カテゴリON・2分未満のイベントを表示する。
3. gentleはフォーカスを奪わないカード、nativeはElectron MainのNotification。Web権限handlerを緩める必要はない。
4. Notification.isSupported()は機能対応の判定でありOS許可の取得ではない。返却するpermissionはunknown。テストは3秒までshow/failedを待ち、無応答を要求済み・受信未確認として返す。遅いfailedも次の状態取得へ反映する。showイベントでも音や実受信を断定しない。
5. Macの表示にはアプリ署名が必要。個人用ad-hoc署名のパッケージ生成・整合検証はDeveloper ID署名、公証、OS許可、実受信の証明ではない。

## 実機で確認する順序

1. Desktop設定のアプリバージョンを確認。v0.26.0未満はDesktop本体を更新し、サーバーもv0.26.0以上にする。Webだけ更新しても古いDesktopにはbridgeが追加されない。
2. Desktop設定で「Desktopで通知を受け取る」「OSの通知」「OS通知で音を鳴らす」を選び保存。作業画面Settingsで必要なカテゴリをON。
3. macOS システム設定 → 通知 → PETITで通知、通知スタイル、サウンドを許可。集中モードOFFでテストし、ON時はPETITの許可対象設定と比較。OS設定は本修正で変更しない。
4. 保存済み設定のテストを実行。失敗表示なら署名・OS設定を確認。カードへ切り替えて表示できるならサーバーやWeb Pushに依存しない表示経路を確認できる。ただしローカルテストだけではpoll受信を証明しない。
5. アプリ常駐・小型画面を閉じた状態で新規の対象通知を発生させ、15秒程度で受信するか確認。アプリ終了、サーバー停止、ロック/スリープ、古い通知は受信対象外。
6. Web/PWAは独立してWeb Push設定を確認。Desktopのブラウザ拒否をSafari/Chrome側の許可変更で直そうとしない。

実機確認担当: 利用者。実受信・実音・Focus ON/OFF・通常ダウンロードしたDMGのインストールは未確認。検証用DMGを正式Releaseに置き換えない。

参考: [Electron Notification](https://www.electronjs.org/docs/latest/api/notification)、[Electron session permissions](https://www.electronjs.org/docs/latest/api/session)、[Apple通知設定](https://support.apple.com/guide/mac-help/change-notifications-settings-mh40583/mac)。

## この変更の検証結果

- Desktop単体65件、Backend通知関連17件成功。構文チェックと差分チェック成功。
- 隔離Electronの通知専用smoke成功: 音設定の保存、Web Notification.permission=deniedのままDesktop有効化・テスト・停止。
- Mac arm64開発DMG生成、ad-hoc署名整合、DMG内アプリの一致、通知module同梱検証成功。生成物はユーザーの依頼により削除済み。インストール・Releaseは未実施。
- 全体smokeは未完了。音声確認ボタンの待機timeout、統計画面の待機timeout、入力文字列の不一致で失敗。通知専用smokeとは別の未解決条件として扱い、全体回帰成功とはしない。追加の画面/実機確認は利用者が担当。
