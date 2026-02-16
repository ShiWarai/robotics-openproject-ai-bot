import json
import os
from typing import Optional, Tuple, List

import requests


def _get_url() -> Optional[str]:
    return os.getenv("RKLLAMA_URL") or None


def _get_model() -> Optional[str]:
    return os.getenv("RKLLAMA_MODEL") or None


def _get_timeout() -> Optional[int]:
    raw = os.getenv("RKLLAMA_TIMEOUT")
    return int(raw) if raw is not None and raw.strip() else None


def _get_thinking() -> bool:
    raw = os.getenv("RKLLAMA_THINKING", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _get_temperature() -> Optional[float]:
    raw = os.getenv("RKLLAMA_TEMPERATURE", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _get_max_new_tokens() -> int:
    raw = os.getenv("RKLLAMA_MAX_NEW_TOKENS", "").strip()
    if not raw:
        return 4096
    try:
        n = int(raw)
        return max(1, min(n, 128_000))
    except ValueError:
        return 4096


def get_available_models(url: Optional[str] = None) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Запрашивает список моделей у RKLLama (GET /api/tags).
    Возвращает (список имён моделей, None) при успехе или (None, сообщение об ошибке).
    """
    base_url = (url or _get_url() or "").rstrip("/")
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
    url = _get_url()
    model = _get_model()
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
) -> str:
    """Отправка запроса к RKLLama (Ollama-совместимый API). format_schema — строгая JSON Schema. enable_thinking — режим рассуждений (по умолчанию из RKLLAMA_THINKING)."""
    url = url or _get_url()
    model = model or _get_model()
    timeout = timeout if timeout is not None else _get_timeout()
    thinking = enable_thinking if enable_thinking is not None else _get_thinking()
    if not url or not model:
        return json.dumps({
            "error": "Не заданы RKLLAMA_URL или RKLLAMA_MODEL. Укажите их в .env."
        })
    chat_url = f"{url.rstrip('/')}/api/chat"
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
    options = {"num_predict": _get_max_new_tokens()}
    temp = _get_temperature()
    if temp is not None:
        options["temperature"] = temp
    payload["options"] = options

    try:
        response = requests.post(chat_url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        return content if isinstance(content, str) else json.dumps(content)
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Ошибка связи с RKLLama: {str(e)}"})


async def call_rkllama(
    system_prompt: str,
    user_input: str,
    *,
    format_schema: Optional[dict] = None,
    enable_thinking: Optional[bool] = None,
) -> str:
    """Асинхронная обёртка для вызова RKLLama. format_schema — строгая JSON Schema. enable_thinking — из RKLLAMA_THINKING или переопределение."""
    return send_request(system_prompt, user_input, format_schema=format_schema, enable_thinking=enable_thinking)
