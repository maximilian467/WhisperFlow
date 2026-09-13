@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ============================================================
echo  WhisperFlow - Installation (Windows)
echo ============================================================
echo.
echo [1/3] Erstelle virtuelle Python-Umgebung (venv) ...
python -m venv venv
if errorlevel 1 (
    echo.
    echo [FEHLER] venv konnte nicht erstellt werden. Ist Python installiert?
    pause
    exit /b 1
)

echo [2/3] Aktualisiere pip ...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo [3/3] Installiere Abhaengigkeiten (dauert beim ersten Mal etwas) ...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [FEHLER] Installation der Pakete fehlgeschlagen.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Fertig! Starte WhisperFlow mit:  windows\start.bat
echo ============================================================
pause
