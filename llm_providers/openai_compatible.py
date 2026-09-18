from typing import List, Dict, Optional, Type
from openai import OpenAI, APIError
from pydantic import BaseModel

from llm_providers.base import LLMProvider, LLMResponse


class OpenAICompatibleProvider(LLMProvider):

    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 800,
        response_schema: Optional[Type[BaseModel]] = None,
        frequency_penalty: float = 0.0,
    ) -> LLMResponse:
        full_messages = [{
            "role": "system",
            "content": system_prompt
        }] + messages

        response_format = None
        if response_schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "schema": response_schema.model_json_schema(),
                },
            }

        try:
            response = self._create(full_messages, temperature, max_tokens,
                                    response_format, frequency_penalty)
        except APIError:
            if response_format is None:
                raise
            response = self._create(full_messages, temperature, max_tokens,
                                    None, frequency_penalty)

        text = response.choices[0].message.content or ""
        return LLMResponse(text=text, raw_response=response)

    def _create(self,
                full_messages,
                temperature,
                max_tokens,
                response_format,
                frequency_penalty=0.0):
        kwargs = dict(
            model=self.model,
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            frequency_penalty=frequency_penalty,
        )
        if response_format is not None:
            kwargs["response_format"] = response_format
        return self.client.chat.completions.create(**kwargs)
