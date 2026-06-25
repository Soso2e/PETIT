#!/bin/bash
# TimeTree 毎日バックアップの自動実行セットアップ
# 使い方: bash scripts/setup_daily_backup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="${PYTHON:-python3}"

echo "=== TimeTree 毎日バックアップ セットアップ ==="
echo ""

# --- 依存パッケージ ---
echo "[1/3] 依存パッケージを確認..."
$PYTHON -m pip install -q icalendar timetree-exporter
echo "  OK"

# --- 環境変数 ---
echo ""
echo "[2/3] 環境変数を確認..."

ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
fi

source "$ENV_FILE" 2>/dev/null || true

if [ -z "$TIMETREE_EMAIL" ] || [ -z "$TIMETREE_PASSWORD" ] || [ -z "$TIMETREE_CALENDAR_CODE" ]; then
    echo ""
    echo "  .env に以下を設定してください: $ENV_FILE"
    echo ""
    echo "    TIMETREE_EMAIL=your@email.com"
    echo "    TIMETREE_PASSWORD=your_password"
    echo "    TIMETREE_CALENDAR_CODE=your_calendar_code"
    echo ""
    echo "  カレンダーコードの確認:"
    echo "    timetree-exporter -e your@email.com"
    echo ""
    echo "  設定後、もう一度このスクリプトを実行してください。"
    exit 1
fi

echo "  TIMETREE_EMAIL:         $TIMETREE_EMAIL"
echo "  TIMETREE_CALENDAR_CODE: $TIMETREE_CALENDAR_CODE"

# --- 自動実行の設定 ---
echo ""
echo "[3/3] 毎日の自動実行を設定..."

LOG_DIR="$PROJECT_DIR/storage/logs"
mkdir -p "$LOG_DIR"

if [[ "$OSTYPE" == "darwin"* ]]; then
    PLIST_LABEL="com.petit.timetree-backup"
    PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
    PYTHON_BIN="$($PYTHON -c "import sys; print(sys.executable)")"

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
        <string>${PYTHON_BIN}</string>
        <string>${PROJECT_DIR}/tools/timetree_backup.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TIMETREE_EMAIL</key>
        <string>${TIMETREE_EMAIL}</string>
        <key>TIMETREE_PASSWORD</key>
        <string>${TIMETREE_PASSWORD}</string>
        <key>TIMETREE_CALENDAR_CODE</key>
        <string>${TIMETREE_CALENDAR_CODE}</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/timetree_backup.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/timetree_backup_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load "$PLIST_PATH"
    echo "  launchd に登録しました（毎朝 6:00）: $PLIST_PATH"
    echo ""
    echo "  今すぐ実行: launchctl start $PLIST_LABEL"
    echo "  停止:       launchctl unload $PLIST_PATH"

elif command -v crontab &>/dev/null; then
    PYTHON_BIN="$($PYTHON -c "import sys; print(sys.executable)")"
    CRON_CMD="0 6 * * * . $ENV_FILE && $PYTHON_BIN $PROJECT_DIR/tools/timetree_backup.py >> $LOG_DIR/timetree_backup.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "timetree_backup.py"; echo "$CRON_CMD") | crontab -
    echo "  cron に登録しました（毎朝 6:00）。"
    echo "  確認: crontab -l"
else
    echo "  launchd / cron が見つかりません。手動で実行してください。"
fi

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "手動実行:"
echo "  source $ENV_FILE && python $PROJECT_DIR/tools/timetree_backup.py"
