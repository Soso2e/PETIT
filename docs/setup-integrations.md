> #368: Antigravity SDKは廃止。以下のSDK記述は過去の実装・検証記録です。[現在の移行方法](sdk-retirement.md)を参照。

# 初期セットアップ・接続管理（v0.34.0 / #353）

同じFastAPI / SQLite / Module RegistryでLocalとCloudを動かす。サービス接続は`/static/setup.html`に集約し、初回起動・未ログイン時にWeb入口から案内する。従来Settingsのテーマ・音声・通知は残し、接続設定へのリンクを置く。

## サーバーの準備とUI操作

1. `pip install -r requirements.txt`。Antigravityを使うサーバーでは`pip install -r requirements-antigravity.txt`も実行する。Codexは[公式CLI](https://learn.chatgpt.com/docs/cli)をサーバーへ導入する。これらの実行環境はUIの前提条件。
2. `python -m backend.main`で起動し、localhostの画面で12文字以上の管理者パスワードを作成する。CloudはHTTPSと`PETIT_BOOTSTRAP_TOKEN`をホスト側で設定し、初回画面にその値を入力する。外部公開前にホスト設定を済ませる。初期設定後は全`/api`（health/session/login/OAuth callbackを除く）を同じ管理者sessionで保護する。
3. AIを接続し、モデル・優先順位・有料APIへの文脈送信/料金許可を保存する。キーを入力するだけでは有料推論を許可しない。接続テストは合成の専用Threadで実際に推論する。最後に「この優先順位を会話で使う」を有効にする。従来Provider選択へ戻すにはこの設定をOFFにする。
4. Notionはキーを保存し、共有済みページ/DBを検索して接続対象を保存する。Googleは自分のOAuthクライアントID/secretと登録済みcallback URIを設定し、Calendar/Gmailを別々に認可する。callback URIは`https://ホスト/api/setup/google/callback`（localhostはHTTP可）。Google側でCalendar/Gmail APIを有効にし、OAuthテスト利用者等の設定も済ませる。PETITからGoogle Cloudプロジェクトや有料契約は作成しない。
5. TimeTreeは既存exporterに必要なメール・パスワード・カレンダーコードを登録する。接続テスト後、アクティブな外部Calendarを1つ選び、手動同期で取り込みを確認する。未使用のサービスはスキップできる。
6. 初期設定を完了し、会話で予定・メール・Notionを検索する。サービス別の接続テスト成功と、実際の会話でのTool利用は分けて確認する。

## 保存・認証

- `PETIT_SETTINGS_DIR`（既定`storage/settings/`、Git管理外）に設定と秘密情報を暗号化した`config.enc`を保存する。Fernet鍵はWindowsではDPAPIで保護し、他OSでは所有者専用の鍵ファイルを使う。WindowsのDPAPIは同じOS利用者に結びつくため、別ホストへ暗号ファイルだけコピーしても復号できない。Cloudの鍵と暗号ファイルを一緒に公開しない。ホスト管理者/同一OS利用者の完全侵害への対策ではない。
- 設定・トークン更新はCoreとSDK Workerをまたぐファイルロックとatomic replaceで保存する。破損時は管理者情報を初期化せず、復旧を要するエラーにする。
- パスワードはsalt付きscrypt。session cookieはHttpOnly / SameSite=Lax、HTTPSではSecure、12時間。再起動後も認証情報は残り、管理画面へのログインは再度必要。認証試行を制限し、変更APIはOriginまたは同一サイト用custom headerを検査する。
- 公開APIは秘密の値を返さず、入力欄を保存時に消去する。ブラウザlocalStorageへキーを保存しない。OAuthコード/stateをcallbackアクセスログに残さない。VAPIDや既存`.env`をブラウザへ返さない。
- 初回管理者作成時に既存Notion/TimeTree設定を引き継ぐ。setup未使用時は既存`.env`とルーティングを維持。切断時は秘密値を明示的に空へ更新し、古い`.env`へ自動復帰しない。
- 新しい認証/料金同意は利用者がUIで行う。Desktop・iPhone等は各端末でこのWeb sessionへログインする必要がある。Desktopの認証ページはIPC権限を持たず、Google/Codexの接続操作は固定の外部ブラウザ設定画面を開く。通知pollはElectron共通sessionのcookieを使用する。既存の外部APIクライアントやショートカットはcookie/Origin対応が必要で、未対応クライアントの実機受入は残る。

## AIと単一Turn

- **Codex**: [公式app-server](https://learn.chatgpt.com/docs/app-server)をstdioで使用。PETIT専用`CODEX_HOME`と公式keyring、ChatGPT device-code認証。利用者の既存Codexトークンを読み出して流用しない。`account/read`と公式Thread/dynamic Toolのプロトコルを使う。ChatGPT認証以外のAPIキーアカウントでは推論しない。
- **Antigravity**: [公式FAQ](https://antigravity.google/docs/faq)により個人CLIラップを採用しない。[公式SDK](https://antigravity.google/docs/sdk/overview)0.1.22を再利用。loopback LM Studioか、明示許可したGemini APIで推論する。SDKの内蔵Toolはfinishだけに限定する。今回の管理UIで選ぶSDKはCoreの公開Toolをbridgeし、schema/risk/承認/receiptはPETITが管理する。従来`antigravity_sdk` profileのRead専用契約はそのまま。
- **DeepSeek**: 既存OpenAI互換native Tool Loopを再利用。APIキーと費用/文脈送信許可が必要。
- 各依頼の冒頭で優先順位を評価する。未接続・依存不足・未許可の候補を飛ばし、認証切れ/使用量上限/接続障害時に次へ進む。次Turnでは上位から再試行し、復旧後に戻る。
- 同一Turnは既存claimとProvider pinを使用。各Runtimeを終了してから次の候補を起動する。Tool呼出し・承認・receipt・保存済みmessagesがある場合は、Loopを再起動するFallbackを禁止する。外部処理のunknownを再実行しない。**Tool実行後のProvider間継続は未対応**で、保存した結果を返し、利用者が次の依頼を送る。安全に途中Tool文脈を移植する拡張は別途受入が必要。
- `local_only`のThreadは外部AIへ送らない。順位・接続・費用許可を取消した場合の再検査も行う。画像は既存の明示許可とRead専用経路を維持し、この新しいAI順位の画像Fallbackは対象外。
- 最新選択と切替理由を既存Turn Eventsへ記録し、設定UIで表示する。利用量を取得できないProviderについて使用量を創作しない。

## Calendar・Gmail・同期障害

- 外部予定の正本は外部サービス、会話からの取得はSQLite。外部は1サービスをアクティブにし、ローカル予定と一緒に読む。接続解除/切替で過去cacheを消さず、非アクティブなcacheを会話へ混ぜない。
- CalendarはGoogleの[増分同期](https://developers.google.com/workspace/calendar/api/guides/sync)を使用。外部ID・更新日時・fingerprint・syncTokenを保存。全ページ取得完了後に単一transactionでdeltaとcursorを確定する。410時はfull fetchを先に行い、取得失敗で正常cacheを消さない。削除は対象source内だけに適用。同じ内容なら行/更新日時を変更しない。
- TimeTreeは既存TLS対策済みexporterのICSを読み、外部IDとfingerprintを比較する。破損/部分応答と、既存cacheがあるのに空のexportはエラーにする。TimeTreeへの書き込みと既存のTimeTree→Google自動Pushは管理同期経路では使わない。
- 02:00 JSTの枠と成功時刻/件数/失敗/leaseをSQLiteへ保存。30秒poll、停止中は起動後に最新の未処理枠へ追いつき、失敗は15分後に再試行。手動再試行は待機を省略する。重複同期はleaseで抑止。通信中断では前回snapshot/cursorを維持し、残ったleaseは10分で失効する。常時動作するCore（単一worker）と永続volumeが必要。
- Notionは既存daily syncを継続し、last_error/daily_errorを監視して同じ運用アラートへ反映する。DBスキーマ/Notion API世代の問題を本機能だけで解決済みとは扱わない。
- GmailはCalendarと同じ[Google web OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)を共有し、サービス別scopeを追加同意。state・session・PKCE・有効期限を検査、refreshを保存する。`gmail_search`と`gmail_get_message`はRead Toolで、send/modify/deleteのscope/APIはない。plain-text本文がないメールはsnippetと本文なしを返す（HTML本文の変換・添付取得は未対応）。
- 同期エラーは通知より先に永続化。`sync_failure`高優先度カテゴリで既存Push/アプリ内通知へ配送し、同じ未解決期間は1回の配送試行に抑える。通知不能でもエラーは残り、会話ごとにコンテキストと短い追記で知らせる。正常同期で解除。通知OFFでもアラート/会話警告は消さない。実Push受信には従来のVAPID/購読設定が必要。
- **Google双方向同期は未実装**。UIは読み取り専用のみを表示し、書き込みOAuth scopeを要求しない。

## 検証

`python -m pytest tests/test_setup_integrations.py -q`で認証/暗号化/OAuth/Calendar delta/再起動相当のschedule/lease/通知/Brain fallback/Gmail契約を検証する。実サービスをMock成功で代替したという主張はしない。

`node scripts/test-setup-ui.cjs`はPlaywright+Chromeの実HTTP/合成Providerで1440/390px、ウィザード、優先順位、再送、サーバー再起動後の設定/会話を検証する。`PETIT_SETUP_REAL_SDK=1`ではMockを外し、公式SDK+`petit-setup-probe`というLM Studioモデルを使う。`PETIT_TEST_PYTHON`で環境を指定する。証跡はGit管理外`storage/setup-e2e/`。

実Codex認証/推論、Gemini/DeepSeek課金API、実Notion/Google OAuth/Gmail/Calendar/TimeTree、02:00実時計の稼働、実Push受信、Cloud実デプロイ、配布Desktop/実スマホは利用者の認証・受入が必要。全完成条件を満たした扱いにはしない。


実行記録は[検証サマリー](../reports/setup-integrations-validation.json)。最終のSDK/LM Studio検証は合成の明示bridge契約プロンプトを用い、Read・記憶保存・予定承認/再開・再送・再起動・未認証CodexからのFallbackまで成功した。SQLiteの保存行と承認引数/receiptも一致した。一方、途中の自然文テストでは小型モデルがToolを呼ばず保存したと述べるケースを検出した。履歴と今回の依頼の分離後に契約ケースは成功したが、自然文全般の実行精度が解決済みという意味ではない。配布前の受入項目として残す。
