#!/usr/bin/env python3
"""
Script to run the Django development server
"""

import os
import sys
import subprocess

def main():
    """Run the Django development server"""
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
    
    # Change to Django backend directory
    django_dir = os.path.join(project_dir, 'django_backend')
    os.chdir(django_dir)
    
    # Run Django server
    try:
        print("🚀 Starting Django development server...")
        print("📱 Admin panel: http://localhost:8000/admin/")
        print("🔗 API endpoints: http://localhost:8000/api/")
        print("Press Ctrl+C to stop the server")
        subprocess.run([python_exe, 'manage.py', 'runserver'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running Django server: {e}")
    except KeyboardInterrupt:
        print("\n👋 Django server stopped by user")

if __name__ == "__main__":
    main()

