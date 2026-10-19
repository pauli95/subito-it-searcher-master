@echo off
setlocal
cd /d "%~dp0"
title Subito Searcher

rem --- 1. Python di sistema (serve solo per creare il virtualenv) -------------------
set "PY="
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)

rem --- 2. Virtualenv in .venv (creato al primo avvio) ---------------------------------
if not exist ".venv\Scripts\python.exe" (
    if not defined PY (
        echo Python non trovato. Installalo da https://www.python.org/downloads/
        echo e spunta "Add python.exe to PATH" durante l'installazione.
        pause
        exit /b 1
    )
    echo Creazione dell'ambiente virtuale .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo Errore nella creazione del virtualenv.
        pause
        exit /b 1
    )
)
set "VPY=.venv\Scripts\python.exe"

rem --- 3. Dipendenze: reinstallate solo se requirements.txt e' cambiato ---------------
fc /b requirements.txt .venv\requirements.installed >nul 2>nul
if errorlevel 1 (
    echo Installazione delle dipendenze ...
    "%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Errore durante l'installazione delle dipendenze.
        pause
        exit /b 1
    )
    copy /y requirements.txt .venv\requirements.installed >nul
)

rem --- 4. Avvio ---------------------------------------------------------------------
echo.
echo Avvio di Subito Searcher su http://127.0.0.1:8000
echo Lascia aperta questa finestra; chiudila o premi CTRL+C per fermare l'app.
echo.
"%VPY%" server.py --open
pause
