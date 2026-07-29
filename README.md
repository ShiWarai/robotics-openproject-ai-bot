# robotics-openproject-ai-bot

Telegram-бот для работы с OpenProject: создание задач, учёт часов, расчёт времени сотрудников. Поддерживается произвольный ввод текста и голосовые сообщения (опционально — RKLLama или LM Studio).

## Стек технологий

| Категория       | Технологии                                                                 |
| --------------- | -------------------------------------------------------------------------- |
| Бот             | python-telegram-bot                                                        |
| API             | OpenProject REST API v3, requests                                          |
| Распознавание   | Whisper RKNN (голос), RKLLama / LM Studio (разбор произвольного текста)    |
| Конфигурация    | python-dotenv, .env                                                        |
| Инфраструктура  | Docker, Docker Compose                                                     |

## Оглавление

| Раздел                       | Содержание                                  |
| ---------------------------- | -------------------------------------------- |
| [Быстрый старт](#быстрый-старт) | Запуск за 3 шага                             |
| [Установка и запуск](#установка-и-запуск) | Docker, локально, RKLLama, Whisper          |
| [Возможности](#возможности)  | Создание задач, учёт часов, расчёт, доступ   |
| [Структура проекта](#структура-проекта) | Дерево каталогов                             |
| [Команды бота](#команды-бота) | /start, /cancel                              |
| [Лицензия](#лицензия)        | Использование                                |

---

## Быстрый старт

1. Скопируйте конфиг и заполните переменные:  
   `cp .env.example .env` — укажите `OP_API_URL`, `OP_API_KEY`, `TELEGRAM_TOKEN`.
2. При использовании RKLLama в отдельном проекте: в `.env` задайте `RKLLAMA_URL=http://rkllama:8080` и сначала запустите RKLLama (чтобы создалась сеть), затем бота.
3. Для голоса: поднимите [`whisper-rknn`](https://github.com/ShiWarai/whisper-rknn) (`WHISPER_RKNN_URL=http://whisper-rknn-api:9003`, сеть `whisper_rknn_default`).
4. Запуск (переменные подхватываются из `.env`; другой файл — `ENV_FILE=.env.prod docker compose up`):  
   `docker compose up`  

Остановка: `docker compose down`.

---

## Установка и запуск

### Docker (рекомендуется)

- Запуск: `docker compose up`. Сервис бота подключается к внешней сети `rkllama_default` для доступа к RKLLama (если используется).
- Переменные окружения задаются через `.env` (см. `.env.example`). Другой файл: `ENV_FILE=.env.prod docker compose up`.
- Сборка: `docker compose build`.

### Локальный запуск

```bash
cp .env.example .env
# Заполните OP_API_URL, OP_API_KEY, TELEGRAM_TOKEN и при необходимости RKLLAMA_*

pip install -r requirements.txt
python -m app.main
```

На системе должен быть **ffmpeg** (для голосовых сообщений): Linux — `sudo apt install ffmpeg`, Windows — https://ffmpeg.org

### RKLLama / Ollama (для произвольного ввода текста)

- **Отдельный проект RKLLama**: бот подключается к сети `rkllama_default`. В `.env` укажите `RKLLAMA_URL=http://rkllama:8080` (в контейнере rkllama слушает порт 8080). Сначала запустите RKLLama (`docker compose up -d` в каталоге этого проекта), затем бота.
- **На хосте**: в `.env` укажите `RKLLAMA_URL=http://host.docker.internal:11434`.

### Голосовой ввод (Whisper RKNN)

Бот отправляет голосовые сообщения в OpenAI-совместимый API [whisper-rknn](https://github.com/ShiWarai/whisper-rknn) (`POST /v1/audio/transcriptions`):

1. Сеть: `docker network create whisper_rknn_default` (один раз).
2. Клонируйте и запустите whisper-rknn: `docker compose up -d` (в `.env` сервиса задайте **`WHISPER_LANGUAGE=ru`** или другой код под ваше аудио).
3. В `.env` бота: `WHISPER_RKNN_URL=http://whisper-rknn-api:9003`.
4. Если в whisper-rknn включён `WHISPER_API_KEY` — продублируйте его в `.env` бота как `WHISPER_API_KEY`.

Контейнер бота уже подключён к внешней сети `whisper_rknn_default`.

---

## Возможности

### Создание задач

Выбор проекта → название и описание → ответственный и подотчётный → даты начала и окончания → оценка в часах. Задача создаётся в OpenProject через API.

### Учёт часов в задачу

- **Через меню**: проект → задача → дата → сотрудник → количество часов. Запись о времени создаётся в OpenProject.
- **Произвольный ввод**: текст или голосовое сообщение (например: «добавь 2 часа на завтра в тестовый проект на задачу починка бота»). Требуется запущенный RKLLama или LM Studio: бот отправляет запрос в LLM, получает структурированный ответ (проект, задача, часы, дата) и создаёт запись.

### Расчёт часов сотрудника

Выбор сотрудника из списка OpenProject → начальная и конечная дата периода → вывод суммарных часов за период.

### Доступ

В боте могут работать только пользователи, чей **Telegram ID** или **username** привязан в OpenProject (настраивается через кастомное поле в профиле пользователя).

---

## Структура проекта

```
robotics-openproject-ai-bot/
├── app/
│   ├── main.py              # Точка входа, ConversationHandler
│   ├── variables.py         # Конфигурация из .env
│   ├── states.py           # Состояния диалога (enum)
│   ├── calculate_hours/    # Сценарий «Рассчитать часы сотрудника»
│   ├── create_task/        # Сценарий «Создать задачу»
│   ├── estimated_time/     # Сценарий «Добавить часы» (меню + произвольный ввод)
│   └── utils/              # OpenProject API, календарь, Vosk, RKLLama/LM Studio
├── cache/                  # Модель Vosk (скачивается отдельно), временные файлы
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Команды бота

| Команда    | Описание                                              |
| ---------- | ----------------------------------------------------- |
| `/start`  | Начало работы, проверка привязки к OpenProject, меню  |
| `/cancel`  | Отмена текущего действия и возврат в главное меню     |

---

## Лицензия

См. [LICENSE](LICENSE).

_Проект создан с использованием нейросетей._
