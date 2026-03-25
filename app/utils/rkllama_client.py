import json
import logging
import time
from typing import Optional, Tuple, List

import requests

logger = logging.getLogger(__name__)

from app.variables import (
    RKLLAMA_URL,
    RKLLAMA_MODEL,
    RKLLAMA_TIMEOUT,
    RKLLAMA_THINKING,
    RKLLAMA_TEMPERATURE,
    RKLLAMA_MAX_NEW_TOKENS,
)


def get_available_models(url: Optional[str] = None) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Запрашивает список моделей у RKLLama (GET /api/tags).
    Возвращает (список имён моделей, None) при успехе или (None, сообщение об ошибке).
    """
    base_url = (url or RKLLAMA_URL or "").rstrip("/")
    if not base_url:
        return None, "RKLLAMA_URL не задан"
    tags_url = f"{base_url}/api/tags"
    try:
        response = requests.get(tags_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        models = data.get("models") or []
        names = [m.get("name") or m.get("model") for m in models if m.get("name") or m.get("model")]
        return names, None
    except requests.exceptions.RequestException as e:
        return None, f"Не удалось запросить список моделей: {e}"


def check_model_available() -> Optional[str]:
    """
    Проверяет при старте, что RKLLAMA_MODEL есть в списке доступных моделей RKLLama.
    Печатает результат проверки в консоль. Возвращает None при успехе или пропуске, иначе — сообщение об ошибке.
    """
    url = RKLLAMA_URL
    model = RKLLAMA_MODEL
    if not url or not model:
        print("RKLLama: не настроен (RKLLAMA_URL или RKLLAMA_MODEL не заданы), проверка модели пропущена.")
        return None
    names, err = get_available_models(url)
    if err:
        return err
    if model not in names:
        return (
            f"Модель RKLLAMA_MODEL={model!r} не найдена в RKLLama. "
            f"Доступные модели: {', '.join(names) or 'нет'}. "
            "Проверьте RKLLAMA_MODEL в .env и что сервер rkllama запущен (например, docker-compose)."
        )
    print(f"RKLLama: модель {model!r} проверена.")
    return None


def send_request(
    system_prompt: str,
    user_input: str,
    *,
    url: Optional[str] = None,
    model: Optional[str] = None,
    format_json: bool = True,
    format_schema: Optional[dict] = None,
    enable_thinking: Optional[bool] = None,
    timeout: Optional[int] = None,
    temperature: Optional[float] = None,
) -> str:
    """Отправка запроса к RKLLama (Ollama-совместимый API). format_schema — строгая JSON Schema. enable_thinking — режим рассуждений (по умолчанию из RKLLAMA_THINKING)."""
    url = url or RKLLAMA_URL
    model = model or RKLLAMA_MODEL
    timeout = timeout if timeout is not None else RKLLAMA_TIMEOUT
    thinking = enable_thinking if enable_thinking is not None else RKLLAMA_THINKING
    if not url or not model:
        logger.warning("RKLLama: пропуск запроса — не заданы RKLLAMA_URL или RKLLAMA_MODEL")
        return json.dumps({
            "error": "Не заданы RKLLAMA_URL или RKLLAMA_MODEL. Укажите их в .env."
        })
    chat_url = f"{url.rstrip('/')}/api/chat"
    fmt = "schema" if format_schema is not None else ("json" if format_json else "none")
    temp = temperature if temperature is not None else RKLLAMA_TEMPERATURE
    t0 = time.perf_counter()
    logger.info(
        "RKLLama: запрос → %s model=%r timeout=%s thinking=%s format=%s "
        "chars(system=%d user=%d) num_predict=%s temperature=%s",
        chat_url,
        model,
        timeout,
        thinking,
        fmt,
        len(system_prompt),
        len(user_input),
        RKLLAMA_MAX_NEW_TOKENS,
        temp,
    )
    headers = {"Content-Type": "application/json"}

    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "enable_thinking": thinking,
    }
    if format_schema is not None:
        payload["format"] = format_schema
    elif format_json:
        payload["format"] = "json"
    options = {"num_predict": RKLLAMA_MAX_NEW_TOKENS}
    if temp is not None:
        options["temperature"] = temp
    payload["options"] = options

    try:
        response = requests.post(chat_url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        result = content if isinstance(content, str) else json.dumps(content)
        elapsed = time.perf_counter() - t0
        logger.info(
            "RKLLama: ответ за %.2f с, символов в теле ответа=%d",
            elapsed,
            len(result),
        )
        return result
    except requests.exceptions.RequestException as e:
        elapsed = time.perf_counter() - t0
        logger.warning(
            "RKLLama: сбой запроса за %.2f с: %s",
            elapsed,
            e,
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )
        return json.dumps({"error": f"Ошибка связи с RKLLama: {str(e)}"})


async def call_rkllama(
    system_prompt: str,
    user_input: str,
    *,
    format_schema: Optional[dict] = None,
    enable_thinking: Optional[bool] = None,
    temperature: Optional[float] = None,
) -> str:
    """Асинхронная обёртка для вызова RKLLama. format_schema — строгая JSON Schema. enable_thinking — из RKLLAMA_THINKING или переопределение."""
    return send_request(
        system_prompt,
        user_input,
        format_schema=format_schema,
        enable_thinking=enable_thinking,
        temperature=temperature,
    )
