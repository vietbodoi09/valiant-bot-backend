@echo off
echo ==========================================
echo Fly.io Deploy Script for Valiant Bot
echo ==========================================
echo.

:: Check if fly CLI installed
where fly >nul 2>nul
if %errorlevel% neq 0 (
    echo Fly CLI not found. Installing...
    powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
    echo Please restart terminal and run again
    pause
    exit /b
)

echo Fly CLI found!
echo.

:: Login (will open browser)
echo Logging in to Fly.io (will open browser)...
fly auth login
if %errorlevel% neq 0 (
    echo Login failed
    pause
    exit /b
)

echo.
echo ==========================================
echo Creating new app with unique name...
echo ==========================================
echo.

:: Generate unique name with timestamp
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value ^| find "LocalDateTime"') do set datetime=%%a
set TIMESTAMP=%datetime:~0,12%
set APP_NAME=valiant-bot-be-%TIMESTAMP:~8,4%

echo App name: %APP_NAME%
echo.

:: Create app
fly apps create %APP_NAME%
if %errorlevel% neq 0 (
    echo Create failed, trying with random suffix...
    set APP_NAME=valiant-bot-be-%RANDOM%
    fly apps create %APP_NAME%
)

echo.
echo ==========================================
echo Deploying...
echo ==========================================
echo.

fly deploy --app %APP_NAME% --region sin

echo.
echo ==========================================
echo Getting app URL...
echo ==========================================
echo.

fly status --app %APP_NAME%

echo.
echo ==========================================
echo Deploy complete!
echo ==========================================
echo.
echo Your backend URL: https://%APP_NAME%.fly.dev
echo.
echo Next steps:
echo 1. Update frontend API_URL to: https://%APP_NAME%.fly.dev
echo 2. Test the app
echo.
pause
