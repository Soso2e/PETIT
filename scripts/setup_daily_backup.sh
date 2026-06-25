#!/bin/bash
# TimeTree 毎日バックアップの自動実行セットアップスクリプト
# 使い方: bash scripts/setup_daily_backup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="${PYTHON:-python3}"

echo "=== TimeTree 毎日バックアップ セットアップ ==="
echo "プロジェクトディレクトリ: $PROJECT_DIR"
echo ""

# --- 依存パッケージのインストール確認 ---
echo "[1/3] 依存パッケージを確認..."
if ! $PYTHON -c "import icalendar" 2>/dev/null; then
    echo "  icalendar をインストールします..."
    $PYTHON -m pip install icalendar
else
    echo "  icalendar: OK"
fi

# --- TIMETREE_ICAL_URL の確認 ---
echo ""
echo "[2/3] iCal URL を確認..."
if [ -z "$TIMETREE_ICAL_URL" ]; then
    echo ""
    echo "  TIMETREE_ICAL_URL が設定されていません。"
    echo ""
    echo "  TimeTree で iCal URL を取得する手順:"
    echo "    1. TimeTree アプリを開く"
    echo "    2. カレンダーを選択 → 設定（歯車アイコン）"
    echo "    3. 「外部カレンダーへの同期」→「iCal リンク」をコピー"
    echo ""
    read -r -p "  iCal URL を貼り付けてください: " ICAL_URL
    if [ -z "$ICAL_URL" ]; then
        echo "  URL が入力されなかったため、環境変数の設定のみ手順を案内します。"
    else
        export TIMETREE_ICAL_URL="$ICAL_URL"
        echo "  TIMETREE_ICAL_URL を設定しました。"
        # .env ファイルへ保存
        ENV_FILE="$PROJECT_DIR/.env"
        if grep -q "TIMETREE_ICAL_URL" "$ENV_FILE" 2>/dev/null; then
            sed -i "s|^TIMETREE_ICAL_URL=.*|TIMETREE_ICAL_URL=$ICAL_URL|" "$ENV_FILE"
        else
            echo "TIMETREE_ICAL_URL=$ICAL_URL" >> "$ENV_FILE"
        fi
        echo "  .env に保存しました: $ENV_FILE"
    fi
else
    echo "  TIMETREE_ICAL_URL: 設定済み"
fi

# --- 自動実行の設定 ---
echo ""
echo "[3/3] 毎日の自動実行を設定..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: launchd
    PLIST_LABEL="com.petit.timetree-backup"
    PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
    LOG_DIR="$PROJECT_DIR/storage/logs"
    mkdir -p "$LOG_DIR"

    cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>$($PYTHON -c "import sys; print(sys.executable)")</string>
        <string>$PROJECT_DIR/tools/timetree_backup.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TIMETREE_ICAL_URL</key>
        <string>${TIMETREE_ICAL_URL}</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/timetree_backup.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/timetree_backup_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

    # 既存のジョブをアンロードしてから再ロード
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load "$PLIST_PATH"

    echo "  launchd に登録しました: $PLIST_PATH"
    echo "  実行時刻: 毎朝 6:00"
    echo ""
    echo "  手動で今すぐ実行:"
    echo "    launchctl start $PLIST_LABEL"
    echo "  停止:"
    echo "    launchctl unload $PLIST_PATH"

elif command -v crontab &>/dev/null; then
    # Linux / Windows (WSL): cron
    CRON_CMD="0 6 * * * TIMETREE_ICAL_URL='${TIMETREE_ICAL_URL}' $($PYTHON -c "import sys; print(sys.executable)") $PROJECT_DIR/tools/timetree_backup.py >> $PROJECT_DIR/storage/logs/timetree_backup.log 2>&1"

    # 既存のエントリを削除してから追加
    (crontab -l 2>/dev/null | grep -v "timetree_backup.py"; echo "$CRON_CMD") | crontab -

    echo "  cron に登録しました（毎朝 6:00）。"
    echo "  確認: crontab -l"
    echo ""
    echo "  手動で今すぐ実行:"
    echo "    python $PROJECT_DIR/tools/timetree_backup.py"
else
    echo "  自動実行の設定をスキップしました（launchd / cron が見つかりません）。"
    echo "  手動で実行してください:"
    echo "    python $PROJECT_DIR/tools/timetree_backup.py"
fi

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "動作確認（手動実行）:"
echo "  export TIMETREE_ICAL_URL='<your_url>'"
echo "  python $PROJECT_DIR/tools/timetree_backup.py"
