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
    TASK_INPUT_METHOD_CHOICE = 9
    TASK_FREE_TEXT_INPUT = 10
    TASK_FREE_FALLBACK_ASSIGNEE = 11
    TASK_FREE_FALLBACK_RESPONSIBLE = 12
    TASK_AFTER_CREATE_CHOICE = 13

class TimeStates(Enum):
    INPUT_METHOD_CHOICE = 99
    FREE_TEXT_INPUT = 100     # Произвольный ввод текста или голосового сообщения
    PROJECT_CHOICE_TEXT = 101 # Устаревшее состояние, оставлено для обратной совместимости
    TEXT_INPUT = 102         # Устаревшее состояние, оставлено для обратной совместимости
    PROJECT_CHOICE_TIME = 103
    TASK_CHOICE_TIME = 104
    DATE_CHOICE_TIME = 105
    PERSON_CHOICE_TIME = 106
    HOURS_INPUT_TIME = 107
    ADD_ANOTHER_TIME = 108

class CalcStates(Enum):
    EMPLOYEE_CHOICE = 200
    START_DATE_CALC = 201
    END_DATE_CALC = 202
    SHOW_RESULT = 203