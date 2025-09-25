@echo off
echo 🎓 Course Management Bot Setup
echo ================================

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

REM Run the setup script
echo 🚀 Running setup...
python create_superuser_and_run.py

pause

