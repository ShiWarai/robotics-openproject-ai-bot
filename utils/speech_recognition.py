import json
import os
import subprocess
import wave

import aiofiles
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes
from vosk import Model, KaldiRecognizer

# Путь к модели Vosk (нужно скачать модель, например, vosk-model-small-ru-0.22)
MODEL_PATH = "vosk-model-small-ru-0.22"
model = Model(MODEL_PATH)

async def convert_ogg_to_wav(ogg_path: str, wav_path: str) -> bool:
    """Конвертирует OGG файл в WAV с помощью ffmpeg."""
    try:
        subprocess.run(
            ["ffmpeg", "-i", ogg_path, "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_path],
            check=True, capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка конвертации OGG в WAV: {e}")
        return False

async def recognize_speech(file_path: str) -> str:
    """Распознаёт речь из WAV файла с использованием Vosk."""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Модель Vosk не найдена по пути: {MODEL_PATH}")

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
    """Обрабатывает голосовое сообщение, конвертирует и распознаёт речь."""
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    # Скачиваем OGG файл
    ogg_path = f"voice_{voice.file_unique_id}.ogg"
    wav_path = f"voice_{voice.file_unique_id}.wav"
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