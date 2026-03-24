# robotics-openproject-ai-bot — Telegram-бот для OpenProject
FROM python:3.12-slim

# ffmpeg для конвертации голосовых сообщений (Vosk)
RUN apt-get update && apt-get install -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Модель Vosk монтируется в /app/cache через volume (см. docker-compose)
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "-m", "app.main"]
