@echo off
chcp 65001 >nul
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WhisperFlow.lnk"
if exist "%LNK%" (
    del "%LNK%"
    echo [OK] Autostart entfernt.
) else (
    echo Kein Autostart-Eintrag gefunden.
)
pause
