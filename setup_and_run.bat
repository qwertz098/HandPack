@echo off
rem =====================================================================
rem  FF-Transcoder - Setup & Start (Windows)
rem  Legt beim ersten Aufruf eine virtuelle Umgebung (.venv) an,
rem  installiert die Abhaengigkeiten und startet danach die App.
rem  Voraussetzung: Python 3.11+ von python.org (mit "py"-Launcher)
rem =====================================================================
setlocal
cd /d "%~dp0"

rem --- Python finden (py-Launcher bevorzugt) ---
set "PY=py -3"
%PY% --version >nul 2>&1
if errorlevel 1 (
    set "PY=python"
    %PY% --version >nul 2>&1
    if errorlevel 1 (
        echo FEHLER: Python nicht gefunden. Bitte Python 3.11+ installieren:
        echo   https://www.python.org/downloads/
        echo   ^(Haken bei "Add python.exe to PATH" setzen^)
        pause
        exit /b 1
    )
)

rem --- venv anlegen, falls nicht vorhanden ---
if not exist ".venv\Scripts\python.exe" (
    echo Erstelle virtuelle Umgebung...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo FEHLER: venv konnte nicht erstellt werden.
        pause
        exit /b 1
    )
)

rem --- Abhaengigkeiten installieren/aktualisieren ---
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo FEHLER: Installation der Abhaengigkeiten fehlgeschlagen.
    pause
    exit /b 1
)

rem --- App starten (ohne Konsolenfenster via pythonw) ---
echo Starte FF-Transcoder...
start "" ".venv\Scripts\pythonw.exe" main.py
endlocal
