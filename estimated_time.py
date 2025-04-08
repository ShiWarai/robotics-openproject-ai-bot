from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
import requests
from variables import *
from typing import Optional
from variables import OP_API_URL, OP_API_KEY
from create_task import get_project_members, CustomCalendar

# Новые состояния для ConversationHandler
PROJECT_CHOICE_TIME = 100
TASK_CHOICE_TIME = 101
DATE_CHOICE_TIME = 102
ACTIVITY_TYPE_TIME = 103
PERSON_CHOICE_TIME = 104
HOURS_INPUT_TIME = 105

def get_openproject_projects() -> Optional[dict]:
    """Получение списка проектов"""
    url = f"{OP_API_URL}/projects"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()
    return None

def get_project_tasks(project_id: str) -> Optional[list]:
    """Получение задач конкретного проекта с использованием /api/v3/projects/{project_id}/work_packages"""
    url = f"{OP_API_URL}/projects/{project_id}/work_packages"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()["_embedded"]["elements"]
    print(f"Ошибка при получении задач проекта: {response.status_code} - {response.text}")
    return None

async def get_project_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор проекта для добавления часов"""
    projects = get_openproject_projects()
    if not projects or "_embedded" not in projects or not projects["_embedded"]["elements"]:
        await update.message.reply_text("Не удалось загрузить список проектов.")
        return ConversationHandler.END

    context.user_data['projects'] = projects["_embedded"]["elements"]
    project_names = [p["name"] for p in projects["_embedded"]["elements"]]
    keyboard = [[name] for name in project_names]
    await update.message.reply_text(
        "Выберите проект:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return PROJECT_CHOICE_TIME

async def handle_project_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбранного проекта"""
    project_name = update.message.text
    projects = context.user_data['projects']
    selected_project = next((p for p in projects if p["name"] == project_name), None)

    if not selected_project:
        await update.message.reply_text("Проект не найден. Попробуйте снова:")
        return PROJECT_CHOICE_TIME

    context.user_data['project_id'] = selected_project['id']
    tasks = get_project_tasks(selected_project['id'])
    if not tasks:
        await update.message.reply_text("В этом проекте нет задач.")
        return MENU

    context.user_data['tasks'] = tasks
    task_options = [[f"{task['subject']}"] for task in tasks]
    await update.message.reply_text(
        "Выберите задачу:",
        reply_markup=ReplyKeyboardMarkup(task_options, one_time_keyboard=True, resize_keyboard=True)
    )
    return TASK_CHOICE_TIME

async def handle_task_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбранной задачи"""
    choice = update.message.text
    tasks = context.user_data['tasks']
    selected_task = next((t for t in tasks if f"{t['subject']}" == choice), None)

    if not selected_task:
        await update.message.reply_text("Задача не найдена. Попробуйте снова:")
        return TASK_CHOICE_TIME

    context.user_data['selected_task'] = selected_task
    context.user_data['calendar'] = CustomCalendar()
    calendar_markup = context.user_data['calendar'].build_month()
    await update.message.reply_text(
        "Выберите дату для добавления часов:",
        reply_markup=calendar_markup
    )
    return DATE_CHOICE_TIME

async def handle_date_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора даты через календарь"""
    query = update.callback_query
    if not query:
        return DATE_CHOICE_TIME

    calendar = context.user_data['calendar']
    result = calendar.process(query.data)

    if result is False:  # Переключение месяца
        calendar_markup = calendar.build_month()
        await query.edit_message_reply_markup(reply_markup=calendar_markup)
        await query.answer()
        return DATE_CHOICE_TIME
    elif result is None:  # Пропустить не разрешено
        await query.answer("Пожалуйста, выберите дату.")
        return DATE_CHOICE_TIME
    else:  # Дата выбрана
        context.user_data['selected_date'] = result
        await query.edit_message_text(f"Выбрана дата: {result}")

        # Предопределенные типы деятельности (можно настроить)
        activity_types = ["Разработка", "Тестирование", "Анализ", "Документация"]
        keyboard = [[activity] for activity in activity_types]
        await query.message.reply_text(
            "Выберите тип деятельности:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ACTIVITY_TYPE_TIME

async def handle_activity_type_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора типа деятельности"""
    activity_type = update.message.text
    context.user_data['activity_type'] = activity_type

    project_id = context.user_data['project_id']
    members = get_project_members(project_id)
    if not members or "_embedded" not in members or not members["_embedded"]["elements"]:
        await update.message.reply_text("Не удалось загрузить участников проекта.")
        return MENU

    project_users = []
    for member in members["_embedded"]["elements"]:
        user_link = member["_links"].get("principal", {})
        if user_link and "href" in user_link:
            user_id = user_link["href"].split("/")[-1]
            user_name = user_link.get("title", f"User {user_id}")
            project_users.append({"id": user_id, "name": user_name})

    context.user_data['project_users'] = project_users
    user_names = [u["name"] for u in project_users]
    keyboard = [[name] for name in user_names]
    await update.message.reply_text(
        "Выберите сотрудника:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return PERSON_CHOICE_TIME

async def handle_person_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора сотрудника"""
    person_name = update.message.text
    users = context.user_data['project_users']
    selected_user = next((u for u in users if u["name"] == person_name), None)

    if not selected_user:
        await update.message.reply_text("Сотрудник не найден. Попробуйте снова:")
        return PERSON_CHOICE_TIME

    context.user_data['selected_person_id'] = selected_user['id']
    await update.message.reply_text(
        "Введите количество часов (например, '2' или '2.5'):",
        reply_markup=ReplyKeyboardRemove()
    )
    return HOURS_INPUT_TIME

async def handle_hours_input_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода часов и создание записи о времени"""
    try:
        hours = float(update.message.text)
        if hours <= 0:
            await update.message.reply_text("Количество часов должно быть положительным числом.")
            return HOURS_INPUT_TIME
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число (например, '2' или '2.5').")
        return HOURS_INPUT_TIME

    task = context.user_data['selected_task']
    person_id = context.user_data['selected_person_id']
    activity_type = context.user_data['activity_type']
    selected_date = context.user_data['selected_date']

    # Создание записи о затраченном времени (time entry) в OpenProject
    url = f"{OP_API_URL}/time_entries"
    headers = {"Content-Type": "application/json"}
    payload = {
        "hours": f"PT{hours}H",
        "spentOn": selected_date,
        "comment": {"raw": f"Тип деятельности: {activity_type}"},
        "_links": {
            "workPackage": {"href": f"/api/v3/work_packages/{task['id']}"},
            "user": {"href": f"/api/v3/users/{person_id}"},
            "project": {"href": f"/api/v3/projects/{context.user_data['project_id']}"}
        }
    }

    response = requests.post(url, headers=headers, json=payload, auth=("apikey", OP_API_KEY))
    if response.status_code == 201:
        await update.message.reply_text(
            f"Добавлено {hours} часов для задачи '{task['subject']}' на {selected_date} "
            f"для пользователя {person_id} (тип: {activity_type})."
        )
    else:
        await update.message.reply_text(f"Ошибка при добавлении часов: {response.text}")

    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(
            [["Создать задачу"], ["Добавить часы в задачу"]],
            one_time_keyboard=False,
            resize_keyboard=True
        )
    )
    return MENU