@echo off
rem =====================================================================
rem  HandPack - Build (Windows)
rem  Erzeugt mit PyInstaller eine eigenstaendige EXE unter dist\.
rem  ffmpeg/dovi_tool/mkvmerge werden NICHT eingebettet - die App laedt
rem  sie bei Bedarf selbst herunter in einen ".tools"-Ordner neben der EXE.
rem =====================================================================
setlocal
cd /d "%~dp0"

rem --- Python ermitteln (py-Launcher, dann python, dann python3) ---
set "PY="
py --version >nul 2>&1
if not errorlevel 1 set "PY=py"
if "%PY%"=="" (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if "%PY%"=="" (
    python3 --version >nul 2>&1
    if not errorlevel 1 set "PY=python3"
)
if "%PY%"=="" (
    echo FEHLER: Kein Python gefunden. Bitte Python installieren und im PATH haben.
    pause
    exit /b 1
)
echo Python: %PY%

rem --- Version aus version.py lesen ---
rem    Umweg ueber Datei, um Quoting-Probleme mit f-Strings zu vermeiden
%PY% -c "from version import APP_NAME,VERSION; open('_ver.tmp','w').write(APP_NAME+'-'+VERSION)"
if errorlevel 1 (
    echo FEHLER: version.py konnte nicht gelesen werden.
    if exist "_ver.tmp" del "_ver.tmp"
    pause
    exit /b 1
)
set /p APP_VER=<_ver.tmp
del "_ver.tmp"
if "%APP_VER%"=="" (
    echo FEHLER: APP_VER ist leer.
    pause
    exit /b 1
)
set "DIST_EXE=dist\%APP_VER%.exe"
echo Version: %APP_VER%

rem --- Build-Venv anlegen / aktualisieren ---
if not exist ".venv-build\Scripts\python.exe" (
    echo Erstelle Build-Umgebung...
    %PY% -m venv .venv-build
)
".venv-build\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv-build\Scripts\python.exe" -m pip install --quiet -r requirements-build.txt
if errorlevel 1 (
    echo FEHLER: pip install fehlgeschlagen.
    pause
    exit /b 1
)

rem --- Icon erzeugen (SVG -> ICO) ---
echo Erzeuge icon.ico ...
".venv-build\Scripts\python.exe" make_icon.py
if errorlevel 1 (
    echo FEHLER: Icon-Konvertierung fehlgeschlagen.
    pause
    exit /b 1
)

rem --- altes Artefakt entfernen ---
if exist "%DIST_EXE%" del /f /q "%DIST_EXE%"

rem --- PyInstaller ---
echo Baue %APP_VER%.exe ...
".venv-build\Scripts\pyinstaller.exe" --noconfirm --clean ^
    --name "%APP_VER%" ^
    --windowed ^
    --onefile ^
    --icon "icon.ico" ^
    --add-data "icon.svg;." ^
    --add-data "README.md;." ^
    --add-data "README_DE.md;." ^
    main.py
if errorlevel 1 (
    echo FEHLER: PyInstaller-Build fehlgeschlagen.
    pause
    exit /b 1
)

rem --- Build-Ordner aufraumen ---
if exist "build" rmdir /s /q "build"

echo.
echo Fertig: %DIST_EXE%
echo Beim ersten Start ggf. "Fehlende Tools herunterladen" klicken.
pause
endlocal
