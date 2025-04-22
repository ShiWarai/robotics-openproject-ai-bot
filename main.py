from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes, CallbackQueryHandler
from typing import Dict, Optional
import requests
from variables import *
from create_task import (
    get_project_choice, get_task_name, get_task_description,
    get_assignee_choice, get_responsible_choice, get_start_date,
    get_due_date, get_estimated_time, create_openproject_task
)
from estimated_time import (
    choose_input_method, handle_input_method_choice, get_project_choice_time, handle_project_choice_time,
    handle_task_choice_time, handle_date_choice_time, handle_person_choice_time,
    handle_hours_input_time, handle_add_another_time, handle_project_choice_text
)
from parse_text_input import handle_text_input
from calculate_hours import (
    get_employee_choice, handle_employee_choice, handle_start_date_calc, handle_end_date_calc
)
from utils import show_main_menu, get_openproject_projects
from states import MainStates, TaskStates, TimeStates, CalcStates

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

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик выбора в главном меню."""
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
        return TaskStates.PROJECT_CHOICE.value
    elif choice == "Добавить часы в задачу":
        return await choose_input_method(update, context)
    elif choice == "Рассчитать часы сотрудника":
        return await get_employee_choice(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите действие из меню.")
        return await show_main_menu(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /cancel."""
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

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Сохраняем USER_TELEGRAM_IDS в bot_data
    application.bot_data['USER_TELEGRAM_IDS'] = USER_TELEGRAM_IDS

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
        ],
        states={
            MainStates.MENU.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu)],
            TaskStates.PROJECT_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_project_choice)],
            TaskStates.TASK_NAME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_task_name)],
            TaskStates.TASK_DESCRIPTION.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_task_description)],
            TaskStates.ASSIGNEE_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_assignee_choice)],
            TaskStates.RESPONSIBLE_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_responsible_choice)],
            TaskStates.START_DATE.value: [CallbackQueryHandler(get_start_date)],
            TaskStates.DUE_DATE.value: [CallbackQueryHandler(get_due_date)],
            TaskStates.ESTIMATED_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_estimated_time)],
            TimeStates.INPUT_METHOD_CHOICE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input_method_choice)],
            TimeStates.PROJECT_CHOICE_TEXT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_project_choice_text)],
            TimeStates.TEXT_INPUT.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
                MessageHandler(filters.VOICE, handle_text_input)  # Добавляем обработку голосовых сообщений
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
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == '__main__':
    main()