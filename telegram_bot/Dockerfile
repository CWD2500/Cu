FROM python:3.11-slim

WORKDIR /app

# Copy Requirements
COPY requirements.txt .

# Install dependencies needed for python telegram bot
RUN pip install --no-cache-dir -r requirements.txt

# Copy whole project into bot container
COPY . .

# Run the python telegram bot executable
CMD ["python", "telegram_bot/bot.py"]
