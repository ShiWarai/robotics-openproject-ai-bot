import logging

# Отключить логи HTTP-запросов до импорта telegram (в URL может попадать токен бота)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from typing import Dict, Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes, \
    CallbackQueryHandler

from app.calculate_hours.calculate_hours import (
    get_employee_choice, handle_employee_choice, handle_start_date_calc, handle_end_date_calc
)
from app.create_task.create_task import (
    choose_task_input_method,
    handle_task_input_method_choice,
    handle_task_free_fallback_assignee,
    handle_task_free_fallback_responsible,
    handle_task_after_create_choice,
    get_project_choice,
    get_task_name,
    get_task_description,
    get_assignee_choice,
    get_responsible_choice,
    get_start_date,
    get_due_date,
    get_estimated_time,
)
from app.create_task.parse_text_input import handle_create_task_free_text
from app.estimated_time.estimated_time import (
    choose_input_method, handle_input_method_choice, handle_project_choice_time,
    handle_task_choice_time, handle_date_choice_time, handle_person_choice_time,
    handle_hours_input_time, handle_add_another_time
)
from app.estimated_time.parse_text_input import handle_free_text_input, handle_text_input
from app.states import MainStates, TaskStates, TimeStates, CalcStates
from app.utils.utils import show_main_menu
from app.variables import *

# Глобальный словарь для хранения Telegram ID пользователей
USER_TELEGRAM_IDS: Dict[str, int] = {}

def load_users_telegram_ids() -> None:
    """Загружает Telegram ID пользователей из OpenProject."""
    url = f"{OP_API_URL}/users"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        users = response.json()["_embedded"]["elements"]
        for user in users:
            telegram_id = user.get(CUSTOM_FIELD_NAME)
            if telegram_id:
                USER_TELEGRAM_IDS[telegram_id] = user["id"]
        print(f"Загружено {len(USER_TELEGRAM_IDS)} пользователей с Telegram ID")
    else:
        print(f"Ошибка при загрузке пользователей: {response.status_code} - {response.text}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start."""
    telegram_id = str(update.message.from_user.id)
    telegram_username = update.message.from_user.username or ""

    user_id = USER_TELEGRAM_IDS.get(telegram_id)
    if not user_id and telegram_username:
        user_id = USER_TELEGRAM_IDS.get(telegram_username)

    if user_id:
        context.user_data['user_id'] = user_id
        return await show_main_menu(update, context)
    else:
        await update.message.reply_text(
            "Ваш Telegram ID или username не зарегистрирован в OpenProject. Обратитесь к администратору."
        )
        return ConversationHandler.END

async def auto_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Обработчик для автоматического открытия меню для известных пользователей."""
    telegram_id = str(update.message.from_user.id)
    telegram_username = update.message.from_user.username or ""

    user_id = USER_TELEGRAM_IDS.get(telegram_id)
    if not user_id and telegram_username:
        user_id = USER_TELEGRAM_IDS.get(telegram_username)

    if user_id:
        context.user_data['user_id'] = user_id
        return await show_main_menu(update, context)
    else:
        await update.message.reply_text(
            "Ваш Telegram ID или username не зарегистрирован в OpenProject. Введите /start для начала работы."
        )
        return None

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик выбора в главном меню."""
    choice = update.message.text
    if choice == "Создать задачу":
        return await choose_task_input_method(update, context)
    elif choice == "Добавить часы в задачу":
        return await choose_input_method(update, context)
    elif choice == "Рассчитать часы сотрудника":
        return await get_employee_choice(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите действие из меню.")
        return await show_main_menu(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /cancel — отмена текущего действия и возврат в главное меню."""
    if update.message:
        await update.message.reply_text("Действие отменено. Начинаем сначала.")
    return await show_main_menu(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок."""
    print(f"Произошла ошибка: {context.error}")
    if update and update.message:
        await update.message.reply_text("Произошла ошибка. Попробуйте снова или обратитесь к администратору.")

def main():
    """Запускает бота."""
    load_users_telegram_ids()

    if not USER_TELEGRAM_IDS:
        print("Не удалось загрузить пользователей. Бот не запустится.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN.strip()).build()

    # Сохраняем USER_TELEGRAM_IDS в bot_data
    application.bot_data['USER_TELEGRAM_IDS'] = USER_TELEGRAM_IDS

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, auto_menu),
        ],
        states={
            MainStates.MENU.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu)],
            TaskStates.TASK_INPUT_METHOD_CHOICE.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_input_method_choice)
            ],
            TaskStates.PROJECT_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_project_choice)],
            TaskStates.TASK_FREE_TEXT_INPUT.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_create_task_free_text),
                MessageHandler(filters.VOICE, handle_create_task_free_text),
            ],
            TaskStates.TASK_FREE_FALLBACK_ASSIGNEE.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_free_fallback_assignee)
            ],
            TaskStates.TASK_FREE_FALLBACK_RESPONSIBLE.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_free_fallback_responsible)
            ],
            TaskStates.TASK_NAME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_task_name)],
            TaskStates.TASK_DESCRIPTION.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_task_description)],
            TaskStates.ASSIGNEE_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_assignee_choice)],
            TaskStates.RESPONSIBLE_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_responsible_choice)],
            TaskStates.START_DATE.value: [CallbackQueryHandler(get_start_date)],
            TaskStates.DUE_DATE.value: [CallbackQueryHandler(get_due_date)],
            TaskStates.ESTIMATED_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_estimated_time)],
            TaskStates.TASK_AFTER_CREATE_CHOICE.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_after_create_choice)
            ],
            TimeStates.INPUT_METHOD_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input_method_choice)],
            TimeStates.FREE_TEXT_INPUT.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text_input),
                MessageHandler(filters.VOICE, handle_free_text_input)
            ],
            TimeStates.PROJECT_CHOICE_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_project_choice_time)],
            TimeStates.TASK_CHOICE_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_choice_time)],
            TimeStates.DATE_CHOICE_TIME.value: [CallbackQueryHandler(handle_date_choice_time)],
            TimeStates.PERSON_CHOICE_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_person_choice_time)],
            TimeStates.HOURS_INPUT_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hours_input_time)],
            TimeStates.ADD_ANOTHER_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_another_time)],
            CalcStates.EMPLOYEE_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_employee_choice)],
            CalcStates.START_DATE_CALC.value: [CallbackQueryHandler(handle_start_date_calc)],
            CalcStates.END_DATE_CALC.value: [CallbackQueryHandler(handle_end_date_calc)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start),
        ],
    )

    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == '__main__':
    main()