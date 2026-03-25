"""
Произвольный ввод при создании задачи: два этапа LLM (поля задачи + роли по участникам проекта).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import List, Optional, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from app.create_task.create_task import try_finish_free_task_creation
from app.estimated_time.parse_text_input import (
    CORRECTION_PROMPT,
    _strip_json_response,
)
from app.utils.lm_studio_client import call_lm_studio
from app.utils.rkllama_client import call_rkllama
from app.states import TaskStates
from app.utils.speech_recognition import process_voice_message
from app.utils.utils import show_main_menu, get_project_members
from app.variables import LLM_PROVIDER

logger = logging.getLogger(__name__)
CREATE_TASK_RKLLAMA_TEMPERATURE = 0.5


async def _call_llm_create_task(
    system_prompt: str,
    user_input: str,
    *,
    format_schema: Optional[dict] = None,
) -> str:
    """LLM вызов для create_task free-text: повышаем креативность только здесь."""
    t0 = time.perf_counter()
    logger.info(
        "create_task free: LLM старт provider=%s format_schema=%s temp=%s chars(system=%d user=%d)",
        LLM_PROVIDER,
        format_schema is not None,
        CREATE_TASK_RKLLAMA_TEMPERATURE if LLM_PROVIDER == "rkllama" else "n/a",
        len(system_prompt),
        len(user_input),
    )
    if LLM_PROVIDER == "rkllama":
        out = await call_rkllama(
            system_prompt,
            user_input,
            format_schema=format_schema,
            temperature=CREATE_TASK_RKLLAMA_TEMPERATURE,
        )
    else:
        out = await call_lm_studio(system_prompt, user_input)
    elapsed = time.perf_counter() - t0
    logger.info(
        "create_task free: LLM конец за %.2f с, ответ_chars=%d",
        elapsed,
        len(out) if isinstance(out, str) else 0,
    )
    return out

# --- JSON Schema (rkllama / format) ---

FORMAT_TASK_STAGE1 = {
    "type": "object",
    "properties": {
        "project_id": {"type": "integer", "description": "id проекта из списка"},
        "task_subject": {"type": "string", "description": "Краткое название задачи"},
        "task_description": {"type": "string", "description": "Описание задачи (может быть кратким)"},
        "start_date": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "YYYY-MM-DD или null",
        },
        "due_date": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "YYYY-MM-DD или null",
        },
        "estimated_hours": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": "Оценка в часах или null",
        },
        "assignee_hint": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Кто исполнитель по тексту, если явно; иначе null",
        },
        "responsible_hint": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Кто ответственный по тексту, если явно; иначе null",
        },
        "error_code": {
            "type": "integer",
            "description": "1 проект не найден, 2 нет названия, 3 бессмыслица",
        },
    },
}

FORMAT_TASK_ROLES = {
    "type": "object",
    "properties": {
        "assignee_name": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Точное имя из списка участников или null",
        },
        "responsible_name": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Точное имя из списка участников или null",
        },
        "error_code": {"type": "integer"},
    },
}

SCHEMA_STAGE1_JSON = json.dumps(FORMAT_TASK_STAGE1, ensure_ascii=False, indent=2)
SCHEMA_ROLES_JSON = json.dumps(FORMAT_TASK_ROLES, ensure_ascii=False, indent=2)

STAGE1_ERROR_MESSAGES = {
    1: "Проект не указан или не найден среди доступных.",
    2: "Не указано название задачи.",
    3: "Текст не похож на запрос на создание задачи.",
}


TASK_CREATE_STAGE1_PROMPT = """
Вы — помощник для создания задачи в OpenProject по произвольному тексту пользователя.
Верните один JSON-объект по схеме (project_id, task_subject, task_description, опционально даты и часы, подсказки ролей).

**Список проектов** (id и name):
{PROJECTS}

**Правила**:
- project_id: id проекта из списка, к которому относится запрос (сопоставление по смыслу с name).
- task_subject: короткое название задачи (обязательно, не пустая строка).
- task_description: описание; если в тексте только заголовок — можно дублировать или кратко пояснить.
- **Язык**: поля task_subject и task_description всегда формулируй **на русском языке**, даже если исходный запрос пользователя на английском или другом языке (переведи смысл корректно, без калькирования).
- start_date, due_date: строки YYYY-MM-DD или null. «Сегодня»/«завтра» считать от текущей даты.
- estimated_hours: целое число часов или null.
- assignee_hint / responsible_hint: кого пользователь назвал исполнителем/ответственным; если не сказано — null.
- error_code: 1 если проект не определён; 2 если нет смысла названия задачи; 3 если текст мусор.
- Ответ — только один JSON-объект, без пояснений.

