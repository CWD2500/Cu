#!/bin/bash
# شغّل البوت في الخلفية
python bot.py &

# شغّل Django مع Gunicorn
gunicorn course_bot_project.wsgi:application --bind 0.0.0.0:10000