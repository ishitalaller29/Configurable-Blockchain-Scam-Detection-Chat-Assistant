import json

from llm_providers.base import LLMProvider
from schema import BusinessAnalyserOutput

SYSTEM_PROMPT = """You are the Business Analyser for a blockchain scam-detection chat assistant.

Given a single user chat message, you must:
1. Decide if it is in-scope: a question about a specific blockchain address, contract, token, or transaction (scam check, info lookup, or a general blockchain question). Anything unrelated to blockchain (e.g. "what's the weather") is out of scope.
2. If in scope, classify request_type as exactly one of: "scam_check", "address_info" "general_question".
3. For "scam_check": extract raw_input as {"type": one of ["address","token_name","tx_hash","contract","unknown"], "value": <string taken from the message>}. If you cannot confidently identify a concrete input, set type to "unknown"; never invent an address that isn't in the message.
4. No detector is currently configured, so always set: selected_detector: null, detector_configured: false, required_input_type: "address_with_context", needs_resolution: false, resolution_plan: [].
5. For "general_question", or if in_scope is false, put a short direct plain-language answer in "direct_response" and leave the scam_check-only fields null/default.

Respond with ONLY a single JSON object, no prose, no markdown code fences, matching
this shape exactly:
{
  "in_scope": true,
  "request_type": "scam_check",
  "raw_input": {"type": "address", "value": "0xABC..."},
  "chain": "ethereum",
  "selected_detector": null,
  "detector_configured": false,
  "required_input_type": "address_with_context",
  "needs_resolution": false,
  "resolution_plan": [],
  "direct_response": null
}
"""


class BusinessAnalyser:
    def __init__(self, provider: LLMProvider, temperature: float = 0.3, max_tokens: int = 800):
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens

    def analyse(self, user_message: str) -> BusinessAnalyserOutput:
        response = self.provider.generate(
            system_prompt=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        data = _parse_json(response.text)
        return BusinessAnalyserOutput(**data)


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Business Analyser did not return valid JSON. Raw output:\n{text}"
        ) from e