**Примеры** (id в примерах условные):
- Текст про проект «Тестовый» id 7, задачу «Настроить CI» → {{ "project_id": 7, "task_subject": "Настроить CI", "task_description": "…", "start_date": null, "due_date": null, "estimated_hours": null, "assignee_hint": null, "responsible_hint": null }}
- Проект не ясен → {{ "error_code": 1 }}

Текущая дата: {DATE}

Текст для анализа: "{TEXT}"
"""

TASK_CREATE_ROLES_PROMPT = """
Вы — помощник для сопоставления ролей в задаче OpenProject. Участники проекта (выбирай **только** имена из этого списка; иначе null для автоназначения по умолчанию):

{MEMBERS}

Исходный текст пользователя:
"{TEXT}"

Подсказки из первого шага: исполнитель (hint): {ASSIGNEE_HINT!r}, ответственный (hint): {RESPONSIBLE_HINT!r}

**Правила**:
- assignee_name и responsible_name — либо **точное** значение поля "name" одного участника из списка, либо null.
- Если в тексте явно не назван исполнитель — assignee_name: null.
- Если не назван ответственный — responsible_name: null.
- Если имя похоже на участника, выбери одного с наилучшим совпадением; только имена из списка.
- Ответ — один JSON-объект, без пояснений.

