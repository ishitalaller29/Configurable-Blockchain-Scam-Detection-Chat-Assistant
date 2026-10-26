import time
from typing import Dict, List, Optional, Type

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from llm_providers.base import LLMProvider, LLMResponse

class GeminiNativeProvider(LLMProvider):

    def __init__(self, api_key: str, model: str,
                 thinking_budget: Optional[int] = None):
        self.model = model
        self.thinking_budget = thinking_budget
        self.client = genai.Client(api_key=api_key)

    def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 800,
        response_schema: Optional[Type[BaseModel]] = None,
        frequency_penalty: float = 0.0,
    ) -> LLMResponse:
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages if m.get("content")
        ]

        config = dict(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if frequency_penalty:
            config["frequency_penalty"] = frequency_penalty
        if self.thinking_budget is not None:
            config["thinking_config"] = types.ThinkingConfig(
                thinking_budget=self.thinking_budget)
        if response_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = response_schema

        try:
            response = self._create(contents, config)
        except errors.ClientError as error:
            # Only a 400 means the schema or penalty was rejected - retrying a 429 would just burn more quota.
            if error.code != 400 or (response_schema is None
                                     and not frequency_penalty):
                raise
            config.pop("response_schema", None)
            config.pop("frequency_penalty", None)
            response = self._create(contents, config)

        return LLMResponse(text=response.text or "", raw_response=response)

    def _create(self, contents, config):
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config),
                )
            except errors.APIError as error:
                wait = _retry_wait(error)
                if attempt == MAX_RETRIES or wait is None:
                    raise
                time.sleep(wait)


MAX_RETRIES = 2
# Longer waits (e.g. the free tier's daily limit) fail straight away rather than hanging the chat.
MAX_RETRY_WAIT = 30


def _retry_wait(error: errors.APIError) -> Optional[float]:
    # Seconds to wait before retrying a busy (503) or per-minute rate-limited (429) call, or None to give up.
    if error.code == 503:
        return 5.0
    if error.code != 429:
        return None
    details = (error.details or {}).get("error", {}).get("details", [])
    for item in details:
        delay = item.get("retryDelay")
        if delay and delay.endswith("s"):
            seconds = float(delay[:-1]) + 1
            return seconds if seconds <= MAX_RETRY_WAIT else None
    return None