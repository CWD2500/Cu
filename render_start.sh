#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "Installing minimal dependencies..."
pip install -r requirements_render.txt

cd django_backend

echo "Running migrations..."
python manage.py makemigrations
python manage.py migrate

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Telegram Bot in background..."
cd ..
python telegram_bot/bot.py &

echo "Starting Django Server..."
cd django_backend
gunicorn course_management.wsgi:application --bind 0.0.0.0:$PORT
