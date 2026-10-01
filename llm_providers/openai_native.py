from typing import Dict, List, Optional, Type

from openai import BadRequestError, OpenAI
from pydantic import BaseModel

from llm_providers.base import LLMProvider, LLMResponse

class OpenAINativeProvider(LLMProvider):

    def __init__(self, api_key: str, model: str):
        self.model = model
        self.client = OpenAI(api_key=api_key)

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

        kwargs = dict(
            model=self.model,
            messages=full_messages,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            frequency_penalty=frequency_penalty,
        )
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            response = self.client.chat.completions.create(**kwargs)
        except BadRequestError:
            kwargs.pop("temperature", None)
            kwargs.pop("frequency_penalty", None)
            response = self.client.chat.completions.create(**kwargs)

        text = response.choices[0].message.content or ""
        return LLMResponse(text=text, raw_response=response)
