import os

from dotenv import load_dotenv

# Все параметры только из .env; override=True — значения из .env перезаписывают переменные окружения
load_dotenv(override=True)

# Настройки OpenProject API
OP_API_URL = os.getenv("OP_API_URL")
OP_API_KEY = os.getenv("OP_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# RKLLama (Ollama-совместимый API)
RKLLAMA_URL = os.getenv("RKLLAMA_URL") or None
RKLLAMA_MODEL = os.getenv("RKLLAMA_MODEL") or None

_raw_timeout = os.getenv("RKLLAMA_TIMEOUT")
RKLLAMA_TIMEOUT = int(_raw_timeout) if _raw_timeout and _raw_timeout.strip() else None

_raw_thinking = os.getenv("RKLLAMA_THINKING", "").strip().lower()
RKLLAMA_THINKING = _raw_thinking in ("1", "true", "yes", "on")

_raw_temp = os.getenv("RKLLAMA_TEMPERATURE", "").strip()
try:
    RKLLAMA_TEMPERATURE = float(_raw_temp) if _raw_temp else None
except ValueError:
    RKLLAMA_TEMPERATURE = None

_raw_tokens = os.getenv("RKLLAMA_MAX_NEW_TOKENS", "").strip()
try:
    _n = int(_raw_tokens) if _raw_tokens else 4096
    RKLLAMA_MAX_NEW_TOKENS = max(1, min(_n, 128_000))
except ValueError:
    RKLLAMA_MAX_NEW_TOKENS = 4096

# Провайдер LLM: rkllama или lm_studio
LLM_PROVIDER = os.getenv("LLM_PROVIDER") or (
    "rkllama" if RKLLAMA_URL else "lm_studio"
)

# Константы для состояний разговора
MENU, PROJECT_CHOICE, TASK_NAME, TASK_DESCRIPTION, ASSIGNEE_CHOICE, RESPONSIBLE_CHOICE, START_DATE, DUE_DATE, ESTIMATED_TIME = range(9)
CUSTOM_FIELD_NAME = "customField1"  # Замените на реальное имя