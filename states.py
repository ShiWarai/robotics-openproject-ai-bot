from enum import Enum

class MainStates(Enum):
    MENU = 0

class TaskStates(Enum):
    PROJECT_CHOICE = 1
    TASK_NAME = 2
    TASK_DESCRIPTION = 3
    ASSIGNEE_CHOICE = 4
    RESPONSIBLE_CHOICE = 5
    START_DATE = 6
    DUE_DATE = 7
    ESTIMATED_TIME = 8

class TimeStates(Enum):
    INPUT_METHOD_CHOICE = 99
    PROJECT_CHOICE_TEXT = 100  # Выбор проекта для текстового ввода
    TEXT_INPUT = 101          # Ввод текста после выбора проекта
    PROJECT_CHOICE_TIME = 102
    TASK_CHOICE_TIME = 103
    DATE_CHOICE_TIME = 104
    PERSON_CHOICE_TIME = 106
    HOURS_INPUT_TIME = 107
    ADD_ANOTHER_TIME = 108

class CalcStates(Enum):
    EMPLOYEE_CHOICE = 200
    START_DATE_CALC = 201
    END_DATE_CALC = 202
    SHOW_RESULT = 203