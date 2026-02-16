from typing import Optional, Dict, List

import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from app.variables import OP_API_URL, OP_API_KEY


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
    from app.states import MainStates
    return MainStates.MENU.value

def get_projects() -> Optional[Dict]:
    """Получение списка проектов."""
    url = f"{OP_API_URL}/projects"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()
    print(f"Ошибка при получении проектов: {response.status_code} - {response.text}")
    return None

def get_project_tasks(project_id: int) -> Optional[List[Dict]]:
    """Получение всех задач проекта по его ID."""
    url = f"{OP_API_URL}/projects/{project_id}/work_packages"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()["_embedded"]["elements"]
    print(f"Ошибка при получении задач проекта {project_id}: {response.status_code} - {response.text}")
    return None

def get_project_members(project_id: str) -> Optional[Dict]:
    url = f"{OP_API_URL}/memberships"
    headers = {"Content-Type": "application/json"}
    params = {
        "filters": f'[{{"project":{{"operator":"=","values":["{project_id}"]}}}}]'
    }
    response = requests.get(url, headers=headers, params=params, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Ошибка при получении участников проекта: {response.status_code} - {response.text}")
        return None