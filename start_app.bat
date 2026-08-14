@echo off
title VST IMS - One Click Launcher
color 0A
echo =====================================================
echo    VST IMS - Inventory Management System Launcher
echo =====================================================
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend
set URL=http://localhost:5173

REM ---------- Step 1: Backend virtual env ----------
if not exist "%BACKEND%\venv\Scripts\python.exe" (
    echo [1/4] Creating Python virtual environment...
    python -m venv "%BACKEND%\venv"
    if errorlevel 1 (
        echo ERROR: Failed to create venv. Is Python installed?
        pause
        exit /b 1
    )
)

echo [2/4] Checking backend dependencies...
"%BACKEND%\venv\Scripts\python.exe" -c "import fastapi, sqlalchemy, uvicorn" 2>nul
if errorlevel 1 (
    echo Installing backend dependencies, this may take a minute...
    "%BACKEND%\venv\Scripts\pip.exe" install -r "%BACKEND%\requirements.txt"
    if errorlevel 1 (
        echo ERROR: Failed to install backend dependencies.
        pause
        exit /b 1
    )
)

REM ---------- Step 2: Database check ----------
echo [3/4] Checking database...
if not exist "%BACKEND%\vst_ims.db" (
    echo    Database not found. Migrating CSV data into database...
    "%BACKEND%\venv\Scripts\python.exe" "%BACKEND%\migrate_csv_to_pg.py"
    if errorlevel 1 (
        echo WARNING: Migration had issues. The app may still start with empty data.
    )
)

echo [4/4] Starting VST IMS...
echo.

REM ---------- Step 3: Check if backend already running (port 8000) ----------
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8000/api/health > "%TEMP%\vst_bk.txt" 2>nul
set /p BKCODE=<"%TEMP%\vst_bk.txt"
if "%BKCODE%"=="200" (
    echo    Backend already running on port 8000 - reusing it.
) else (
    start "VST IMS - Backend (API)" cmd /k "cd /d %BACKEND% && venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
    echo    Backend started in new window.
)

REM ---------- Step 4: Check if frontend already running (port 5173) ----------
curl -s -o nul -w "%%{http_code}" http://localhost:5173 > "%TEMP%\vst_fe.txt" 2>nul
set /p FECODE=<"%TEMP%\vst_fe.txt"
if "%FECODE%"=="200" (
    echo    Frontend already running on port 5173 - reusing it.
) else (
    start "VST IMS - Frontend (React)" cmd /k "cd /d %FRONTEND% && npm run dev"
    echo    Frontend started in new window.
)

REM ---------- Step 5: Wait until frontend is ready (up to 60s) ----------
echo.
echo Waiting for frontend to be ready...
set /a TRIES=0
:waitloop
set /a TRIES+=1
curl -s -o nul -w "%%{http_code}" http://localhost:5173 > "%TEMP%\vst_fe.txt" 2>nul
set /p FECODE=<"%TEMP%\vst_fe.txt"
if "%FECODE%"=="200" goto ready
if %TRIES% geq 60 goto fail
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo Frontend is ready! Opening browser...
echo.

REM ---------- Step 6: Open Chrome (fallback to default browser) ----------
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" %URL%
    goto opened
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" %URL%
    goto opened
)
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    start "" "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" %URL%
    goto opened
)
start %URL%
:opened

echo.
echo =====================================================
echo    VST IMS is running!
echo.
echo    Frontend : %URL%
echo    Backend  : http://localhost:8000
echo    API Docs : http://localhost:8000/docs
echo.
echo    You can close this window. The app runs in the
echo    two new terminal windows that opened.
echo =====================================================
echo.
pause
exit /b 0

:fail
echo ERROR: Frontend did not become ready in 60 seconds.
echo Check the "VST IMS - Frontend" window for errors, then open %URL% manually.
pause
exit /b 1