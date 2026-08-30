@echo off
REM ==========================================================================
REM  AutoFill Agent - backend launcher (Windows)
REM  Double-click this file to start the local backend.
REM  On first run it sets up everything automatically.
REM ==========================================================================
setlocal
cd /d "%~dp0"

echo ============================================
echo   AutoFill Agent - starting local backend
echo ============================================
echo.

REM --- 1. Check Python is installed -----------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during install, then run this again.
    echo.
    pause
    exit /b 1
)

REM --- 2. Create the virtual environment on first run -----------------------
if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
    echo Installing requirements (one-time, may take a minute)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Installing requirements failed. Check your internet connection.
        pause
        exit /b 1
    )
)

REM --- 3. Make sure a .env exists -------------------------------------------
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo.
        echo [ACTION NEEDED] A new .env file was just created.
        echo Open it in Notepad and set your GROQ_API_KEY and LOCAL_TOKEN,
        echo then run this launcher again.
        echo   - Free key: https://console.groq.com/keys
        echo   - LOCAL_TOKEN: any random string ^(also paste it into the extension^)
        echo.
        notepad ".env"
        pause
        exit /b 0
    ) else (
        echo [ERROR] No .env or .env.example found in this folder.
        pause
        exit /b 1
    )
)

REM --- 4. Start the server ---------------------------------------------------
echo.
echo Backend running at http://127.0.0.1:8000
echo Health check:      http://127.0.0.1:8000/health
echo.
echo Keep this window OPEN while you use the extension.
echo Close it (or press Ctrl+C) to stop the backend.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

pause
