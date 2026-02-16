from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class CustomCalendar:
    def __init__(self):
        self.current_date = datetime.now()
        self.selected_date = None

    def build_month(self, year=None, month=None):
        """Создаёт клавиатуру с выбором дней месяца"""
        if year is None:
            year = self.current_date.year
        if month is None:
            month = self.current_date.month

        # Определяем количество дней в месяце
        next_month = (month % 12) + 1 if month < 12 else 1
        next_year = year + 1 if month == 12 else year
        days_in_month = (datetime(next_year, next_month, 1) - datetime(year, month, 1)).days

        # Создаём клавиатуру
        keyboard = []
        # Заголовок с месяцем и годом
        month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                       "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        keyboard.append([InlineKeyboardButton(f"{month_names[month - 1]} {year}", callback_data="ignore")])

        # Дни недели
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        keyboard.append([InlineKeyboardButton(day, callback_data="ignore") for day in weekdays])

        # Заполняем дни
        first_day = datetime(year, month, 1)
        start_weekday = first_day.weekday()  # 0 = Понедельник, 6 = Воскресенье
        week = [" " for _ in range(start_weekday)]  # Пустые клетки до начала месяца

        # Определяем текущий день для выделения
        today = datetime.now()
        is_current_month = today.year == year and today.month == month
        current_day = today.day if is_current_month else None

        for day in range(1, days_in_month + 1):
            # Добавляем эмодзи 🟢 для текущего дня
            display_text = f"🟢 {day}" if day == current_day else str(day)
            week.append(display_text)
            if len(week) == 7:
                keyboard.append([InlineKeyboardButton(
                    d if d != " " else " ",
                    callback_data=f"day_{year}_{month:02d}_{int(d.replace('🟢 ', '')):02d}" if d != " " and d.startswith("🟢") else f"day_{year}_{month:02d}_{int(d):02d}" if d != " " else "ignore"
                ) for d in week])
                week = []

        if week:
            week += [" " for _ in range(7 - len(week))]
            keyboard.append([InlineKeyboardButton(
                d if d != " " else " ",
                callback_data=f"day_{year}_{month:02d}_{int(d.replace('🟢 ', '')):02d}" if d != " " and d.startswith("🟢") else f"day_{year}_{month:02d}_{int(d):02d}" if d != " " else "ignore"
            ) for d in week])

        # Кнопки навигации
        keyboard.append([
            InlineKeyboardButton("<< Пред",
                                 callback_data=f"month_{year - 1}_{month}" if month == 1 else f"month_{year}_{month - 1}"),
            InlineKeyboardButton("Пропустить", callback_data="skip"),
            InlineKeyboardButton("След >>",
                                 callback_data=f"month_{year + 1}_{1}" if month == 12 else f"month_{year}_{month + 1}")
        ])

        return InlineKeyboardMarkup(keyboard)

    def process(self, callback_data):
        """Обрабатывает выбор пользователя"""
        if callback_data == "skip":
            return None
        if callback_data.startswith("day_"):
            _, year, month, day = callback_data.split("_")
            self.selected_date = datetime(int(year), int(month), int(day))
            return self.selected_date.strftime("%Y-%m-%d")
        if callback_data.startswith("month_"):
            _, year, month = callback_data.split("_")
            self.current_date = datetime(int(year), int(month), 1)
            return False  # Возвращаем False, чтобы показать новый месяц
        return None  # Игнорируем другие callback_data