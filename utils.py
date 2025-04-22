from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
import requests
from variables import OP_API_URL, OP_API_KEY
from typing import Optional, Dict

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отображает главное меню."""
    context.user_data.clear()
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(
            [["Создать задачу"], ["Добавить часы в задачу"], ["Рассчитать часы сотрудника"]],
            one_time_keyboard=False,
            resize_keyboard=True
        )
    )
    from states import MainStates
    return MainStates.MENU.value

def get_openproject_projects() -> Optional[Dict]:
    """Получение списка проектов."""
    url = f"{OP_API_URL}/projects"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()
    print(f"Ошибка при получении проектов: {response.status_code} - {response.text}")
    return None