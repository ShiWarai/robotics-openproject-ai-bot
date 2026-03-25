import json
import logging
import time

import requests

logger = logging.getLogger(__name__)


class LMStudioClient:
    def __init__(self, url="http://localhost:1234/v1/chat/completions", model="gemma-3-4b-it-qat"):
        self.url = url
        self.model = model
        self.headers = {"Content-Type": "application/json"}

    def send_request(self, system_prompt: str, user_input: str, temperature: float = 0.3, max_tokens: int = 200) -> str:
        """Отправка запроса к LM Studio API."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        t0 = time.perf_counter()
        logger.info(
            "LM Studio: запрос → %s model=%r chars(system=%d user=%d) max_tokens=%s temp=%s",
            self.url,
            self.model,
            len(system_prompt),
            len(user_input),
            max_tokens,
            temperature,
        )
        try:
            response = requests.post(self.url, headers=self.headers, json=payload)
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            elapsed = time.perf_counter() - t0
            logger.info(
                "LM Studio: ответ за %.2f с, символов=%d",
                elapsed,
                len(text) if isinstance(text, str) else 0,
            )
            return text
        except requests.exceptions.RequestException as e:
            elapsed = time.perf_counter() - t0
            logger.warning(
                "LM Studio: сбой за %.2f с: %s",
                elapsed,
                e,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            return json.dumps({"error": f"Ошибка связи с LM Studio: {str(e)}"})

async def call_lm_studio(system_prompt: str, user_input: str) -> str:
    client = LMStudioClient()
    return client.send_request(system_prompt, user_input)