**Примеры** (имена условные):
- Участники [{{"id":"1","name":"Иван Иванов"}}], в тексте «сделай задачу, исполнитель Иванов» → {{ "assignee_name": "Иван Иванов", "responsible_name": null }}
"""


def _build_stage1_prompt(project_list: List[dict], user_input: str) -> str:
    """Как в estimated_time/parse_text_input: .format с JSON в {PROJECTS}, дата и текст."""
    return TASK_CREATE_STAGE1_PROMPT.format(
        PROJECTS=json.dumps(project_list, ensure_ascii=False),
        DATE=datetime.now().strftime("%Y-%m-%d"),
        TEXT=(user_input[:8000] if user_input else ""),
    )


def _build_roles_prompt(
    project_users: List[dict],
    user_input: str,
    assignee_hint: Optional[str],
    responsible_hint: Optional[str],
) -> str:
    return TASK_CREATE_ROLES_PROMPT.format(
        MEMBERS=json.dumps(project_users, ensure_ascii=False),
        TEXT=(user_input[:8000] if user_input else ""),
        ASSIGNEE_HINT=assignee_hint,
        RESPONSIBLE_HINT=responsible_hint,
    )


def _sender_op_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    tid = str(update.effective_user.id)
    uname = (update.effective_user.username or "").strip()
    m = context.bot_data.get("USER_TELEGRAM_IDS", {})
    uid = m.get(tid) or (m.get(uname) if uname else None)
    return str(uid) if uid is not None else None


def _member_ids_set(project_users: List[dict]) -> set:
    return {str(u["id"]) for u in project_users}


def _match_member_by_name(name: Optional[str], project_users: List[dict]) -> Tuple[Optional[str], bool]:
    """
    Возвращает (user_id или None, ambiguous).
    ambiguous=True если несколько подходящих кандидатов.
    """
    if not name or not str(name).strip():
        return None, False
    raw = str(name).strip()
    low = raw.lower()
    exact = [u for u in project_users if u["name"].strip().lower() == low]
    if len(exact) == 1:
        return str(exact[0]["id"]), False
    if len(exact) > 1:
        return None, True
    substr = [
        u
        for u in project_users
        if low in u["name"].lower() or u["name"].lower() in low
    ]
    if len(substr) == 1:
        return str(substr[0]["id"]), False
    if len(substr) > 1:
        return None, True
    return None, False


def _resolve_role(
    llm_name: Optional[str],
    hint: Optional[str],
    project_users: List[dict],
    sender_id: Optional[str],
) -> Tuple[Optional[str], bool, bool]:
    """
    Возвращает (op_user_id или None, ambiguous, need_pick).
    need_pick: не удалось ни из LLM, ни дефолт на отправителя (отправитель не в проекте).
    """
    for candidate in (llm_name, hint):
        if candidate:
            uid, amb = _match_member_by_name(candidate, project_users)
            if amb:
                return None, True, False
            if uid:
                return uid, False, False

    if sender_id and sender_id in _member_ids_set(project_users):
        return sender_id, False, False
    return None, False, True


async def handle_create_task_free_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Текст или голос: этап 1 → участники → этап 2 → создание или фолбэк-клавиатуры."""
    user_input: Optional[str] = None

    if update.message.voice:
        try:
            user_input = await process_voice_message(update, context)
            await update.message.reply_text(f"Распознанный текст: {user_input}")
        except Exception as e:
            await update.message.reply_text(f"Ошибка распознавания голосового сообщения: {e}")
            return TaskStates.TASK_FREE_TEXT_INPUT.value
    else:
        user_input = update.message.text or ""

    projects = context.user_data.get("projects") or []
    project_list = [{"id": int(p["id"]), "name": p["name"]} for p in projects]

    prompt = _build_stage1_prompt(project_list, user_input or "")

    logger.info("create_task free: этап 1 LLM, сообщение длины %s", len(user_input or ""))
    raw_response = await _call_llm_create_task(prompt, user_input or "", format_schema=FORMAT_TASK_STAGE1)
    json_str = _strip_json_response(raw_response)
    correction_used = False

    while True:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            if not correction_used:
                correction_used = True
                raw_response = await _call_llm_create_task(
                    "Ты исправляешь ответ в валидный JSON. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_STAGE1_JSON,
                        CONTEXT="Список проектов: " + json.dumps(project_list, ensure_ascii=False),
                        RAW=raw_response,
                    ),
                    format_schema=FORMAT_TASK_STAGE1,
                )
                json_str = _strip_json_response(raw_response)
                continue
            await update.message.reply_text("Ошибка разбора JSON от модели. Попробуйте переформулировать.")
            return TaskStates.TASK_FREE_TEXT_INPUT.value

        if isinstance(data, dict) and "error" in data:
            logger.warning("create_task free: LLM ошибка — %s", data.get("error"))
            await update.message.reply_text(
                "Сервис LLM недоступен. Проверьте RKLLama/LM Studio или выберите «Через меню»."
            )
            return TaskStates.TASK_FREE_TEXT_INPUT.value

        err = data.get("error_code") if isinstance(data, dict) else None
        if err == 3:
            await update.message.reply_text(
                f"Ошибка: {STAGE1_ERROR_MESSAGES[3]}\nПопробуйте снова."
            )
            return TaskStates.TASK_FREE_TEXT_INPUT.value
        if err == 1 and data.get("project_id") is None:
            await update.message.reply_text(
                f"Ошибка: {STAGE1_ERROR_MESSAGES[1]}\nПопробуйте снова."
            )
            return TaskStates.TASK_FREE_TEXT_INPUT.value
        if err == 2 and not (data.get("task_subject") or "").strip():
            await update.message.reply_text(
                f"Ошибка: {STAGE1_ERROR_MESSAGES[2]}\nПопробуйте снова."
            )
            return TaskStates.TASK_FREE_TEXT_INPUT.value

        pid = data.get("project_id")
        subj = (data.get("task_subject") or "").strip() if isinstance(data, dict) else ""
        desc = (data.get("task_description") or "").strip() if isinstance(data, dict) else ""

        if pid is None or subj == "":
            if not correction_used:
                correction_used = True
                raw_response = await _call_llm_create_task(
                    "Ты исправляешь ответ в валидный JSON. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_STAGE1_JSON,
                        CONTEXT="Список проектов: " + json.dumps(project_list, ensure_ascii=False),
                        RAW=raw_response,
                    ),
                    format_schema=FORMAT_TASK_STAGE1,
                )
                json_str = _strip_json_response(raw_response)
                continue
            await update.message.reply_text("Не удалось извлечь проект или название задачи. Попробуйте снова.")
            return TaskStates.TASK_FREE_TEXT_INPUT.value

        break

    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        await update.message.reply_text("Неверный id проекта от модели. Попробуйте снова.")
        return TaskStates.TASK_FREE_TEXT_INPUT.value

    selected = next((p for p in projects if int(p["id"]) == pid_int), None)
    if not selected:
        await update.message.reply_text("Указанный проект не найден в списке. Попробуйте снова.")
        return TaskStates.TASK_FREE_TEXT_INPUT.value

    context.user_data["project_id"] = selected["id"]

    members = get_project_members(selected["id"])
    if not members or "_embedded" not in members or not members["_embedded"]["elements"]:
        await update.message.reply_text("Не удалось загрузить участников проекта.")
        return await show_main_menu(update, context)

    project_users = []
    for m in members["_embedded"]["elements"]:
        pl = m["_links"].get("principal", {})
        if pl and pl.get("href"):
            uid = pl["href"].split("/")[-1]
            title = pl.get("title", f"User {uid}")
            project_users.append({"id": str(uid), "name": title})

    if not project_users:
        await update.message.reply_text("В проекте нет участников с привязкой principal.")
        return await show_main_menu(update, context)

    logger.info(
        "create_task free: проект %s (%s), участников %s",
        selected["name"],
        selected["id"],
        len(project_users),
    )

    assignee_hint = data.get("assignee_hint")
    responsible_hint = data.get("responsible_hint")
    roles_prompt = _build_roles_prompt(project_users, user_input or "", assignee_hint, responsible_hint)

    logger.info("create_task free: этап 2 LLM (роли)")
    roles_raw = await _call_llm_create_task(roles_prompt, user_input or "", format_schema=FORMAT_TASK_ROLES)
    roles_str = _strip_json_response(roles_raw)
    correction2 = False
    while True:
        try:
            roles = json.loads(roles_str)
        except json.JSONDecodeError:
            if not correction2:
                correction2 = True
                roles_raw = await _call_llm_create_task(
                    "Ты исправляешь ответ в валидный JSON. Отвечай только JSON-объектом.",
                    CORRECTION_PROMPT.format(
                        SCHEMA=SCHEMA_ROLES_JSON,
                        CONTEXT="Участники: " + json.dumps(project_users, ensure_ascii=False),
                        RAW=roles_raw,
                    ),
                    format_schema=FORMAT_TASK_ROLES,
                )
                roles_str = _strip_json_response(roles_raw)
                continue
            await update.message.reply_text("Ошибка разбора ответа по ролям. Попробуйте снова.")
            return TaskStates.TASK_FREE_TEXT_INPUT.value

        if isinstance(roles, dict) and "error" in roles:
            logger.warning("create_task free: LLM роли — %s", roles.get("error"))
            await update.message.reply_text("Сервис LLM недоступен при разборе ролей.")
            return TaskStates.TASK_FREE_TEXT_INPUT.value

        break

    sender_id = _sender_op_user_id(update, context)
    if not sender_id:
        await update.message.reply_text("Ваш Telegram не сопоставлен с OpenProject. Обратитесь к администратору.")
        return TaskStates.TASK_FREE_TEXT_INPUT.value

    aname = roles.get("assignee_name") if isinstance(roles, dict) else None
    rname = roles.get("responsible_name") if isinstance(roles, dict) else None

    if aname is not None and isinstance(aname, str) and aname.strip() == "":
        aname = None
    if rname is not None and isinstance(rname, str) and rname.strip() == "":
        rname = None

    assignee_id, a_amb, need_a = _resolve_role(aname, assignee_hint, project_users, sender_id)
    if a_amb:
        logger.warning("create_task free: неоднозначный исполнитель")
        need_a = True
        assignee_id = None

    responsible_id, r_amb, need_r = _resolve_role(rname, responsible_hint, project_users, sender_id)
    if r_amb:
        logger.warning("create_task free: неоднозначный ответственный")
        need_r = True
        responsible_id = None

    start_date = data.get("start_date")
    due_date = data.get("due_date")
    if start_date and isinstance(start_date, str):
        start_date = start_date.strip() or None
    else:
        start_date = None
    if due_date and isinstance(due_date, str):
        due_date = due_date.strip() or None
    else:
        due_date = None

    est = data.get("estimated_hours")
    est_str = None
    if est is not None and isinstance(est, int) and est > 0:
        est_str = str(est)
    elif est is not None and isinstance(est, float) and est > 0:
        est_str = str(int(est))

    if desc == "":
        desc = subj

    context.user_data["task_free_draft"] = {
        "project_id": str(selected["id"]),
        "project_name": selected["name"],
        "task_name": subj,
        "task_description": desc,
        "start_date": start_date,
        "due_date": due_date,
        "estimated_time": est_str,
        "assignee_id": assignee_id,
        "responsible_id": responsible_id,
        "project_users": project_users,
        "need_assignee_pick": need_a,
        "need_responsible_pick": need_r,
    }

    logger.info(
        "create_task free: черновик assignee_id=%s responsible_id=%s need_pick A=%s R=%s",
        assignee_id,
        responsible_id,
        need_a,
        need_r,
    )

    return await try_finish_free_task_creation(update, context)
