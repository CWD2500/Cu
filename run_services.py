#!/usr/bin/env python3
"""
Script to run both Django server and Telegram bot
"""

import os
import sys
import subprocess
import threading
import time

def run_django_server():
    """Run Django development server"""
    try:
        django_path = os.path.join(os.path.dirname(__file__), 'django_backend')
        os.chdir(django_path)
        
        print("🚀 Starting Django server...")
        print("📱 Admin panel: http://localhost:8000/admin/")
        print("🔗 API endpoints: http://localhost:8000/api/")
        
        subprocess.run([sys.executable, 'manage.py', 'runserver'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Django server error: {e}")
    except KeyboardInterrupt:
        print("Django server stopped")

def run_telegram_bot():
    """Run Telegram bot"""
    try:
        bot_path = os.path.join(os.path.dirname(__file__), 'telegram_bot', 'bot.py')
        
        print("🤖 Starting Telegram bot...")
        subprocess.run([sys.executable, bot_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Bot error: {e}")
    except KeyboardInterrupt:
        print("Telegram bot stopped")

def main():
    """Main function"""
    print("🎓 Course Management Bot - Starting Services")
    print("=" * 50)
    
    # Check if .env file exists
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_file):
        print("❌ .env file not found!")
        print("Please copy env_example.txt to .env and configure it.")
        return
    
    print("🚀 Starting both services...")
    print("Press Ctrl+C to stop all services")
    print()
    
    # Start Django server in a separate thread
    django_thread = threading.Thread(target=run_django_server, daemon=True)
    django_thread.start()
    
    # Wait a bit for Django to start
    time.sleep(3)
    
    # Start Telegram bot in the main thread
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        print("\n👋 All services stopped by user")

if __name__ == "__main__":
    main()

