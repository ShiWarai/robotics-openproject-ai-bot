import os

from dotenv import load_dotenv

# Все параметры только из .env; override=True — значения из .env перезаписывают переменные окружения
load_dotenv(override=True)

# Настройки OpenProject API
OP_API_URL = os.getenv('OP_API_URL')
OP_API_KEY = os.getenv('OP_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

# RKLLama (Ollama-совместимый API)
RKLLAMA_URL = os.getenv('RKLLAMA_URL')
RKLLAMA_MODEL = os.getenv('RKLLAMA_MODEL')

# Константы для состояний разговора
MENU, PROJECT_CHOICE, TASK_NAME, TASK_DESCRIPTION, ASSIGNEE_CHOICE, RESPONSIBLE_CHOICE, START_DATE, DUE_DATE, ESTIMATED_TIME = range(9)
CUSTOM_FIELD_NAME = "customField1"  # Замените на реальное имя