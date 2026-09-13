@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Lege Autostart-Verknuepfung an (Start mit Windows, ohne Fenster) ...

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS=%~dp0start-hidden.vbs"
set "LNK=%STARTUP%\WhisperFlow.lnk"

powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath='wscript.exe';" ^
  "$s.Arguments='\"%VBS%\"';" ^
  "$s.WorkingDirectory='%CD%';" ^
  "$s.IconLocation='%SystemRoot%\System32\shell32.dll,138';" ^
  "$s.Save()"

if exist "%LNK%" (
    echo.
    echo [OK] WhisperFlow startet ab jetzt automatisch mit Windows.
    echo      Entfernen: windows\install-autostart-entfernen.bat
) else (
    echo [FEHLER] Verknuepfung konnte nicht erstellt werden.
)
pause
