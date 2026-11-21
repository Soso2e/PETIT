@echo off
echo settingsフォルダのアクセス権限を修復しています...
takeown /F "C:\#Project\Server\PersonalAssistant_PETIT\storage\settings" /R /A /D Y
icacls "C:\#Project\Server\PersonalAssistant_PETIT\storage\settings" /grant "%USERNAME%:(OI)(CI)F" /T
echo.
echo 完了しました。このウィンドウを閉じてください。
pause
