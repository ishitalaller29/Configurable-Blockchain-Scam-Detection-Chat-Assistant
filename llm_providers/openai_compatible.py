from typing import List, Dict
from openai import OpenAI

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
    ) -> LLMResponse:
        full_messages = [{
            "role": "system",
            "content": system_prompt
        }] + messages
        response = self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        return LLMResponse(text=text, raw_response=response)
