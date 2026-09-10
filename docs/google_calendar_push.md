# TimeTree → Google Calendar 同期

TimeTree の読み取り同期後、取得した予定を Google Calendar に作成・更新するオプション機能です。

## 標準状態

**OFF が標準です。**

```env
PETIT_GOOGLE_CALENDAR_SYNC_ENABLED=0
```

OFF の場合、Google Calendar API にはアクセスしません。TimeTree の通常同期とラベル取得だけが動作します。

## 初回設定

Google Cloud で Calendar API を有効化し、Desktop app 用 OAuth クライアントを作成して JSON を取得します。

既定では以下に配置します。

```text
storage/google_calendar_credentials.json
```

別パスの場合:

```env
PETIT_GOOGLE_CALENDAR_CREDENTIALS_FILE=C:/path/to/credentials.json
```

依存関係を入れた後、初回だけ以下を実行します。

```bash
python tools/google_calendar_auth.py
```

認証後のトークンは既定で以下に保存されます。

```text
storage/google_calendar_token.json
```

## ON にする

```env
PETIT_GOOGLE_CALENDAR_SYNC_ENABLED=1
PETIT_GOOGLE_CALENDAR_ID=primary
```

必要ならトークンの保存先も変更できます。

```env
PETIT_GOOGLE_CALENDAR_TOKEN_FILE=C:/path/to/google_calendar_token.json
```

## 同期仕様

- TimeTree 同期成功後にのみ実行
- TimeTree UID を `extendedProperties.private.petit_timetree_uid` として保存
- 同じ UID が Google Calendar に存在する場合は `patch`
- 存在しない場合のみ `insert`
- 自動削除はしない
- 招待メール等は送らない (`sendUpdates=none`)

TimeTree ラベルは Google Calendar の予定に以下の両方で保存します。

1. 説明欄
   - `TimeTreeラベル: そそ`
   - `TimeTreeラベル色: #...`
2. `extendedProperties.private`
   - `petit_source=timetree`
   - `petit_timetree_uid=...`
   - `timetree_label=...`
   - `timetree_label_id=...`
   - `timetree_label_color=...`

説明欄にも残すのは、Google Calendar を読む外部 AI / コネクタが `extendedProperties` を返さない場合でも、誰の予定か判定できるようにするためです。

## 失敗時

Google Calendar 側への push が失敗しても、TimeTree → PETIT の読み取り同期は失敗扱いにしません。Google push の結果は `google_calendar_push` フィールドで独立して返します。
