import json
import os
import subprocess
import wave

import aiofiles
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes
from vosk import Model, KaldiRecognizer

# Модель Vosk для русского языка (нужно скачать вручную и распаковать в cache/)
VOSK_MODEL_NAME = "vosk-model-small-ru-0.22"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache")
_MODEL_PATH = os.path.join(_CACHE_DIR, VOSK_MODEL_NAME)

_model = None


def _get_model():
    """Ленивая загрузка модели Vosk (только при первом голосовом сообщении). Модель должна быть в cache/."""
    global _model
    if _model is None:
        if not os.path.isdir(_MODEL_PATH) or not os.path.exists(os.path.join(_MODEL_PATH, "conf")):
            raise FileNotFoundError(
                f"Модель Vosk не найдена: {_MODEL_PATH}. "
                "Скачайте vosk-model-small-ru-0.22 с https://alphacephei.com/vosk/models и распакуйте в папку cache/."
            )
        _model = Model(_MODEL_PATH)
    return _model

FFMPEG_REQUIRED_MSG = (
    "Для голосовых сообщений нужен ffmpeg. "
    "Установите: sudo apt install ffmpeg (Linux) или скачайте с https://ffmpeg.org (Windows)."
)


async def convert_ogg_to_wav(ogg_path: str, wav_path: str) -> bool:
    """Конвертирует OGG файл в WAV с помощью ffmpeg."""
    try:
        subprocess.run(
            ["ffmpeg", "-i", ogg_path, "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_path],
            check=True, capture_output=True
        )
        return True
    except FileNotFoundError as e:
        if getattr(e, "filename", None) == "ffmpeg" or "ffmpeg" in str(e):
            raise RuntimeError(FFMPEG_REQUIRED_MSG) from e
        raise
    except subprocess.CalledProcessError as e:
        print(f"Ошибка конвертации OGG в WAV: {e}")
        return False

async def recognize_speech(file_path: str) -> str:
    """Распознаёт речь из WAV файла с использованием Vosk."""
    model = _get_model()

    wf = wave.open(file_path, "rb")
    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
        wf.close()
        raise ValueError("Аудиофайл должен быть WAV, моно, 16 бит, 16000 Гц")

    recognizer = KaldiRecognizer(model, wf.getframerate())
    recognizer.SetWords(True)

    result_text = ""
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            result_text += result.get("text", "") + " "

    final_result = json.loads(recognizer.FinalResult())
    result_text += final_result.get("text", "")
    wf.close()
    return result_text.strip()

async def process_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Обрабатывает голосовое сообщение, конвертирует и распознаёт речь. Временные файлы — в cache/."""
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    os.makedirs(_CACHE_DIR, exist_ok=True)
    ogg_path = os.path.join(_CACHE_DIR, f"voice_{voice.file_unique_id}.ogg")
    wav_path = os.path.join(_CACHE_DIR, f"voice_{voice.file_unique_id}.wav")

    # Скачиваем OGG в cache/
    async with aiohttp.ClientSession() as session:
        async with session.get(file.file_path) as response:
            if response.status == 200:
                async with aiofiles.open(ogg_path, "wb") as f:
                    await f.write(await response.read())
            else:
                raise Exception(f"Ошибка скачивания голосового сообщения: {response.status}")

    # Конвертируем OGG в WAV
    if not await convert_ogg_to_wav(ogg_path, wav_path):
        os.remove(ogg_path)
        raise Exception("Ошибка конвертации голосового сообщения в WAV")

    # Распознаём речь
    try:
        recognized_text = await recognize_speech(wav_path)
        if not recognized_text:
            raise Exception("Не удалось распознать текст из голосового сообщения")
        return recognized_text
    finally:
        # Удаляем временные файлы
        for path in [ogg_path, wav_path]:
            if os.path.exists(path):
                os.remove(path)