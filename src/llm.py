"""
Drop-in OpenAI-compatible client using httpx.
Replaces the openai package — same interface: client.chat.completions.create(...)
"""

import os
import httpx
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Message:
    content: str
    role: str = "assistant"


@dataclass
class Choice:
    message: Message


@dataclass
class Completion:
    choices: list


class Completions:
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key  = api_key

    def create(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Any] = None,
        **kwargs,
    ) -> Completion:
        payload: dict = {
            "model":       model,
            "messages":    messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }
        if response_format is not None:
            if hasattr(response_format, "type"):
                payload["response_format"] = {"type": response_format.type}
            elif isinstance(response_format, dict):
                payload["response_format"] = response_format

        with httpx.Client(timeout=60) as c:
            r = c.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
        r.raise_for_status()
        data = r.json()
        choices = [
            Choice(message=Message(content=ch["message"]["content"], role=ch["message"]["role"]))
            for ch in data.get("choices", [])
        ]
        return Completion(choices=choices)


class Chat:
    def __init__(self, base_url: str, api_key: str):
        self.completions = Completions(base_url, api_key)


class OpenAI:
    """Minimal OpenAI-compatible client backed by httpx."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        key  = api_key  or os.getenv("AIML_API_KEY", "")
        url  = base_url or os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
        self.chat = Chat(base_url=url, api_key=key)
