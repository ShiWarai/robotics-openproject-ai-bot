import requests
import json

class LMStudioClient:
    def __init__(self, url="http://localhost:1234/v1/chat/completions", model="gemma-3-4b-it-qat"):
        self.url = url
        self.model = model
        self.headers = {"Content-Type": "application/json"}

    def send_request(self, system_prompt: str, user_input: str, temperature: float = 0.1, max_tokens: int = 1000) -> str:
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
        try:
            response = requests.post(self.url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            return json.dumps({"error": f"Ошибка связи с LM Studio: {str(e)}"})

async def call_lm_studio(system_prompt: str, user_input: str) -> str:
    client = LMStudioClient()
    return client.send_request(system_prompt, user_input)