#!/usr/bin/env python3
"""
Script to create Django superuser and run both services
"""

import os
import sys
import subprocess
import threading
import time
import django

def setup_django():
    """Setup Django environment"""
    # Add Django project to path
    django_path = os.path.join(os.path.dirname(__file__), 'django_backend')
    sys.path.append(django_path)
    
    # Set Django settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'course_management.settings')
    django.setup()

def create_superuser():
    """Create Django superuser"""
    try:
        from django.contrib.auth.models import User
        
        # Check if admin user already exists
        if User.objects.filter(username='admin').exists():
            print("✅ Superuser 'admin' already exists")
            return True
        
        # Create superuser
        User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin12345'
        )
        print("✅ Superuser 'admin' created successfully with password 'admin12345'")
        return True
        
    except Exception as e:
        print(f"❌ Error creating superuser: {e}")
        return False

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
    print("🎓 Course Management Bot Setup")
    print("=" * 40)
    
    # Check if .env file exists
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_file):
        print("❌ .env file not found!")
        print("Please copy env_example.txt to .env and configure it.")
        return
    
    # Setup Django
    print("🔄 Setting up Django...")
    setup_django()
    
    # Create superuser
    print("🔄 Creating superuser...")
    if not create_superuser():
        return
    
    print("\n🎉 Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Django admin: http://localhost:8000/admin/")
    print("2. Login with username: admin, password: admin12345")
    print("3. Add your course data through the admin panel")
    print("4. Start the Telegram bot to test")
    
    # Ask user if they want to start services
    choice = input("\n🚀 Start both services now? (y/n): ").lower().strip()
    
    if choice == 'y':
        print("\n🚀 Starting services...")
        print("Press Ctrl+C to stop all services")
        
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
    else:
        print("\n📝 To start services manually:")
        print("1. Django: cd django_backend && python manage.py runserver")
        print("2. Bot: python telegram_bot/bot.py")

if __name__ == "__main__":
    main()

