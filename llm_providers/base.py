from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Dict, Optional, Type

from pydantic import BaseModel


@dataclass
class LLMResponse:
    text: str
    raw_response: Any


class LLMProvider(ABC):

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 800,
        response_schema: Optional[Type[BaseModel]] = None,
        frequency_penalty: float = 0.0,
    ) -> LLMResponse:
        ...
