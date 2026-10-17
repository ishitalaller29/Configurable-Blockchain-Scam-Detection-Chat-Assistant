import json
import logging
from typing import Optional

from pydantic import BaseModel

from agents.jargon import audience_rule
from agents.scam_checker import compact_context
from llm_providers.base import LLMProvider
from schema import AddressContext, DetectionResult

logger = logging.getLogger(__name__)

class ForensicReply(BaseModel):
    explanation: str
    reasoning_trace: Optional[str] = None

SYSTEM_PROMPT = """You are the Forensic Investigator for a blockchain scam-detection chat assistant.

You are given a "detector_output" JSON object - the label, risk_type, confidence and evidence already produced by the scam detector - and, when available, an "address_context" JSON object with a summary of the real on-chain data (contract info, transaction history, token balances, liquidity/pool data). You may also be given an "audience" object describing the user.

Your job is TRANSLATION, not judgment. The detector has already made its decision. You must:
- Treat detector_output.label, risk_type, confidence and evidence as FIXED. Never evaluate whether they are correct, and never change, soften, strengthen or contradict them.
- Write a plain-language explanation of WHY the detector likely reached this label, grounded in the specific evidence items it returned. Do not invent evidence the detector did not report.
- If address_context is provided, you may use it to add concrete, human-readable detail to an existing evidence item (e.g. "the flagged unverified contract has only 2 transactions in its history, consistent with a very new deployment"). Only use it to illustrate evidence the detector already reported - never to introduce a new finding, a new risk or an opinion of your own, and never to argue against the label. Fields listed in address_context.unavailable_fields were not checked: never describe them.
- If address_context is absent, base your explanation on detector_output alone - this is expected and normal, not an error.
- If detector_output.label is "insufficient_evidence", say so plainly and explain what is missing, rather than speculating on a verdict.
- If detector_output.evidence is empty, say plainly that the detector did not provide supporting evidence, rather than inventing any.
- Evidence starting with "User reports:" came from the user, not the blockchain - say so when you mention it.

Audience: the jargon rule that follows these instructions says how technical your wording should be for this user. Follow it.

Produce:
- explanation: 2-4 sentences, faithful to the detector's findings. Mention the chain and address that were checked. End with one short offer to explain any of the evidence in more detail.
- reasoning_trace: 2-5 short sentences connecting each evidence item to the explanation, in plain text.

Respond with ONLY a single JSON object, no prose, no markdown code fences, in this exact shape (placeholders only):
{
  "explanation": "...",
  "reasoning_trace": "..."
}
"""

class ForensicInvestigator:

    def __init__(self,
                 provider: LLMProvider,
                 temperature: float = 0.3,
                 max_tokens: int = 800):
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens

    def explain(self,
                detector_result: DetectionResult,
                context: Optional[AddressContext] = None,
                expertise_tier: Optional[str] = None,
                use_case: Optional[str] = None) -> DetectionResult:
        payload = {
            # Without the detector's own explanation: a small model would just rework that text, jargon and all, instead of writing for this user from the evidence.
            "detector_output": detector_result.model_dump(
                by_alias=True, exclude={"explanation", "reasoning_trace"}),
            "address_context": compact_context(context) if context else None,
        }
        if expertise_tier or use_case:
            payload["audience"] = {
                "expertise_tier": expertise_tier,
                "use_case": use_case,
            }

        try:
            response = self.provider.generate(
                system_prompt=SYSTEM_PROMPT + "\n" +
                audience_rule(expertise_tier, use_case) + "\n",
                messages=[{
                    "role": "user",
                    "content": json.dumps(payload, indent=2)
                }],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_schema=ForensicReply,
            )
            reply = ForensicReply(**_parse_json(response.text))
        except Exception as e:
            logger.warning("Forensic Investigator failed, keeping detector "
                           "explanation: %s", e)
            return detector_result

        if not reply.explanation.strip():
            logger.warning("Forensic Investigator returned an empty "
                           "explanation, keeping detector explanation")
            return detector_result
        return detector_result.model_copy(update={
            "explanation": reply.explanation.strip(),
            "reasoning_trace": (reply.reasoning_trace or "").strip()
            or detector_result.reasoning_trace,
        })

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
            f"Forensic Investigator did not return valid JSON. Raw output:\n{text}"
        ) from e