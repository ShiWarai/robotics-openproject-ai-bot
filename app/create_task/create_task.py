import logging
from typing import Dict, Optional

import requests
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from app.states import TaskStates
from app.utils.custom_calendar import CustomCalendar
from app.utils.utils import show_main_menu, get_project_members, get_projects
from app.variables import *

logger = logging.getLogger(__name__)

def _user_name_by_id(users: list, uid: Optional[str]) -> str:
    if uid is None:
        return "Никого"
    suid = str(uid)
    found = next((u.get("name") for u in users if str(u.get("id")) == suid), None)
    return found or f"ID {suid}"

async def handle_task_after_create_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """После успешного создания задачи: либо новая задача, либо возврат в меню."""
    choice = (update.message.text or "").strip()
    if choice == "Создать еще задачу":
        context.user_data.clear()
        return await choose_task_input_method(update, context)
    return await show_main_menu(update, context)


async def choose_task_input_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор: пошаговое меню или произвольный ввод."""
    keyboard = [["Через меню"], ["Произвольный ввод"]]
    await update.message.reply_text(
        "Как создать задачу?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return TaskStates.TASK_INPUT_METHOD_CHOICE.value


async def handle_task_input_method_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = (update.message.text or "").strip()
    if choice == "Через меню":
        projects = get_projects()
        if not projects or "_embedded" not in projects or not projects["_embedded"]["elements"]:
            await update.message.reply_text("Не удалось загрузить список проектов.")
            return await show_main_menu(update, context)

        context.user_data["projects"] = projects["_embedded"]["elements"]
        project_names = [p["name"] for p in projects["_embedded"]["elements"]]
        keyboard = [[name] for name in project_names]
        await update.message.reply_text(
            "Выберите проект:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        )
        return TaskStates.PROJECT_CHOICE.value

    if choice == "Произвольный ввод":
        projects = get_projects()
        if not projects or "_embedded" not in projects or not projects["_embedded"]["elements"]:
            await update.message.reply_text("Не удалось загрузить список проектов.")
            return await show_main_menu(update, context)

        context.user_data["projects"] = projects["_embedded"]["elements"]
        await update.message.reply_text(
            "Опишите задачу текстом или голосовым сообщением: проект, название, описание; "
            "по желанию — исполнителя, ответственного, даты начала/окончания, оценку в часах.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TaskStates.TASK_FREE_TEXT_INPUT.value

    await update.message.reply_text("Пожалуйста, выберите способ из предложенных.")
    return TaskStates.TASK_INPUT_METHOD_CHOICE.value


async def try_finish_free_task_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Создание задачи по черновику task_free_draft или запрос выбора исполнителя/ответственного.
    """
    draft = context.user_data.get("task_free_draft")
    if not draft:
        logger.warning("create_task free: нет task_free_draft")
        return await show_main_menu(update, context)

    users = draft.get("project_users") or []

    if draft.get("need_assignee_pick"):
        names = [u["name"] for u in users] + ["Никого"]
        keyboard = [[n] for n in names]
        logger.info("create_task free: запрос выбора исполнителя (ручной)")
        await update.message.reply_text(
            "Не удалось однозначно назначить исполнителя. Выберите из списка участников проекта:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        )
        return TaskStates.TASK_FREE_FALLBACK_ASSIGNEE.value

    if draft.get("need_responsible_pick"):
        names = [u["name"] for u in users] + ["Никого"]
        keyboard = [[n] for n in names]
        logger.info("create_task free: запрос выбора ответственного (ручной)")
        await update.message.reply_text(
            "Не удалось однозначно назначить ответственного. Выберите из списка:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        )
        return TaskStates.TASK_FREE_FALLBACK_RESPONSIBLE.value

    logger.info(
        "create_task free: создание задачи project=%s assignee=%s responsible=%s",
        draft.get("project_id"),
        draft.get("assignee_id"),
        draft.get("responsible_id"),
    )
    result = create_openproject_task(
        draft["project_id"],
        draft["task_name"],
        draft["task_description"],
        draft.get("assignee_id"),
        draft.get("responsible_id"),
        draft.get("start_date"),
        draft.get("due_date"),
        draft.get("estimated_time"),
    )

    context.user_data.pop("task_free_draft", None)

    if result:
        keyboard = [["Создать еще задачу"], ["Вернуться в меню"]]
        assignee_name = _user_name_by_id(users, draft.get("assignee_id"))
        responsible_name = _user_name_by_id(users, draft.get("responsible_id"))
        project_name = draft.get("project_name") or f"ID {draft.get('project_id')}"
        description = (draft.get("task_description") or "").strip()
        if len(description) > 400:
            description = description[:397] + "..."
        start_date = draft.get("start_date") or "не указана"
        due_date = draft.get("due_date") or "не указана"
        estimated_time = (
            f"{draft.get('estimated_time')} ч"
            if draft.get("estimated_time")
            else "не указана"
        )
        await update.message.reply_text(
            (
                "Задача создана в OpenProject.\n\n"
                f"ID: {result['id']}\n"
                f"Проект: {project_name}\n"
                f"Название: {draft['task_name']}\n"
                f"Описание: {description}\n"
                f"Исполнитель (assignee): {assignee_name}\n"
                f"Ответственный (responsible): {responsible_name}\n"
                f"Дата начала: {start_date}\n"
                f"Дата окончания: {due_date}\n"
                f"Оценка: {estimated_time}\n\n"
                "Хотите создать еще одну задачу?"
            ),
            reply_markup=ReplyKeyboardMarkup(
                keyboard, one_time_keyboard=True, resize_keyboard=True
            ),
        )
        return TaskStates.TASK_AFTER_CREATE_CHOICE.value
    else:
        await update.message.reply_text(
            "Ошибка при создании задачи в OpenProject.",
            reply_markup=ReplyKeyboardRemove(),
        )

    return await show_main_menu(update, context)


async def handle_task_free_fallback_assignee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data.get("task_free_draft")
    if not draft:
        return await show_main_menu(update, context)

    choice = (update.message.text or "").strip()
    users = draft["project_users"]

    if choice == "Никого":
        draft["assignee_id"] = None
    else:
        selected = next((u for u in users if u["name"] == choice), None)
        if not selected:
            await update.message.reply_text("Выберите имя из предложенного списка.")
            return TaskStates.TASK_FREE_FALLBACK_ASSIGNEE.value
        draft["assignee_id"] = selected["id"]

    draft["need_assignee_pick"] = False
    return await try_finish_free_task_creation(update, context)


async def handle_task_free_fallback_responsible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data.get("task_free_draft")
    if not draft:
        return await show_main_menu(update, context)

    choice = (update.message.text or "").strip()
    users = draft["project_users"]

    if choice == "Никого":
        draft["responsible_id"] = None
    else:
        selected = next((u for u in users if u["name"] == choice), None)
        if not selected:
            await update.message.reply_text("Выберите имя из предложенного списка.")
            return TaskStates.TASK_FREE_FALLBACK_RESPONSIBLE.value
        draft["responsible_id"] = selected["id"]

    draft["need_responsible_pick"] = False
    return await try_finish_free_task_creation(update, context)


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
        keyboard = [["Создать еще задачу"], ["Вернуться в меню"]]
        await update.message.reply_text(
            f"Задача '{task_name}' создана в проекте {project_id}! ID: {result['id']}\n\nХотите создать еще одну задачу?",
            reply_markup=ReplyKeyboardMarkup(
                keyboard, one_time_keyboard=True, resize_keyboard=True
            ),
        )
        return TaskStates.TASK_AFTER_CREATE_CHOICE.value
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