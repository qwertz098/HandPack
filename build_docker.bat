@echo off
rem =====================================================================
rem  HandPack - Docker Image Build (Windows)
rem  Baut das Linux-Container-Image (ffmpeg + noVNC-GUI) und taggt es
rem  lokal mit Name + Version aus version.py. Fertige Images gibt es
rem  unter ghcr.io/qwertz098/handpack.
rem =====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- Python ermitteln (fuer version.py-Auslesen) ---
set "PY="
py --version >nul 2>&1
if not errorlevel 1 set "PY=py"
if "%PY%"=="" (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if "%PY%"=="" (
    echo FEHLER: Kein Python gefunden. Bitte Python installieren und im PATH haben.
    pause
    exit /b 1
)

rem --- Docker verfuegbar? ---
docker --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Docker wurde nicht gefunden. Bitte Docker Desktop installieren/starten.
    pause
    exit /b 1
)

rem --- Version aus version.py lesen ---
%PY% -c "from version import APP_NAME,VERSION; open('_ver.tmp','w').write(APP_NAME.lower()+'|'+VERSION)"
if errorlevel 1 (
    echo FEHLER: version.py konnte nicht gelesen werden.
    if exist "_ver.tmp" del "_ver.tmp"
    pause
    exit /b 1
)
set /p VERLINE=<_ver.tmp
del "_ver.tmp"
for /f "tokens=1,2 delims=|" %%a in ("%VERLINE%") do (
    set "IMG_NAME=%%a"
    set "IMG_VER=%%b"
)
if "%IMG_NAME%"=="" (
    echo FEHLER: Image-Name konnte nicht ermittelt werden.
    pause
    exit /b 1
)

rem --- Namespace optional per Argument ---
rem     Aufruf:  build_docker.bat [namespace]
rem     Beispiel: build_docker.bat kristian
rem       -> Image: kristian/handpack:0.1  (+ :latest)
set "NAMESPACE=%~1"
if not "%NAMESPACE%"=="" (
    set "IMG_NAME=%NAMESPACE%/%IMG_NAME%"
)

set "TAG_VER=%IMG_NAME%:%IMG_VER%"
set "TAG_LATEST=%IMG_NAME%:latest"

echo.
echo Baue Docker-Image %TAG_VER% ...
docker build -t "%TAG_VER%" -t "%TAG_LATEST%" .
if errorlevel 1 (
    echo FEHLER: Docker-Build fehlgeschlagen.
    pause
    exit /b 1
)

echo.
echo Fertig: %TAG_VER%  (auch getaggt als %TAG_LATEST%)
echo.
echo Lokal starten:  docker compose up -d
echo.
pause
endlocal
