@echo off
rem =====================================================================
rem  HandPack - Docker Image Deploy (Windows)
rem  Taggt ein zuvor mit build_docker.bat gebautes lokales Image fuer
rem  eine Ziel-Registry (z.B. eine lokale Registry auf Unraid) und pusht
rem  Version- und latest-Tag dorthin.
rem
rem  Voraussetzung: build_docker.bat [namespace] wurde bereits ausgefuehrt.
rem  Bei HTTP-Registry ohne TLS muss sie auf dieser Maschine als
rem  insecure-registry eingetragen sein:
rem    Docker Desktop -> Settings -> Docker Engine -> JSON ergaenzen:
rem      { "insecure-registries": ["registry-host:port"] }
rem    -> Apply & Restart
rem =====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- Argumente ---
rem     Aufruf:  deploy_docker.bat <registry-host:port> [namespace]
rem     Beispiel: deploy_docker.bat 192.168.1.50:5000 kristian
rem       liest lokales Image kristian/handpack:<version>
rem       und pusht es als 192.168.1.50:5000/kristian/handpack:<version>
set "REGISTRY=%~1"
set "NAMESPACE=%~2"

if "%REGISTRY%"=="" (
    set /p "REGISTRY=Ziel-Registry (host:port): "
)
if "%REGISTRY%"=="" (
    echo FEHLER: Keine Ziel-Registry angegeben.
    pause
    exit /b 1
)
echo %REGISTRY%| findstr /r ":[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo FEHLER: "%REGISTRY%" enthaelt keinen Port ^(z.B. :5000^).
    echo Ohne Port versucht Docker HTTPS auf Port 443 -^> "connection refused".
    echo Beispiel: 192.168.178.222:5000
    pause
    exit /b 1
)

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

set "LOCAL_NAME=%IMG_NAME%"
if not "%NAMESPACE%"=="" (
    set "LOCAL_NAME=%NAMESPACE%/%IMG_NAME%"
)
set "LOCAL_TAG_VER=%LOCAL_NAME%:%IMG_VER%"
set "LOCAL_TAG_LATEST=%LOCAL_NAME%:latest"

rem --- Lokales Image muss existieren ---
docker image inspect "%LOCAL_TAG_VER%" >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Lokales Image %LOCAL_TAG_VER% nicht gefunden.
    echo Zuerst bauen mit:  build_docker.bat %NAMESPACE%
    pause
    exit /b 1
)

set "REMOTE_NAME=%REGISTRY%/%LOCAL_NAME%"
set "REMOTE_TAG_VER=%REMOTE_NAME%:%IMG_VER%"
set "REMOTE_TAG_LATEST=%REMOTE_NAME%:latest"

echo.
echo Tagge %LOCAL_TAG_VER% als %REMOTE_TAG_VER% ...
docker tag "%LOCAL_TAG_VER%" "%REMOTE_TAG_VER%"
docker tag "%LOCAL_TAG_LATEST%" "%REMOTE_TAG_LATEST%"

echo Push zu %REGISTRY% ...
docker push "%REMOTE_TAG_VER%"
if errorlevel 1 (
    echo FEHLER: Push fehlgeschlagen. Ist die Registry erreichbar und als
    echo insecure-registry in Docker Desktop eingetragen?
    pause
    exit /b 1
)
docker push "%REMOTE_TAG_LATEST%"

echo.
echo Erfolgreich gepusht: %REMOTE_TAG_VER%  und  %REMOTE_TAG_LATEST%
echo In Dockge verwenden:  image: %REMOTE_TAG_VER%
echo.
pause
endlocal
