import json
import logging
import re
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from app.states import TimeStates
from app.utils.lm_studio_client import call_lm_studio
from app.utils.rkllama_client import call_rkllama
from app.utils.speech_recognition import process_voice_message
from app.utils.utils import show_main_menu, get_project_members, get_project_tasks
from app.variables import OP_API_URL, OP_API_KEY, LLM_PROVIDER


async def _call_llm(
    system_prompt: str,
    user_input: str,
    *,
    format_schema: Optional[dict] = None,
) -> str:
    """Вызов выбранного провайдера LLM. format_schema передаётся только в rkllama."""
    if LLM_PROVIDER == "rkllama":
        return await call_rkllama(system_prompt, user_input, format_schema=format_schema)
    return await call_lm_studio(system_prompt, user_input)


def _strip_json_response(text: str) -> str:
    """Убирает обёртку ```json ... ``` из ответа модели. Шаблон вывода даёт только JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


# Коды ошибок от модели: по коду показываем пользователю текст (без передачи сырого текста от LLM)
PROJECT_ERROR_MESSAGES = {
    1: "Проект не указан или не соответствует списку проектов.",
}
HOURS_ERROR_MESSAGES = {
    1: "Название задачи не указано или не соответствует списку задач.",
    2: "Количество часов должно быть положительным числом.",
    3: "Текст не содержит осмысленной информации о задачах или часах.",
}

# Схема ответа «проект»: project_id (число, id из списка) или error_code (при ошибке)
FORMAT_PROJECT = {
    "type": "object",
    "properties": {
        "project_id": {"type": "integer", "description": "id проекта из списка"},
        "error_code": {"type": "integer", "description": "Код ошибки, если проект не определён"},
    },
}

# Ответ «часы»: entries (массив с task_id, hours, date) или error_code
FORMAT_HOURS = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "description": "Список записей о часах",
            "items": {
                "type": "object",
                "properties": {
                    "hours": {"type": "number", "description": "Количество часов"},
                    "task_id": {"type": "integer", "description": "id задачи из списка"},
                    "date": {"type": "string", "description": "Дата YYYY-MM-DD"},
                },
                "required": ["hours", "task_id", "date"],
            },
        },
        "error_code": {"type": "integer", "description": "Код ошибки, если данные некорректны"},
    },
}

# Текстовое представление схем для подстановки в промпты (корректировка и др.)
SCHEMA_PROJECT_JSON = json.dumps(FORMAT_PROJECT, ensure_ascii=False, indent=2)
SCHEMA_HOURS_JSON = json.dumps(FORMAT_HOURS, ensure_ascii=False, indent=2)

# Промпт для корректировки ответа под требуемый шаблон (один повторный вызов при неверном формате)
# Подставлять: SCHEMA, CONTEXT (список проектов или задач), RAW (сырой ответ модели)
CORRECTION_PROMPT = (
    "Твой предыдущий ответ не соответствует требуемому формату.\n"
    "Требуемая JSON Schema:\n{SCHEMA}\n\n"
    "{CONTEXT}\n"
    "Твой ответ: {RAW}\n"
    "Исправь и верни только один JSON-объект, без пояснений."
)


PROJECT_PROMPT_TEMPLATE = """
Вы — помощник, который по тексту пользователя определяет, к какому проекту из списка он обращается. Вернуть в JSON **project_id** (число — id из списка ниже) или **error_code**: 1, если проект не указан или не совпадает ни с одним из списка.

**Критично**: вернуть id **того** проекта, **название** которого пользователь имел в виду (сопоставление по смыслу: «тестовый проект» → проект с названием «Тестовый проект» в списке; «разработка робота» → «Разработка робота» и т.д.). Смотри на список — у каждого проекта свой id; подставлять нужно id именно того проекта, чьё название подходит под формулировку пользователя.

**Список проектов** (id и название):
{PROJECTS}

**Правила**:
- Найти в списке проект, название которого совпадает или ближе всего к упомянутому в тексте. Вернуть в project_id **именно его id** из столбца id.
- Если проект не указан или не соответствует ни одному названию из списка — {{ "error_code": 1 }}.
- Ответ — только один JSON-объект, без пояснений.

