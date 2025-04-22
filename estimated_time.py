from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
import requests
from variables import OP_API_URL, OP_API_KEY
from typing import Optional
from create_task import get_project_members, CustomCalendar
from utils import show_main_menu, get_openproject_projects
from states import TimeStates

def get_project_tasks(project_id: str) -> Optional[list]:
    """Получение задач конкретного проекта."""
    url = f"{OP_API_URL}/projects/{project_id}/work_packages"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()["_embedded"]["elements"]
    print(f"Ошибка при получении задач проекта: {response.status_code} - {response.text}")
    return None

async def choose_input_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Предлагает пользователю выбрать способ ввода для добавления часов."""
    keyboard = [["Через меню"], ["Текстом"]]
    await update.message.reply_text(
        "Как вы хотите добавить часы?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return TimeStates.INPUT_METHOD_CHOICE.value

async def handle_input_method_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора способа ввода."""
    choice = update.message.text
    if choice == "Через меню":
        return await get_project_choice_time(update, context)
    elif choice == "Текстом":
        projects = get_openproject_projects()
        if not projects or "_embedded" not in projects or not projects["_embedded"]["elements"]:
            await update.message.reply_text("Не удалось загрузить список проектов.")
            return await show_main_menu(update, context)

        context.user_data['projects'] = projects["_embedded"]["elements"]
        project_names = [p["name"] for p in projects["_embedded"]["elements"]]
        keyboard = [[name] for name in project_names]
        await update.message.reply_text(
            "Выберите проект для текстового ввода:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return TimeStates.PROJECT_CHOICE_TEXT.value
    else:
        await update.message.reply_text("Пожалуйста, выберите способ ввода из предложенных.")
        return TimeStates.INPUT_METHOD_CHOICE.value

async def get_project_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор проекта для добавления часов через меню."""
    projects = get_openproject_projects()
    if not projects or "_embedded" not in projects or not projects["_embedded"]["elements"]:
        await update.message.reply_text("Не удалось загрузить список проектов.")
        return await show_main_menu(update, context)

    context.user_data['projects'] = projects["_embedded"]["elements"]
    project_names = [p["name"] for p in projects["_embedded"]["elements"]]
    keyboard = [[name] for name in project_names]
    await update.message.reply_text(
        "Выберите проект:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return TimeStates.PROJECT_CHOICE_TIME.value

async def handle_project_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбранного проекта для меню."""
    project_name = update.message.text
    projects = context.user_data['projects']
    selected_project = next((p for p in projects if p["name"] == project_name), None)

    if not selected_project:
        await update.message.reply_text("Проект не найден. Попробуйте снова:")
        return TimeStates.PROJECT_CHOICE_TIME.value

    context.user_data['project_id'] = selected_project['id']
    tasks = get_project_tasks(selected_project['id'])
    if not tasks:
        await update.message.reply_text("В этом проекте нет задач.")
        return await show_main_menu(update, context)

    context.user_data['tasks'] = tasks
    task_options = [[f"{task['subject']}"] for task in tasks]
    await update.message.reply_text(
        "Выберите задачу:",
        reply_markup=ReplyKeyboardMarkup(task_options, one_time_keyboard=True, resize_keyboard=True)
    )
    return TimeStates.TASK_CHOICE_TIME.value

async def handle_task_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбранной задачи."""
    choice = update.message.text
    tasks = context.user_data['tasks']
    selected_task = next((t for t in tasks if f"{t['subject']}" == choice), None)

    if not selected_task:
        await update.message.reply_text("Задача не найдена. Попробуйте снова:")
        return TimeStates.TASK_CHOICE_TIME.value

    context.user_data['selected_task'] = selected_task
    context.user_data['calendar'] = CustomCalendar()
    calendar_markup = context.user_data['calendar'].build_month()
    await update.message.reply_text(
        "Выберите дату для добавления часов:",
        reply_markup=calendar_markup
    )
    return TimeStates.DATE_CHOICE_TIME.value

async def handle_date_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора даты через календарь."""
    query = update.callback_query
    if not query:
        return TimeStates.DATE_CHOICE_TIME.value

    calendar = context.user_data['calendar']
    result = calendar.process(query.data)

    if result is False:
        calendar_markup = calendar.build_month()
        await query.edit_message_reply_markup(reply_markup=calendar_markup)
        await query.answer()
        return TimeStates.DATE_CHOICE_TIME.value
    elif result is None:
        await query.answer("Пожалуйста, выберите дату.")
        return TimeStates.DATE_CHOICE_TIME.value
    else:
        context.user_data['selected_date'] = result
        await query.edit_message_text(f"Выбрана дата: {result}")

        activity_types = ["Разработка", "Тестирование", "Анализ", "Документация"]
        keyboard = [[activity] for activity in activity_types]
        await query.message.reply_text(
            "Выберите тип деятельности:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return TimeStates.ACTIVITY_TYPE_TIME.value

async def handle_activity_type_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора типа деятельности."""
    activity_type = update.message.text
    context.user_data['activity_type'] = activity_type

    project_id = context.user_data['project_id']
    members = get_project_members(project_id)
    if not members or "_embedded" not in members or not members["_embedded"]["elements"]:
        await update.message.reply_text("Не удалось загрузить участников проекта.")
        return await show_main_menu(update, context)

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
    return TimeStates.PERSON_CHOICE_TIME.value

async def handle_person_choice_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора сотрудника."""
    person_name = update.message.text
    users = context.user_data['project_users']
    selected_user = next((u for u in users if u["name"] == person_name), None)

    if not selected_user:
        await update.message.reply_text("Сотрудник не найден. Попробуйте снова:")
        return TimeStates.PERSON_CHOICE_TIME.value

    context.user_data['selected_person_id'] = selected_user['id']
    await update.message.reply_text(
        "Введите количество часов (например, '2' или '2.5'):",
        reply_markup=ReplyKeyboardRemove()
    )
    return TimeStates.HOURS_INPUT_TIME.value

async def handle_hours_input_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода часов и создание записи о времени."""
    try:
        hours = float(update.message.text)
        if hours <= 0:
            await update.message.reply_text("Количество часов должно быть положительным числом.")
            return TimeStates.HOURS_INPUT_TIME.value
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число (например, '2' или '2.5').")
        return TimeStates.HOURS_INPUT_TIME.value

    task = context.user_data['selected_task']
    person_id = context.user_data['selected_person_id']
    activity_type = context.user_data['activity_type']
    selected_date = context.user_data['selected_date']

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
        return TimeStates.HOURS_INPUT_TIME.value

    # Спрашиваем, хочет ли пользователь добавить еще часы
    keyboard = [["Добавить еще часы"], ["Вернуться в меню"]]
    await update.message.reply_text(
        "Хотите добавить еще часы для другого проекта или задачи?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return TimeStates.ADD_ANOTHER_TIME.value

async def handle_add_another_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора, добавлять ли еще часы."""
    choice = update.message.text
    if choice == "Добавить еще часы":
        # Очищаем предыдущие данные, чтобы начать заново
        context.user_data.pop('selected_task', None)
        context.user_data.pop('selected_date', None)
        context.user_data.pop('activity_type', None)
        context.user_data.pop('selected_person_id', None)
        context.user_data.pop('project_id', None)
        context.user_data.pop('tasks', None)
        context.user_data.pop('project_users', None)
        return await choose_input_method(update, context)
    else:
        return await show_main_menu(update, context)

async def handle_project_choice_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбранного проекта для текстового ввода."""
    project_name = update.message.text
    projects = context.user_data['projects']
    selected_project = next((p for p in projects if p["name"] == project_name), None)

    if not selected_project:
        await update.message.reply_text("Проект не найден. Попробуйте снова:")
        return TimeStates.PROJECT_CHOICE_TEXT.value

    context.user_data['project_id'] = selected_project['id']
    context.user_data['project_name'] = selected_project['name']
    tasks = get_project_tasks(selected_project['id'])
    if not tasks:
        await update.message.reply_text("В этом проекте нет задач.")
        return await show_main_menu(update, context)

    context.user_data['tasks'] = tasks
    await update.message.reply_text(
        "Введите информацию о часах, например: '2 часа тестирования навигации вчера, 3 часа доработки навигации'",
        reply_markup=ReplyKeyboardRemove()
    )
    return TimeStates.TEXT_INPUT.value