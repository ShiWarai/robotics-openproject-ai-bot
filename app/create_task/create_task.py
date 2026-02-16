from typing import Dict, Optional

import requests
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from app.states import TaskStates
from app.utils.custom_calendar import CustomCalendar
from app.utils.utils import show_main_menu, get_project_members
from app.variables import *


async def get_project_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    project_name = update.message.text
    projects = context.user_data['projects']
    selected_project = next((p for p in projects if p["name"] == project_name), None)

    if selected_project:
        context.user_data['project_id'] = selected_project['id']
        await update.message.reply_text(
            f"Вы выбрали проект: {project_name}\nВведите название задачи:",
            reply_markup=ReplyKeyboardRemove()
        )
        return TaskStates.TASK_NAME.value
    else:
        await update.message.reply_text("Проект не найден. Попробуйте снова:")
        return TaskStates.PROJECT_CHOICE.value

async def get_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['task_name'] = update.message.text
    await update.message.reply_text("Введите описание задачи:")
    return TaskStates.TASK_DESCRIPTION.value

async def get_task_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['task_description'] = update.message.text
    project_id = context.user_data['project_id']

    members = get_project_members(project_id)
    if not members or "_embedded" not in members or not members["_embedded"]["elements"]:
        await update.message.reply_text("Не удалось загрузить участников проекта или проект пуст.")
        return await show_main_menu(update, context)

    project_users = []
    for member in members["_embedded"]["elements"]:
        user_link = member["_links"].get("principal", {})
        if user_link and "href" in user_link:
            user_id = user_link["href"].split("/")[-1]
            user_name = user_link.get("title", f"User {user_id}")
            project_users.append({"id": user_id, "name": user_name})

    context.user_data['users'] = project_users
    user_names = [u["name"] for u in project_users] + ["Никого"]
    keyboard = [[name] for name in user_names]
    await update.message.reply_text(
        "Выберите ответственного (assignee):",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return TaskStates.ASSIGNEE_CHOICE.value

async def get_assignee_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assignee_name = update.message.text
    users = context.user_data['users']
    selected_user = next((u for u in users if u["name"] == assignee_name), None)

    if assignee_name == "Никого":
        context.user_data['assignee_id'] = None
    elif selected_user:
        context.user_data['assignee_id'] = selected_user['id']
    else:
        await update.message.reply_text("Пользователь не найден. Попробуйте снова:")
        return TaskStates.ASSIGNEE_CHOICE.value

    user_names = [u["name"] for u in users] + ["Никого"]
    keyboard = [[name] for name in user_names]
    await update.message.reply_text(
        "Выберите подотчетного (responsible):",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return TaskStates.RESPONSIBLE_CHOICE.value

async def get_responsible_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    responsible_name = update.message.text
    users = context.user_data['users']
    selected_user = next((u for u in users if u["name"] == responsible_name), None)

    if responsible_name == "Никого":
        context.user_data['responsible_id'] = None
    elif selected_user:
        context.user_data['responsible_id'] = selected_user['id']
    else:
        await update.message.reply_text("Пользователь не найден. Попробуйте снова:")
        return TaskStates.RESPONSIBLE_CHOICE.value

    context.user_data['calendar'] = CustomCalendar()
    calendar_markup = context.user_data['calendar'].build_month()
    await update.message.reply_text(
        "Выберите дату начала задачи:",
        reply_markup=calendar_markup
    )
    return TaskStates.START_DATE.value

async def get_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        calendar = context.user_data['calendar']
        result = calendar.process(query.data)

        if result is None:
            context.user_data['start_date'] = None
            context.user_data['calendar'] = CustomCalendar()
            calendar_markup = context.user_data['calendar'].build_month()
            await query.edit_message_text("Дата начала пропущена.")
            await query.message.reply_text(
                "Выберите дату окончания задачи:",
                reply_markup=calendar_markup
            )
            return TaskStates.DUE_DATE.value
        elif result is False:
            calendar_markup = calendar.build_month()
            await query.edit_message_reply_markup(reply_markup=calendar_markup)
            await query.answer()
            return TaskStates.START_DATE.value
        else:
            context.user_data['start_date'] = result
            context.user_data['calendar'] = CustomCalendar()
            calendar_markup = context.user_data['calendar'].build_month()
            await query.edit_message_text(f"Выбрана дата начала: {result}")
            await query.message.reply_text(
                "Выберите дату окончания задачи:",
                reply_markup=calendar_markup
            )
            return TaskStates.DUE_DATE.value

async def get_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        calendar = context.user_data['calendar']
        result = calendar.process(query.data)

        if result is None:
            context.user_data['due_date'] = None
            await query.edit_message_text("Дата окончания пропущена.")
            await query.message.reply_text(
                "Введите количество часов на задачу (например, 8) или 'Пропустить':",
                reply_markup=ReplyKeyboardRemove()
            )
            return TaskStates.ESTIMATED_TIME.value
        elif result is False:
            calendar_markup = calendar.build_month()
            await query.edit_message_reply_markup(reply_markup=calendar_markup)
            await query.answer()
            return TaskStates.DUE_DATE.value
        else:
            context.user_data['due_date'] = result
            await query.edit_message_text(f"Выбрана дата окончания: {result}")
            await query.message.reply_text(
                "Введите количество часов на задачу (например, 8) или 'Пропустить':",
                reply_markup=ReplyKeyboardRemove()
            )
            return TaskStates.ESTIMATED_TIME.value

async def get_estimated_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    estimated_time_input = update.message.text
    if estimated_time_input.lower() == "пропустить":
        context.user_data['estimated_time'] = None
    else:
        try:
            hours = int(estimated_time_input)
            if hours <= 0:
                raise ValueError
            context.user_data['estimated_time'] = str(hours)
        except ValueError:
            await update.message.reply_text("Введите положительное число часов или 'Пропустить':")
            return TaskStates.ESTIMATED_TIME.value

    project_id = context.user_data['project_id']
    task_name = context.user_data['task_name']
    task_description = context.user_data['task_description']
    assignee_id = context.user_data.get('assignee_id')
    responsible_id = context.user_data.get('responsible_id')
    start_date = context.user_data.get('start_date')
    due_date = context.user_data.get('due_date')
    estimated_time = context.user_data.get('estimated_time')

    result = create_openproject_task(
        str(project_id), task_name, task_description, assignee_id, responsible_id,
        start_date, due_date, estimated_time
    )

    if result:
        await update.message.reply_text(
            f"Задача '{task_name}' создана в проекте {project_id}! ID: {result['id']}"
        )
    else:
        await update.message.reply_text("Ошибка при создании задачи.")

    return await show_main_menu(update, context)

def create_openproject_task(project_id: str, task_name: str, task_description: str,
                           assignee_id: Optional[str] = None, responsible_id: Optional[str] = None,
                           start_date: Optional[str] = None, due_date: Optional[str] = None,
                           estimated_time: Optional[str] = None) -> Optional[Dict]:
    url = f"{OP_API_URL}/work_packages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "subject": task_name,
        "description": {"raw": task_description},
        "_links": {
            "project": {"href": f"/api/v3/projects/{project_id}"},
            "type": {"href": "/api/v3/types/1"}
        }
    }
    if assignee_id:
        payload["_links"]["assignee"] = {"href": f"/api/v3/users/{assignee_id}"}
    if responsible_id:
        payload["_links"]["responsible"] = {"href": f"/api/v3/users/{responsible_id}"}
    if start_date:
        payload["startDate"] = start_date
    if due_date:
        payload["dueDate"] = due_date
    if estimated_time:
        payload["estimatedTime"] = f"PT{estimated_time}H"

    response = requests.post(url, headers=headers, json=payload, auth=("apikey", OP_API_KEY))
    if response.status_code == 201:
        return response.json()
    else:
        print(f"Ошибка: {response.status_code} - {response.text}")
        return None