$target = "C:\#Project\Server\PersonalAssistant_PETIT\storage\settings"
takeown /F $target /R /A /D Y
icacls $target /grant "${env:USERNAME}:(OI)(CI)F" /T
Write-Host "権限の修正が完了しました。"
Start-Sleep -Seconds 2