**Примеры** (id в примерах условные; в реальности смотри список выше):
- Текст: "добавь часы в тестовый проект" → в списке есть «Тестовый проект» с id 7 → Вывод: {{ "project_id": 7 }}
- Текст: "2 часа в проекте Разработка робота" → в списке есть «Разработка робота» с id 12 → Вывод: {{ "project_id": 12 }}
- Текст: "2 часа на Создать код" (проект не назван) → Вывод: {{ "error_code": 1 }}

Текст для анализа: "{TEXT}"
"""

SYSTEM_PROMPT_TEMPLATE = """
Вы — помощник, который извлекает информацию о рабочем времени для учёта задач. Проект уже выбран: "{PROJECT_NAME}". Вернуть в JSON массив записей (поле entries) или код ошибки (поле error_code).

**Поля каждой записи в entries**:
- hours: число, количество часов (обязательно)
- task_id: число (integer), **id** задачи из списка (обязательно). Текст сопоставлять по смыслу с названиями задач; подставлять **id** выбранной задачи из списка.
- date: строка YYYY-MM-DD (обязательно; «сегодня»/«вчера» → дата)

**Коды ошибок** (error_code): 1 — задача не указана или не из списка; 2 — часы не положительное число; 3 — текст не содержит осмысленной информации.

**Задачи проекта** (id и название):
{TASKS}

**Правила**:
- Фразы «добавь N часов», «запиши N часов», «N часов на задачу X» — hours = N.
- В каждой записи указывать **task_id** (id из списка задач), не название. Задачу из текста сопоставлять по смыслу («починка бота» → задача «Починить бота» → подставить её id).
- Если задача не определена или не из списка — {{ "error_code": 1 }}.
- Если часы не положительное число — {{ "error_code": 2 }}.
- Если текст бессмысленный — {{ "error_code": 3 }}.
- Вернуть только JSON: объект с «entries» (массив объектов с hours, task_id, date) или с «error_code».

**Примеры** (id в примерах условные):
- "2 часа на Создать код вчера" при задаче «Создать код» id 101 → {{ "entries": [ {{ "hours": 2, "task_id": 101, "date": "2025-04-21" }} ] }}
- "добавь два часа, починка бота" при задаче «Починить бота» id 102 → {{ "entries": [ {{ "hours": 2, "task_id": 102, "date": "{DATE}" }} ] }}
- "2 часа над чем-то" → {{ "error_code": 1 }}
- "-1 час на Создать код" → {{ "error_code": 2 }}
- "fhdasf difjhads" → {{ "error_code": 3 }}

Текущая дата: {DATE}

