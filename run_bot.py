#!/usr/bin/env python3
"""
Script to run the Telegram bot
"""

import os
import sys
import subprocess

def main():
    """Run the Telegram bot"""
    # Change to the project directory
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)
    
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
    
    # Determine the correct Python executable
    if sys.platform.startswith('win'):
        python_exe = 'venv\\Scripts\\python'
    else:
        python_exe = 'venv/bin/python'
    
    # Run the bot
    try:
        print("🚀 Starting Telegram bot...")
        subprocess.run([python_exe, 'telegram_bot/bot.py'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running bot: {e}")
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")

if __name__ == "__main__":
    main()

