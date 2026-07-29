import json
import os

import aiofiles
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

# Корень проекта (родитель app/) — временные голосовые файлы в cache/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache")

# OpenAI-совместимый HTTP API whisper-rknn (POST /v1/audio/transcriptions)
WHISPER_RKNN_URL = os.environ.get("WHISPER_RKNN_URL", "").strip().rstrip("/")
WHISPER_API_KEY = os.environ.get("WHISPER_API_KEY", "").strip()


def _require_whisper_url() -> None:
    if not WHISPER_RKNN_URL:
        raise RuntimeError(
            "WHISPER_RKNN_URL пустой — задайте URL API Whisper (например в .env или docker-compose)."
        )


def _whisper_headers() -> dict[str, str]:
    if WHISPER_API_KEY:
        return {"Authorization": f"Bearer {WHISPER_API_KEY}"}
    return {}


async def _transcribe_whisper_rknn(ogg_path: str) -> str:
    """POST OGG на /v1/audio/transcriptions (декодирование и ресэмплинг на стороне API)."""
    url = f"{WHISPER_RKNN_URL}/v1/audio/transcriptions"
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiofiles.open(ogg_path, "rb") as af:
        body = await af.read()
    data = aiohttp.FormData()
    data.add_field("file", body, filename="voice.ogg", content_type="audio/ogg")
    data.add_field("model", "whisper-1")
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, data=data, headers=_whisper_headers()) as resp:
            raw = await resp.text()
            if resp.status != 200:
                raise RuntimeError(
                    f"Whisper RKNN API ошибка {resp.status}: {raw[:500]}"
                )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Whisper RKNN API: неверный JSON: {raw[:200]}") from e
    text = (payload.get("text") or "").strip()
    if not text:
        raise RuntimeError("Пустой текст от Whisper RKNN API")
    return text


async def process_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Скачивает голос, отправляет в Whisper RKNN API, удаляет временный файл."""
    _require_whisper_url()

    voice = update.message.voice
    tg_file = await context.bot.get_file(voice.file_id)

    os.makedirs(_CACHE_DIR, exist_ok=True)
    ogg_path = os.path.join(_CACHE_DIR, f"voice_{voice.file_unique_id}.ogg")

    # Через клиент бота (httpx + HTTP_PROXY), а не отдельный aiohttp — иначе в РФ таймаут на api.telegram.org
    await tg_file.download_to_drive(custom_path=ogg_path)

    try:
        return await _transcribe_whisper_rknn(ogg_path)
    finally:
        if os.path.exists(ogg_path):
            os.remove(ogg_path)
