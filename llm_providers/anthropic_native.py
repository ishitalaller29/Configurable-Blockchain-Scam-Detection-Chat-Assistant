import json
from typing import Dict, List, Optional, Type

from anthropic import Anthropic
from pydantic import BaseModel

from llm_providers.base import LLMProvider, LLMResponse

class AnthropicNativeProvider(LLMProvider):

    def __init__(self, api_key: str, model: str):
        self.model = model
        self.client = Anthropic(api_key=api_key)

    def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 800,
        response_schema: Optional[Type[BaseModel]] = None,
        frequency_penalty: float = 0.0,
    ) -> LLMResponse:
        chat = [{"role": m["role"], "content": m["content"]}
                for m in messages if m.get("content")]

        kwargs = dict(
            model=self.model,
            system=system_prompt,
            messages=chat,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if response_schema is not None:
            tool_name = response_schema.__name__
            kwargs["tools"] = [{
                "name": tool_name,
                "description": "Return the final answer in this structure.",
                "input_schema": response_schema.model_json_schema(),
            }]
            kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

        response = self.client.messages.create(**kwargs)

        if response_schema is not None:
            for block in response.content:
                if block.type == "tool_use":
                    return LLMResponse(text=json.dumps(block.input),
                                       raw_response=response)

        text = "".join(b.text for b in response.content if b.type == "text")
        return LLMResponse(text=text, raw_response=response)