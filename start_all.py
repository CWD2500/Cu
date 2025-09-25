#!/usr/bin/env python3
"""
Script to start both Django server and Telegram bot
"""

import os
import sys
import subprocess
import threading
import time

def run_django():
    """Run Django server in a separate thread"""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    django_dir = os.path.join(project_dir, 'django_backend')
    
    if sys.platform.startswith('win'):
        python_exe = os.path.join(project_dir, 'venv\\Scripts\\python')
    else:
        python_exe = os.path.join(project_dir, 'venv/bin/python')
    
    os.chdir(django_dir)
    try:
        subprocess.run([python_exe, 'manage.py', 'runserver'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Django server error: {e}")
    except KeyboardInterrupt:
        print("Django server stopped")

def run_bot():
    """Run Telegram bot in a separate thread"""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    
    if sys.platform.startswith('win'):
        python_exe = os.path.join(project_dir, 'venv\\Scripts\\python')
    else:
        python_exe = os.path.join(project_dir, 'venv/bin/python')
    
    os.chdir(project_dir)
    try:
        subprocess.run([python_exe, 'telegram_bot/bot.py'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Bot error: {e}")
    except KeyboardInterrupt:
        print("Telegram bot stopped")

def main():
    """Start both Django and Telegram bot"""
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("❌ .env file not found!")
        print("Please copy env_example.txt to .env and configure it with your settings.")
        return
    
    # Check if virtual environment exists
    if not os.path.exists('venv'):
        print("❌ Virtual environment not found!")
        print("Please run setup.py first to set up the environment.")
        return
    
    print("🚀 Starting Course Management System...")
    print("📱 Django admin: http://localhost:8000/admin/")
    print("🔗 API endpoints: http://localhost:8000/api/")
    print("🤖 Telegram bot will start shortly...")
    print("Press Ctrl+C to stop all services")
    
    # Start Django server in a separate thread
    django_thread = threading.Thread(target=run_django, daemon=True)
    django_thread.start()
    
    # Wait a bit for Django to start
    time.sleep(3)
    
    # Start Telegram bot in the main thread
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 All services stopped by user")

if __name__ == "__main__":
    main()

