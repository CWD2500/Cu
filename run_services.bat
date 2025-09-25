@echo off
echo 🎓 Course Management Bot - Starting Services
echo ============================================

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if .env file exists
if not exist .env (
    echo ❌ .env file not found!
    echo Please copy env_example.txt to .env and configure it.
    pause
    exit /b 1
)

REM Run the services
echo 🚀 Starting services...
python run_services.py

pause

