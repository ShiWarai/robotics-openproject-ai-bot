from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes, CallbackQueryHandler
from typing import Dict, Optional
import requests
from variables import *
from create_task import (get_project_choice, get_task_name, get_task_description,
                        get_assignee_choice, get_responsible_choice, get_start_date,
                        get_due_date, get_estimated_time, create_openproject_task)
from estimated_time import (get_project_choice_time, handle_project_choice_time, handle_task_choice_time,
                             handle_date_choice_time, handle_activity_type_time, handle_person_choice_time,
                             handle_hours_input_time, PROJECT_CHOICE_TIME, TASK_CHOICE_TIME, DATE_CHOICE_TIME,
                             ACTIVITY_TYPE_TIME, PERSON_CHOICE_TIME, HOURS_INPUT_TIME)

# Глобальный словарь для хранения Telegram ID пользователей
USER_TELEGRAM_IDS = {}

def load_users_telegram_ids() -> None:
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

def get_openproject_projects() -> Optional[Dict]:
    url = f"{OP_API_URL}/projects"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Ошибка при получении проектов: {response.status_code} - {response.text}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = str(update.message.from_user.id)
    telegram_username = update.message.from_user.username or ""

    user_id = USER_TELEGRAM_IDS.get(telegram_id)
    if not user_id and telegram_username:
        user_id = USER_TELEGRAM_IDS.get(telegram_username)

    if user_id:
        context.user_data['user_id'] = user_id
        await update.message.reply_text(
            "Добро пожаловать! Выберите действие:",
            reply_markup=ReplyKeyboardMarkup(
                [["Создать задачу"], ["Добавить часы в задачу"]],
                one_time_keyboard=False,
                resize_keyboard=True
            )
        )
        return MENU
    else:
        await update.message.reply_text(
            "Ваш Telegram ID или username не зарегистрирован в OpenProject. Обратитесь к администратору."
        )
        return ConversationHandler.END

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    if choice == "Создать задачу":
        projects = get_openproject_projects()
        if not projects or "_embedded" not in projects or not projects["_embedded"]["elements"]:
            await update.message.reply_text("Не удалось загрузить список проектов.")
            return ConversationHandler.END

        context.user_data['projects'] = projects["_embedded"]["elements"]
        project_names = [p["name"] for p in projects["_embedded"]["elements"]]
        keyboard = [[name] for name in project_names]
        await update.message.reply_text(
            "Выберите проект:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )
        return PROJECT_CHOICE
    elif choice == "Добавить часы в задачу":
        return await get_project_choice_time(update, context)
    else:
        await update.message.reply_text(
            "Выберите действие из меню:",
            reply_markup=ReplyKeyboardMarkup(
                [["Создать задачу"], ["Добавить часы в задачу"]],
                one_time_keyboard=False,
                resize_keyboard=True
            )
        )
        return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await start(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    print(f"Произошла ошибка: {context.error}")
    if update and update.message:
        await update.message.reply_text("Произошла ошибка. Попробуйте снова или обратитесь к администратору.")

def main():
    load_users_telegram_ids()

    if not USER_TELEGRAM_IDS:
        print("Не удалось загрузить пользователей. Бот не запустится.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu)],
            PROJECT_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_project_choice)],
            TASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_task_name)],
            TASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_task_description)],
            ASSIGNEE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_assignee_choice)],
            RESPONSIBLE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_responsible_choice)],
            START_DATE: [CallbackQueryHandler(get_start_date)],
            DUE_DATE: [CallbackQueryHandler(get_due_date)],
            ESTIMATED_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_estimated_time)],
            PROJECT_CHOICE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_project_choice_time)],
            TASK_CHOICE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_choice_time)],
            DATE_CHOICE_TIME: [CallbackQueryHandler(handle_date_choice_time)],
            ACTIVITY_TYPE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_activity_type_time)],
            PERSON_CHOICE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_person_choice_time)],
            HOURS_INPUT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hours_input_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == '__main__':
    main()