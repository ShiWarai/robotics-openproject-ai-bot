import json
import re
from datetime import datetime

import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from states import TimeStates
from utils.lm_studio_client import call_lm_studio
from utils.speech_recognition import process_voice_message
from utils.utils import show_main_menu, get_project_members
from variables import OP_API_URL, OP_API_KEY

SYSTEM_PROMPT_TEMPLATE = """
Вы — помощник, который анализирует текст на русском языке и извлекает информацию о рабочем времени для добавления в систему учета задач. Пользователь вводит текст, описывающий деятельность по задачам в проекте "{PROJECT_NAME}", например: "2 часа на Создать код вчера, 3 часа на Создать код". Ваша задача — извлечь данные для каждой упомянутой задачи и вернуть их в формате массива JSON-объектов. Если текст некорректен или не содержит достаточно информации, верните JSON с ошибкой.

**Поля и их обязательность (для каждой задачи)**:
- hours: количество часов (обязательное, число, например, 3 или 2.5)
- task_name: название задачи (обязательное, должно **точно** совпадать с одним из названий задач из списка, без изменений или перефразировки; например, если в списке есть "Создать код", то "создание кода" или "код" должны сопоставляться с "Создать код")
- date: дата в формате YYYY-MM-DD (обязательное, если указано "сегодня" — использовать 2025-04-22; если "вчера" — использовать 2025-04-21; если указана конкретная дата — использовать её; если дата не указана — использовать текущую дату 2025-04-22; если есть предыдущая задача в тексте, наследовать её дату)

**Данные проекта "{PROJECT_NAME}"**:
- Задачи: {TASKS}
- Пользователи: {USERS}

**Правила**:
- Текст может содержать несколько задач, разделенных словами "и", "а также", запятыми, "после чего" или другими перечислениями.
- Поле project_name не извлекается, так как проект уже известен ("{PROJECT_NAME}").
- Для каждой задачи извлечь все обязательные поля.
- Название задачи в тексте (например, "создание кода") должно строго сопоставляться с названием из списка задач (например, "Создать код") и возвращать его без изменений.
- Если hours не является положительным числом, вернуть ошибку.
- Если task_name не соответствует ни одному названию из списка задач, вернуть ошибку.
- Если date не удалось извлечь или она некорректна, вернуть ошибку.
- Если текст не содержит осмысленных данных (например, случайные слова), вернуть ошибку.
- Формат ошибки: {{ "error": "описание ошибки, какие поля отсутствуют или некорректны для какой задачи" }}
- Вернуть только JSON (массив объектов или объект с ошибкой), без дополнительного текста.

**Примеры**:
1. Ввод: "2 часа на Создать код вчера, 3 часа на Создать код"
   Вывод: [
     {{ "hours": 2, "task_name": "Создать код", "date": "2025-04-21" }},
     {{ "hours": 3, "task_name": "Создать код", "date": "2025-04-21" }}
   ]
2. Ввод: "3 часа на создание кода сегодня"
   Вывод: [
     {{ "hours": 3, "task_name": "Создать код", "date": "2025-04-22" }}
   ]
3. Ввод: "2 часа на Создать код"
   Вывод: [
     {{ "hours": 2, "task_name": "Создать код", "date": "2025-04-22" }}
   ]
4. Ввод: "2 часа над чем-то"
   Вывод: {{ "error": "Название задачи не указано или не соответствует списку задач" }}
5. Ввод: "-1 час на Создать код"
   Вывод: {{ "error": "Количество часов должно быть положительным числом для задачи 'Создать код'" }}
6. Ввод: "fhdasf difjhads"
   Вывод: {{ "error": "Текст не содержит осмысленной информации о задачах или часах" }}

Текущая дата: {DATE}

Текст для анализа: "{TEXT}"
"""

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка текстового или голосового ввода для добавления часов."""
    user_input = None
    input_type = "текстового"

    # Проверяем, является ли сообщение голосовым
    if update.message.voice:
        try:
            user_input = await process_voice_message(update, context)
            input_type = "голосового"
            await update.message.reply_text(f"Распознанный текст: {user_input}")
        except Exception as e:
            await update.message.reply_text(f"Ошибка распознавания голосового сообщения: {str(e)}")
            return TimeStates.TEXT_INPUT.value
    else:
        user_input = update.message.text

    project_id = context.user_data['project_id']
    project_name = context.user_data['project_name']
    tasks = context.user_data['tasks']

    # Получение Telegram ID текущего пользователя
    telegram_id = str(update.message.from_user.username)

    # Поиск user_id в USER_TELEGRAM_IDS
    user_id = context.bot_data.get('USER_TELEGRAM_IDS', {}).get(telegram_id)
    if not user_id:
        await update.message.reply_text("Ваш Telegram ID не зарегистрирован в OpenProject. Обратитесь к администратору.")
        return TimeStates.TEXT_INPUT.value

    # Получение пользователей проекта
    members = get_project_members(project_id)
    if not members or "_embedded" not in members or not members["_embedded"]["elements"]:
        await update.message.reply_text("Не удалось загрузить участников проекта.")
        return await show_main_menu(update, context)

    project_users = [
        {"id": m["_links"]["principal"]["href"].split("/")[-1], "name": m["_links"]["principal"].get("title", f"User {m['_links']['principal']['href'].split('/')[-1]}")}
        for m in members["_embedded"]["elements"] if "principal" in m["_links"]
    ]

    # Проверка, что пользователь является участником проекта
    if not any(user['id'] == str(user_id) for user in project_users):
        await update.message.reply_text("Вы не являетесь участником этого проекта. Обратитесь к администратору.")
        return TimeStates.TEXT_INPUT.value

    # Формирование списков для промта
    task_list = [{"id": str(t["id"]), "name": t["subject"]} for t in tasks]
    user_names = [u["name"] for u in project_users]

    # Отладочный вывод
    print(f"Project: {project_name}")
    print(f"Tasks: {json.dumps(task_list, ensure_ascii=False)}")
    print(f"Users: {json.dumps(user_names, ensure_ascii=False)}")
    print(f"Input ({input_type}): {user_input}")
    print(f"Selected user_id: {user_id} for Telegram ID: {telegram_id}")

    # Формирование промта
    try:
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            PROJECT_NAME=project_name,
            TASKS=json.dumps(task_list, ensure_ascii=False),
            USERS=json.dumps(user_names, ensure_ascii=False),
            DATE=datetime.now().strftime("%Y-%m-%d"),
            TEXT=user_input
        )
        print(f"Generated prompt: {prompt}")
    except KeyError as e:
        print(f"KeyError in prompt formatting: {e}")
        await update.message.reply_text("Ошибка формирования запроса к модели. Обратитесь к администратору.")
        return TimeStates.TEXT_INPUT.value

    # Вызов LM Studio
    parsed_data = await call_lm_studio(prompt, user_input)
    print(f"LM Studio response: {parsed_data}")

    # Удаление markdown-обертки (на случай, если она есть)
    parsed_data = re.sub(r'^```json\n|\n```$', '', parsed_data.strip())

    try:
        data = json.loads(parsed_data)
        if isinstance(data, dict) and "error" in data:
            await update.message.reply_text(f"Ошибка: {data['error']}. Пожалуйста, уточните запрос.")
            return TimeStates.TEXT_INPUT.value
        if not isinstance(data, list):
            await update.message.reply_text("Ошибка: Неверный формат данных. Ожидается список задач.")
            return TimeStates.TEXT_INPUT.value

        # Обработка каждой задачи
        for entry in data:
            # Проверка обязательных полей
            required_fields = ['hours', 'task_name', 'date']
            if not all(field in entry for field in required_fields):
                await update.message.reply_text(f"Ошибка: Отсутствуют обязательные поля для одной из задач.")
                return TimeStates.TEXT_INPUT.value

            # Проверка hours
            try:
                hours = float(entry['hours'])
                if hours <= 0:
                    await update.message.reply_text(f"Ошибка: Количество часов должно быть положительным для задачи '{entry['task_name']}'.")
                    return TimeStates.TEXT_INPUT.value
            except (ValueError, TypeError):
                await update.message.reply_text(f"Ошибка: Некорректное значение часов для задачи '{entry['task_name']}'.")
                return TimeStates.TEXT_INPUT.value

            # Проверка task_name
            selected_task = next((t for t in tasks if t["subject"].lower() == entry['task_name'].lower()), None)
            if not selected_task:
                await update.message.reply_text(f"Ошибка: Задача '{entry['task_name']}' не найдена в проекте '{project_name}'.")
                return TimeStates.TEXT_INPUT.value

            # Отправка запроса в OpenProject
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
                await update.message.reply_text(f"Ошибка при добавлении часов для задачи '{entry['task_name']}': {response.text}")
                return TimeStates.TEXT_INPUT.value

        # Если все запросы успешны
        await update.message.reply_text("Все часы успешно добавлены!")
        keyboard = [["Добавить еще часы"], ["Вернуться в меню"]]
        await update.message.reply_text(
            "Хотите добавить еще часы для другого проекта или задачи?",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return TimeStates.ADD_ANOTHER_TIME.value

    except json.JSONDecodeError as e:
        print(f"JSONDecodeError: {e}")
        print(f"Raw response: {parsed_data}")
        await update.message.reply_text("Ошибка обработки данных от модели. Попробуйте снова.")
        return TimeStates.TEXT_INPUT.value