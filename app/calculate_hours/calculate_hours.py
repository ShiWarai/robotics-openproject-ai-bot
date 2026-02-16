import logging
from datetime import datetime
from typing import Optional, List, Dict

import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from app.states import CalcStates
from app.utils.custom_calendar import CustomCalendar
from app.utils.utils import show_main_menu
from app.variables import OP_API_URL, OP_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_all_users() -> Optional[List[Dict]]:
    """Получает список всех пользователей из OpenProject."""
    url = f"{OP_API_URL}/users"
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, auth=("apikey", OP_API_KEY))
    if response.status_code == 200:
        return response.json()["_embedded"]["elements"]
    logger.error(f"Ошибка при получении пользователей: {response.status_code} - {response.text}")
    return None

def get_time_entries(user_id: str, start_date: str, end_date: Optional[str] = None) -> Optional[List[Dict]]:
    return [{}]

async def get_employee_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрашивает выбор сотрудника."""
    users = get_all_users()
    if not users:
        await update.message.reply_text("Не удалось загрузить список сотрудников.")
        return await show_main_menu(update, context)

    context.user_data['users'] = users
    user_names = [u["name"] for u in users]
    keyboard = [[name] for name in user_names]
    await update.message.reply_text(
        "Выберите сотрудника:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return CalcStates.EMPLOYEE_CHOICE.value


async def handle_employee_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор сотрудника."""
    employee_name = update.message.text
    users = context.user_data['users']
    selected_user = next((u for u in users if u["name"] == employee_name), None)

    if not selected_user:
        await update.message.reply_text("Сотрудник не найден. Попробуйте снова:")
        return CalcStates.EMPLOYEE_CHOICE.value

    context.user_data['selected_user'] = selected_user
    context.user_data['calendar'] = CustomCalendar()
    calendar_markup = context.user_data['calendar'].build_month()
    await update.message.reply_text(
        "Выберите начальную дату для расчёта часов:",
        reply_markup=calendar_markup
    )
    return CalcStates.START_DATE_CALC.value


async def handle_start_date_calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор начальной даты."""
    query = update.callback_query
    if not query:
        return CalcStates.START_DATE_CALC.value

    await query.answer()
    calendar = context.user_data['calendar']
    result = calendar.process(query.data)

    if result is False:  # Переключение месяца
        calendar_markup = calendar.build_month()
        await query.edit_message_reply_markup(reply_markup=calendar_markup)
        return CalcStates.START_DATE_CALC.value
    elif result is None:  # Пропустить не разрешено
        await query.answer("Пожалуйста, выберите дату.")
        return CalcStates.START_DATE_CALC.value
    else:  # Дата выбрана
        context.user_data['start_date'] = result
        context.user_data['calendar'] = CustomCalendar()
        calendar_markup = context.user_data['calendar'].build_month()
        await query.edit_message_text(f"Выбрана начальная дата: {result}")
        await query.message.reply_text(
            "Выберите конечную дату (или нажмите 'Пропустить' для расчёта до сегодня):",
            reply_markup=calendar_markup
        )
        return CalcStates.END_DATE_CALC.value


async def handle_end_date_calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор конечной даты или пропуск."""
    query = update.callback_query
    if not query:
        return CalcStates.END_DATE_CALC.value

    await query.answer()
    calendar = context.user_data['calendar']
    result = calendar.process(query.data)

    if result is False:  # Переключение месяца
        calendar_markup = calendar.build_month()
        await query.edit_message_reply_markup(reply_markup=calendar_markup)
        return CalcStates.END_DATE_CALC.value
    elif result is None:  # Пропустить — использовать текущую дату
        context.user_data['end_date'] = datetime.now().strftime("%Y-%m-%d")
        await query.edit_message_text("Конечная дата не выбрана, используется текущая дата.")
    else:  # Дата выбрана
        context.user_data['end_date'] = result
        await query.edit_message_text(f"Выбрана конечная дата: {result}")

    # Рассчитываем часы
    user_id = context.user_data['selected_user']['id']
    start_date = context.user_data['start_date']
    end_date = context.user_data.get('end_date')

    time_entries = get_time_entries(user_id, start_date, end_date)
    if not time_entries:
        await query.message.reply_text(
            f"Нет записей о времени для {context.user_data['selected_user']['name']} "
            f"с {start_date} по {end_date or 'сегодня'}."
        )
        return await show_main_menu(update, context)

    total_hours = sum(
        float(entry['hours'].replace('PT', '').replace('H', ''))
        for entry in time_entries
        if entry.get('hours')
    )

    await query.message.reply_text(
        f"Сотрудник: {context.user_data['selected_user']['name']}\n"
        f"Период: с {start_date} по {end_date or 'сегодня'}\n"
        f"Общее количество часов: {total_hours:.2f}"
    )
    return await show_main_menu(update, context)