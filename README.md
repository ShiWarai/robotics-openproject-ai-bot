# robotics-openproject-ai-bot
Бот для добавления задачек в OpenProject

## Голосовой ввод
Для распознавания голоса нужна модель Vosk **vosk-model-small-ru-0.22**: скачайте с https://alphacephei.com/vosk/models и распакуйте в папку `cache/` в проекте.

На системе должен быть установлен **ffmpeg** (конвертация OGG → WAV):
- Linux: `sudo apt install ffmpeg`
- Windows: https://ffmpeg.org
