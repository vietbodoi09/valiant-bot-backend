@echo off
echo ===========================================
echo Valiant Bot - Local + Ngrok
echo ===========================================
echo.

:: Check for ngrok token
if "%NGROK_AUTH_TOKEN%"=="" (
    echo [ERROR] NGROK_AUTH_TOKEN not set!
    echo.
    echo 1. Go to https://ngrok.com and sign up (free)
    echo 2. Copy your authtoken
    echo 3. Run: set NGROK_AUTH_TOKEN=your_token
    echo 4. Run this file again
    echo.
    pause
    exit /b
)

echo [1/4] Installing dependencies...
pip install pyngrok -q

echo [2/4] Starting ngrok tunnel...
start "Ngrok" cmd /c "ngrok http 8000"

echo [3/4] Waiting for ngrok to start...
timeout /t 3 /nobreak >nul

echo [4/4] Starting backend...
echo.
echo ===========================================
echo Backend starting on http://localhost:8000
echo.
echo Get your public URL from the ngrok window!
echo (Usually: https://xxxx.ngrok-free.app)
echo ===========================================
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

echo.
echo Backend stopped!
pause
