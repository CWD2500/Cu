#!/usr/bin/env python3
"""
Setup script for Course Management Telegram Bot
"""

import os
import subprocess
import sys

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e.stderr}")
        return False

def main():
    """Main setup function"""
    print("🚀 Setting up Course Management Telegram Bot...")
    
    # Check if Python is available
    if not run_command("python --version", "Checking Python installation"):
        print("❌ Python is not installed or not in PATH")
        return
    
    # Create virtual environment
    if not os.path.exists("venv"):
        if not run_command("python -m venv venv", "Creating virtual environment"):
            return
    else:
        print("✅ Virtual environment already exists")
    
    # Activate virtual environment and install requirements
    if sys.platform.startswith('win'):
        activate_cmd = "venv\\Scripts\\activate"
        pip_cmd = "venv\\Scripts\\pip"
    else:
        activate_cmd = "source venv/bin/activate"
        pip_cmd = "venv/bin/pip"
    
    if not run_command(f"{pip_cmd} install -r requirements.txt", "Installing Python dependencies"):
        return
    
    # Create .env file if it doesn't exist
    if not os.path.exists(".env"):
        if os.path.exists("env_example.txt"):
            run_command("copy env_example.txt .env" if sys.platform.startswith('win') else "cp env_example.txt .env", "Creating .env file")
            print("📝 Please edit .env file with your configuration")
        else:
            print("⚠️  env_example.txt not found, please create .env manually")
    
    # Django setup
    os.chdir("django_backend")
    
    if not run_command(f"{pip_cmd} install -r ../requirements.txt", "Installing Django dependencies"):
        return
    
    if not run_command("python manage.py makemigrations", "Creating Django migrations"):
        return
    
    if not run_command("python manage.py migrate", "Running Django migrations"):
        return
    
    print("\n🎉 Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Edit .env file with your database credentials and Telegram bot token")
    print("2. Create a superuser: python manage.py createsuperuser")
    print("3. Start Django server: python manage.py runserver")
    print("4. Start Telegram bot: python telegram_bot/bot.py")
    print("5. Add data through Django admin at http://localhost:8000/admin/")

if __name__ == "__main__":
    main()