Текст для анализа: "{TEXT}"
"""

async def handle_free_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка произвольного текстового или голосового ввода для определения проекта."""
    user_input = None
    input_type = "текстового"

    # Проверяем, является ли сообщение голосовым
    if update.message.voice:
        try:
            user_input = await process_voice_message(update, context)
            input_type = "голосового"
            await update.message.reply_text(f"Распознанный текст: {user_input}")
        except Exception as e:
            msg = str(e)
            if "ffmpeg" in msg.lower():
                msg = (
                    "Для голосовых сообщений нужен ffmpeg. "
                    "Установите: sudo apt install ffmpeg (Linux) или скачайте с https://ffmpeg.org (Windows)."
                )
            else:
                msg = f"Ошибка распознавания голосового сообщения: {msg}"
            await update.message.reply_text(msg)
            return TimeStates.FREE_TEXT_INPUT.value
    else:
        user_input = update.message.text

    projects = context.user_data['projects']
    project_list = [{"id": int(p["id"]), "name": p["name"]} for p in projects]

    # Формирование промта для определения проекта
    try:
        prompt = PROJECT_PROMPT_TEMPLATE.format(
            PROJECTS=json.dumps(project_list, ensure_ascii=False),
            TEXT=user_input
        )
    except KeyError as e:
        logger.exception("KeyError в промпте проекта")
        await update.message.reply_text("Ошибка формирования запроса к модели. Обратитесь к администратору.")
        return TimeStates.FREE_TEXT_INPUT.value

    logger.info("Обработка: проект, сообщение: %s", user_input)
    raw_response = await _call_llm(prompt, user_input, format_schema=FORMAT_PROJECT)
    json_str = _strip_json_response(raw_response)
    correction_used = False

    while True:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            if not correction_used:
                logger.warning("Проект: неверный JSON, запрос на корректировку")
                correction_used = True
                raw_response = await _call_llm(
                    "Ты исправляешь ответ в валидный JSON по заданному шаблону. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_PROJECT_JSON,
                        CONTEXT="Список проектов: " + json.dumps(project_list, ensure_ascii=False),
                        RAW=raw_response,
                    ),
                    format_schema=FORMAT_PROJECT,
                )
                json_str = _strip_json_response(raw_response)
                continue
            logger.error("Ошибка разбора JSON (проект): %s. Ответ (фрагмент): %s", e, raw_response[:500])
            await update.message.reply_text("Ошибка обработки данных от модели. Попробуйте снова.")
            return TimeStates.FREE_TEXT_INPUT.value

        # Ошибка связи с LLM (RKLLama/LM Studio недоступен) — не путать с «неверный формат»
        if isinstance(data, dict) and "error" in data:
            logger.warning("Проект: ошибка сервиса LLM — %s", data.get("error", ""))
            await update.message.reply_text(
                "Сервис распознавания текста временно недоступен. Проверьте, что RKLLama/Ollama запущен, или выберите «Через меню» для добавления часов."
            )
            return TimeStates.FREE_TEXT_INPUT.value

        error_code = data.get("error_code") if isinstance(data, dict) else None
        if isinstance(data, dict) and error_code is not None and error_code in PROJECT_ERROR_MESSAGES:
            logger.warning("Проект: ошибка от модели — код %s", error_code)
            project_names = [p["name"] for p in projects]
            project_list_text = "\n".join(f"- {name}" for name in project_names)
            msg = PROJECT_ERROR_MESSAGES[error_code]
            await update.message.reply_text(
                f"Ошибка: {msg}\n\nДоступные проекты:\n{project_list_text}\n"
                "Пожалуйста, укажите один из этих проектов в запросе."
            )
            return TimeStates.FREE_TEXT_INPUT.value
        _pid = data.get("project_id") if isinstance(data, dict) else None
        if not isinstance(data, dict) or "project_id" not in data or (
            _pid is None or (isinstance(_pid, str) and not _pid.strip())
        ):
            if not correction_used:
                logger.warning("Проект: неверный формат, запрос на корректировку")
                correction_used = True
                raw_response = await _call_llm(
                    "Ты исправляешь ответ в валидный JSON по заданному шаблону. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_PROJECT_JSON,
                        CONTEXT="Список проектов: " + json.dumps(project_list, ensure_ascii=False),
                        RAW=raw_response,
                    ),
                    format_schema=FORMAT_PROJECT,
                )
                json_str = _strip_json_response(raw_response)
                continue
            logger.warning("Проект: неверный формат данных (ожидается project_id), получено: %s", data)
            project_names = [p["name"] for p in projects]
            project_list_text = "\n".join(f"- {name}" for name in project_names)
            await update.message.reply_text(
                f"Ошибка: Неверный формат данных. Ожидается project_id (id проекта).\n\nДоступные проекты:\n{project_list_text}\n"
                "Пожалуйста, укажите один из этих проектов в запросе."
            )
            return TimeStates.FREE_TEXT_INPUT.value
        break

    raw_id = data.get("project_id")
    if raw_id is None or (isinstance(raw_id, str) and not raw_id.strip()):
        raw_id = None
    else:
        try:
            raw_id = int(raw_id) if not isinstance(raw_id, int) else raw_id
        except (TypeError, ValueError):
            raw_id = str(raw_id).strip() if raw_id else None
    _raw = raw_response[:2000] + "..." if len(raw_response) > 2000 else raw_response
    logger.info("Проект: ответ модели: %s", _raw)
    logger.info("Проект: результат модели — %s", data)
    selected_project = next(
        (p for p in projects if (p["id"] == raw_id if isinstance(raw_id, int) else str(p["id"]) == str(raw_id))),
        None,
    ) if raw_id is not None else None
    if not selected_project:
        logger.warning("Проект: project_id %s не найден в списке", raw_id)
        project_names = [p["name"] for p in projects]
        project_list_text = "\n".join(f"- {name}" for name in project_names)
        await update.message.reply_text(
            f"Ошибка: Проект не найден.\n\nДоступные проекты:\n{project_list_text}\n"
            "Пожалуйста, укажите один из этих проектов в запросе."
        )
        return TimeStates.FREE_TEXT_INPUT.value

    project_name = selected_project["name"]
    context.user_data['project_id'] = selected_project['id']
    context.user_data['project_name'] = project_name
    logger.info("Проект: выбран %s (id %s)", project_name, selected_project['id'])

    tasks = get_project_tasks(selected_project['id'])
    if not tasks:
        await update.message.reply_text(f"В проекте '{project_name}' нет задач.")
        return await show_main_menu(update, context)
    context.user_data['tasks'] = tasks

    members = get_project_members(selected_project['id'])
    if not members or "_embedded" not in members or not members["_embedded"]["elements"]:
        await update.message.reply_text(f"Не удалось загрузить участников проекта '{project_name}'.")
        return await show_main_menu(update, context)

    project_users = [
        {"id": m["_links"]["principal"]["href"].split("/")[-1], "name": m["_links"]["principal"].get("title", f"User {m['_links']['principal']['href'].split('/')[-1]}")}
        for m in members["_embedded"]["elements"] if "principal" in m["_links"]
    ]
    context.user_data['project_users'] = project_users

    return await handle_text_input(update, context, user_input, input_type)

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str, input_type: str) -> int:
    """Обработка текстового или голосового ввода для добавления часов."""
    project_id = context.user_data['project_id']
    project_name = context.user_data['project_name']
    tasks = context.user_data['tasks']
    project_users = context.user_data['project_users']

    # Получение Telegram ID текущего пользователя
    telegram_id = str(update.message.from_user.username)

    # Поиск user_id в USER_TELEGRAM_IDS
    user_id = context.bot_data.get('USER_TELEGRAM_IDS', {}).get(telegram_id)
    if not user_id:
        await update.message.reply_text("Ваш Telegram ID не зарегистрирован в OpenProject. Обратитесь к администратору.")
        return TimeStates.FREE_TEXT_INPUT.value

    # Проверка, что пользователь является участником проекта
    if not any(user['id'] == str(user_id) for user in project_users):
        await update.message.reply_text("Вы не являетесь участником этого проекта. Обратитесь к администратору.")
        return TimeStates.FREE_TEXT_INPUT.value

    # Формирование списков для промта
    task_list = [{"id": int(t["id"]), "name": t["subject"]} for t in tasks]
    user_names = [u["name"] for u in project_users]

    # Формирование промта для извлечения часов
    try:
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            PROJECT_NAME=project_name,
            TASKS=json.dumps(task_list, ensure_ascii=False),
            # USERS=json.dumps(user_names, ensure_ascii=False),
            DATE=datetime.now().strftime("%Y-%m-%d"),
            TEXT=user_input
        )
    except KeyError as e:
        logger.exception("KeyError в промпте часов")
        await update.message.reply_text("Ошибка формирования запроса к модели. Обратитесь к администратору.")
        return TimeStates.FREE_TEXT_INPUT.value

    logger.info("Обработка: часы, сообщение: %s", user_input)
    raw_response = await _call_llm(prompt, user_input, format_schema=FORMAT_HOURS)
    json_str = _strip_json_response(raw_response)
    correction_used = False

    while True:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            if not correction_used:
                logger.warning("Часы: неверный JSON, запрос на корректировку")
                correction_used = True
                raw_response = await _call_llm(
                    "Ты исправляешь ответ в валидный JSON по заданному шаблону. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_HOURS_JSON,
                        CONTEXT="Задачи проекта: " + json.dumps(task_list, ensure_ascii=False),
                        RAW=raw_response,
                    ),
                    format_schema=FORMAT_HOURS,
                )
                json_str = _strip_json_response(raw_response)
                continue
            logger.error("Ошибка разбора JSON (часы): %s. Ответ (фрагмент): %s", e, raw_response[:500])
            await update.message.reply_text("Ошибка обработки данных от модели. Попробуйте снова.")
            return TimeStates.FREE_TEXT_INPUT.value

        # Ошибка связи с LLM — не путать с «неверный формат»
        if isinstance(data, dict) and "error" in data:
            logger.warning("Часы: ошибка сервиса LLM — %s", data.get("error", ""))
            await update.message.reply_text(
                "Сервис распознавания текста временно недоступен. Проверьте, что RKLLama/Ollama запущен, или выберите «Через меню» для добавления часов."
            )
            return TimeStates.FREE_TEXT_INPUT.value

        if not isinstance(data, dict):
            if not correction_used:
                logger.warning("Часы: неверный формат (ответ не объект), запрос на корректировку")
                correction_used = True
                raw_response = await _call_llm(
                    "Ты исправляешь ответ в валидный JSON по заданному шаблону. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_HOURS_JSON,
                        CONTEXT="Задачи проекта: " + json.dumps(task_list, ensure_ascii=False),
                        RAW=raw_response,
                    ),
                    format_schema=FORMAT_HOURS,
                )
                json_str = _strip_json_response(raw_response)
                continue
            logger.warning("Часы: неверный формат (ответ не объект)")
            task_names = [t["subject"] for t in tasks]
            task_list_text = "\n".join(f"- {name}" for name in task_names)
            await update.message.reply_text(
                f"Ошибка: Неверный формат данных. Ожидается объект с полем «entries» или «error_code».\n\nДоступные задачи в проекте '{project_name}':\n{task_list_text}\n"
                "Пожалуйста, укажите одну из этих задач в запросе."
            )
            return TimeStates.FREE_TEXT_INPUT.value

        error_code = data.get("error_code")
        if error_code is not None and error_code in HOURS_ERROR_MESSAGES:
            logger.warning("Часы: ошибка от модели — код %s", error_code)
            task_names = [t["subject"] for t in tasks]
            task_list_text = "\n".join(f"- {name}" for name in task_names)
            msg = HOURS_ERROR_MESSAGES[error_code]
            await update.message.reply_text(
                f"Ошибка: {msg}\n\nДоступные задачи в проекте '{project_name}':\n{task_list_text}\n"
                "Пожалуйста, укажите одну из этих задач в запросе."
            )
            return TimeStates.FREE_TEXT_INPUT.value

        if "entries" not in data or not isinstance(data["entries"], list):
            if not correction_used:
                logger.warning("Часы: неверный формат (нет entries), запрос на корректировку")
                correction_used = True
                raw_response = await _call_llm(
                    "Ты исправляешь ответ в валидный JSON по заданному шаблону. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_HOURS_JSON,
                        CONTEXT="Задачи проекта: " + json.dumps(task_list, ensure_ascii=False),
                        RAW=raw_response,
                    ),
                    format_schema=FORMAT_HOURS,
                )
                json_str = _strip_json_response(raw_response)
                continue
            logger.warning("Часы: неверный формат (нет поля entries или не массив)")
            task_names = [t["subject"] for t in tasks]
            task_list_text = "\n".join(f"- {name}" for name in task_names)
            await update.message.reply_text(
                f"Ошибка: Неверный формат данных. Ожидается объект с полем «entries» (массив задач) или «error_code».\n\nДоступные задачи в проекте '{project_name}':\n{task_list_text}\n"
                "Пожалуйста, укажите одну из этих задач в запросе."
            )
            return TimeStates.FREE_TEXT_INPUT.value
        break

    _raw = raw_response[:2000] + "..." if len(raw_response) > 2000 else raw_response
    logger.info("Часы: ответ модели: %s", _raw)
    entries = data["entries"]

    # Список для хранения сводки
    summary = []

    # Обработка каждой задачи
    for entry in entries:
        required_fields = ['hours', 'task_id', 'date']
        if not all(field in entry for field in required_fields):
            logger.warning("Часы: отсутствуют обязательные поля в записи %s", entry)
            task_names = [t["subject"] for t in tasks]
            task_list_text = "\n".join(f"- {name}" for name in task_names)
            await update.message.reply_text(
                f"Ошибка: Отсутствуют обязательные поля для одной из задач.\n\nДоступные задачи в проекте '{project_name}':\n{task_list_text}\n"
                "Пожалуйста, уточните запрос."
            )
            return TimeStates.FREE_TEXT_INPUT.value

        try:
            hours = float(entry['hours'])
            if hours <= 0:
                task_names = [t["subject"] for t in tasks]
                task_list_text = "\n".join(f"- {name}" for name in task_names)
                await update.message.reply_text(
                    f"Ошибка: Количество часов должно быть положительным.\n\n"
                    f"Доступные задачи в проекте '{project_name}':\n{task_list_text}\n"
                    "Пожалуйста, уточните запрос."
                )
                return TimeStates.FREE_TEXT_INPUT.value
        except (ValueError, TypeError):
            task_names = [t["subject"] for t in tasks]
            task_list_text = "\n".join(f"- {name}" for name in task_names)
            await update.message.reply_text(
                "Ошибка: Некорректное значение часов.\n\n"
                f"Доступные задачи в проекте '{project_name}':\n{task_list_text}\n"
                "Пожалуйста, уточните запрос."
            )
            return TimeStates.FREE_TEXT_INPUT.value

        raw_tid = entry.get("task_id")
        if raw_tid is not None:
            try:
                raw_tid = int(raw_tid) if not isinstance(raw_tid, int) else raw_tid
            except (TypeError, ValueError):
                raw_tid = str(raw_tid).strip() if raw_tid else None
        selected_task = next(
            (t for t in tasks if (t["id"] == raw_tid if isinstance(raw_tid, int) else str(t["id"]) == str(raw_tid))),
            None,
        ) if raw_tid is not None else None
        if not selected_task:
            logger.warning("Часы: task_id %s не найден в проекте '%s'", raw_tid, project_name)
            task_names = [t["subject"] for t in tasks]
            task_list_text = "\n".join(f"- {name}" for name in task_names)
            await update.message.reply_text(
                f"Ошибка: Задача не найдена в проекте '{project_name}'.\n\n"
                f"Доступные задачи:\n{task_list_text}\n"
                "Пожалуйста, укажите одну из этих задач в запросе."
            )
            return TimeStates.FREE_TEXT_INPUT.value

        task_subject = selected_task["subject"]
        payload = {
            "hours": f"PT{hours}H",
            "spentOn": entry['date'],
            "comment": {"raw": f"Создано ботом на основе {input_type} ввода: {user_input}"},
            "_links": {
                "workPackage": {"href": f"/api/v3/work_packages/{selected_task['id']}"},
                "user": {"href": f"/api/v3/users/{user_id}"},
                "project": {"href": f"/api/v3/projects/{project_id}"}
            }
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(f"{OP_API_URL}/time_entries", headers=headers, json=payload, auth=("apikey", OP_API_KEY))
        if response.status_code != 201:
            logger.warning("Часы: OpenProject вернул %s для задачи '%s' — %s", response.status_code, task_subject, response.text)
            await update.message.reply_text(f"Ошибка при добавлении часов для задачи '{task_subject}': {response.text}")
            return TimeStates.FREE_TEXT_INPUT.value

        summary.append(f"• {hours} ч — задача «{task_subject}», проект «{project_name}», {entry['date']}")

    # Отправка сводки
    summary_text = "\n".join(summary)
    logger.info("Часы: добавлено записей: %d. Сводка: %s", len(entries), summary_text)
    await update.message.reply_text(f"Все часы успешно добавлены!\n\nСводка:\n{summary_text}")

    # Запрос на добавление еще часов
    keyboard = [["Добавить еще часы"], ["Вернуться в меню"]]
    await update.message.reply_text(
        "Хотите добавить еще часы для другого проекта или задачи?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return TimeStates.ADD_ANOTHER_TIME.value