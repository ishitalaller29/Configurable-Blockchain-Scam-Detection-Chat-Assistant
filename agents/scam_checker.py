import json
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel

from fetchers.context_builder import missing_fields
from llm_providers.base import LLMProvider
from schema import AddressContext, DetectionResult, Evidence


class ScamCheckerReply(BaseModel):
    label: Literal["scam", "not_scam", "insufficient_evidence"]
    risk_type: Optional[str]
    confidence: float
    evidence: List[Evidence]
    explanation: str
    reasoning_trace: Optional[str] = None


class ClarifyingQuestionsReply(BaseModel):
    questions: List[str]


SYSTEM_PROMPT = """You are the Scam Checker for a blockchain scam-detection chat assistant.

You are given a JSON "AddressContext" object (contract info, transaction history, token balances, liquidity/pool data) for one address. Reason over this evidence only, do not invent facts that are not present in the context. If the context is too sparse to judge, say so honestly with label "insufficient_evidence" rather than guessing.

Before writing your conclusions, re-read each field you plan to cite and quote its exact literal value from the JSON (e.g. "contract.verified_source is false", not "the contract is verified"). If a boolean field is false or an array is empty, that means the described thing did NOT happen, never phrase it as if it did. The exception is any field listed in unavailable_fields: it could not be checked, so treat it as unknown - never cite it as evidence either way.

The context is a summary: contract.bytecode_size_bytes replaces the raw bytecode, contract.abi lists function names only (empty when the source is unverified), tx_history shows only the latest entries and tokens only the first few - use tx_history_count, tx_history_counterparties and tokens_count for the totals. tx_history_count tops out at 100 because only the newest 100 transactions are fetched, so 100 means "at least 100". Token balances are estimates from transfer history; a long token list is usually unsolicited airdrops, not evidence about this address.

Known red-flag patterns to check for explicitly (each is meaningful evidence on its own, do not require multiple before treating the address as risky):
- Rug pull: a liquidity pool with a "remove" event in liquidity_events, especially one that follows an "add" event within a short time, or where the removed amount is close to the added amount.
- Thin liquidity: liquidity_usd under roughly $5,000 on a pool means the token can be crashed by a small sell, treat this as risky even with no removal yet.
- Hidden logic: contract.verified_source is false and/or contract.abi is empty, no one can audit what the contract actually does.
- Concentration risk: a single token balance that represents an implausibly large share of a small/new token's apparent supply.
- Fresh, thin history: a contract with only one or two tx_history entries and a recent creation_tx has no track record to vouch for it.
None of these alone proves "scam" with certainty, but each one should raise confidence and pull the label away from "not_scam", do not let the mere presence of a creator address or a creation_tx (which every contract has) offset these red flags, since those fields carry no positive signal by themselves.

Known reassuring patterns worth logging as evidence when the label is "not_scam" (these are genuine positive signal, unlike a bare creator/creation_tx):
- contract.verified_source is true (source code can be audited).
- liquidity_usd well above the ~$5,000 thin-liquidity line, with no "remove" events in liquidity_events.
- Multiple tx_history entries over time from varied counterparties, showing a real usage history rather than a single fresh transaction.
- No implausibly large single token balance relative to apparent supply.

Produce:
- label: exactly one of "scam", "not_scam", "insufficient_evidence"
- risk_type: a short category (e.g. "rug_pull", "honeypot", "unverified_contract"), or null if not applicable
- confidence: a number from 0.0 to 1.0 reflecting how strong the evidence is whether that evidence points toward risk or toward legitimacy. Do not default to a high number just because you found one red flag, and do not default to 0 for a clean "not_scam" verdict either, if the reassuring patterns above are present, confidence should be well above 0.
- evidence: a list of {"description": <plain-language finding tied to a specific field in the context>, "weight": <0.0-1.0>}. Populate this for BOTH "scam" and "not_scam" labels - cite the reassuring patterns above when the label is "not_scam", not just red flags when it is "scam". Do not leave this list empty unless the label is "insufficient_evidence".
- explanation: 3-5 sentences total. The first 2-4 sentences give your findings in a natural conversational tone, as if you were telling the user directly what you found - not a dry technical citation dump. Still ground them in the strongest evidence and stay accurate to the literal field values, just phrase it the way a person would explain it out loud rather than restating field names. The final sentence is one short offer that keeps the conversation open rather than landing as a closed verdict, tied to something specific in this address's evidence - e.g. offering to dig into the particular red flag you found, walk through what a reassuring pattern would have looked like here, or check a related address that appears in the context.
- reasoning_trace: your step-by-step reasoning over the evidence, in plain text, 3-6 short sentences. Do not repeat a point you have already made, and do not restate "explanation" - move on once each piece of evidence has been considered once.

Choose "label" last, after you have written your evidence and reasoning_trace, and make sure it is consistent with them: if your evidence and reasoning describe real red flags and point toward risk, the label must be "scam", not "not_scam".

Respond with ONLY a single JSON object, no prose, no markdown code fences, in this exact shape. This is a FORMAT EXAMPLE ONLY, its field values (including "label") are placeholders showing valid types and are not a hint about the correct answer for the address you are given; you must derive every value from the actual context:
{
  "label": "scam",
  "risk_type": "rug_pull",
  "confidence": 0.6,
  "evidence": [{"description": "...", "weight": 0.5}],
  "explanation": "...",
  "reasoning_trace": "..."
}
"""

# Appended only when the address is a plain wallet.
WALLET_RULE = """Wallets vs contracts: when contract.is_contract is false, the address is a plain wallet, not a contract - source verification, ABI and creator do not apply to it, so never cite them as a red flag. A wallet with no (or almost no) transaction history, no tokens and no user-reported context has nothing to judge either way: an empty history is not evidence of a scam, so use "insufficient_evidence" rather than "scam". For the same reason, never list an empty tx_history or empty tokens as an evidence item in either direction - absence of activity is simply no evidence."""

# Appended only when the user has answered clarifying questions.
USER_REPORTED_RULE = """User-reported context: "user_reported_context" (present only when the user has answered your earlier clarifying questions) is the user's own account of how they came across this address - e.g. who sent it, what they were promised, what they were asked to do. It is NOT on-chain evidence and cannot be verified. When it is present you must read it and turn each concrete claim in it into its own evidence item: start each such description with "User reports: " and give it a weight of at most 0.3. Check it against well-known scam patterns: unsolicited DMs, guaranteed or outsized returns, "send X and get more back" giveaway/doubling offers, pressure to act fast, being asked to send funds or approve a token to "unlock", "verify" or "claim" something. If it matches one of these, that is a real warning sign even when the on-chain data is empty - use label "scam" (the confidence stays modest because the evidence is user-reported) and explain the pattern, rather than "insufficient_evidence". Say in the explanation which points came from the user and which from the chain."""

# A separate, small call made only for an insufficient_evidence verdict, so the main verdict prompt stays unchanged.
QUESTIONS_PROMPT = """You help a blockchain scam-detection chat assistant that could not reach a verdict on an address because the evidence was too thin.

You are given the evidence it had (a JSON summary of the address, where unavailable_fields lists checks that could not run, plus user_reported_context if the user has already told us anything) and its explanation of why it couldn't decide.

Write 1-2 short, specific questions to ask the user whose answers would give it more to go on - e.g. where they came across this address, what they were promised, whether they were asked to send funds, connect a wallet or approve a token, or (if the address is a plain wallet rather than a contract) the address of the token or contract they are actually worried about. Ask about what is really missing here; never ask for anything already in the evidence or already answered in user_reported_context. Write them the way a person would ask them in a chat: plain, friendly, one sentence each.

Respond with ONLY a single JSON object, no prose, no markdown code fences:
{"questions": ["...", "..."]}
"""


class ScamChecker:

    def __init__(self,
                 provider: LLMProvider,
                 temperature: float = 0.0,
                 max_tokens: int = 800):
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens

    def check(
        self,
        context: AddressContext,
        user_notes: Optional[List[str]] = None
    ) -> Tuple[DetectionResult, List[str]]:
        # Returns the verdict plus the clarifying questions to ask when it's insufficient_evidence.
        payload = compact_context(context)
        prompt = SYSTEM_PROMPT
        if context.contract is not None and not context.contract.is_contract:
            prompt += "\n" + WALLET_RULE + "\n"
        if user_notes:
            prompt += "\n" + USER_REPORTED_RULE + "\n"
            payload = {"user_reported_context": user_notes, **payload}

        response = self.provider.generate(
            system_prompt=prompt,
            messages=[{
                "role": "user",
                "content": json.dumps(payload, indent=2)
            }],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_schema=ScamCheckerReply,
            frequency_penalty=0.5,
        )
        data = _parse_json(response.text)
        evidence = _cap_user_reported(data.get("evidence", []))
        data["evidence"] = evidence
        data["confidence"] = _confidence_from_evidence(evidence)
        if not _has_onchain_activity(context):
            if not user_notes and data.get("label") != "insufficient_evidence":
                data.update(label="insufficient_evidence",
                            risk_type=None,
                            evidence=[],
                            explanation=EMPTY_ADDRESS_EXPLANATION,
                            reasoning_trace=None)
                evidence = []
                data["confidence"] = 0.0
            # Whatever the verdict rests on, it isn't on-chain, so it can't read as confident.
            data["confidence"] = min(data["confidence"],
                                     MAX_USER_ONLY_CONFIDENCE)
        elif evidence and all(_is_user_reported(e) for e in evidence):
            data["confidence"] = min(data["confidence"],
                                     MAX_USER_ONLY_CONFIDENCE)
        result = DetectionResult(**data)

        questions = []
        if result.label == "insufficient_evidence":
            questions = self._ask_questions(payload, result)
        return result, questions

    def _ask_questions(self, payload: dict,
                       result: DetectionResult) -> List[str]:
        try:
            response = self.provider.generate(
                system_prompt=QUESTIONS_PROMPT,
                messages=[{
                    "role":
                    "user",
                    "content":
                    json.dumps(
                        {
                            "evidence": payload,
                            "why_undecided": result.explanation
                        },
                        indent=2)
                }],
                temperature=self.temperature,
                max_tokens=MAX_QUESTION_TOKENS,
                response_schema=ClarifyingQuestionsReply,
            )
            questions = _parse_json(response.text).get("questions") or []
        except Exception:
            return []
        return [
            q.strip() for q in questions if isinstance(q, str) and q.strip()
        ][:MAX_QUESTIONS]


MAX_TXS_SHOWN = 10
MAX_TOKENS_SHOWN = 10
MAX_ABI_NAMES = 30
MAX_QUESTIONS = 2
MAX_QUESTION_TOKENS = 200
EMPTY_ADDRESS_EXPLANATION = (
    "There's nothing on-chain to go on here - no contract, transactions, "
    "tokens or pools on record - so I can't say either way whether it's a "
    "scam. An empty address isn't a red flag by itself, but it isn't a "
    "reassuring sign either.")

USER_REPORTED_PREFIX = "user reports:"
MAX_USER_REPORTED_WEIGHT = 0.3
MAX_USER_ONLY_CONFIDENCE = 0.5


def _has_onchain_activity(context: AddressContext) -> bool:
    return bool((context.contract is not None and context.contract.is_contract)
                or context.tx_history or context.tokens or context.liquidity)


def _is_user_reported(item: dict) -> bool:
    return str(item.get("description",
                        "")).strip().lower().startswith(USER_REPORTED_PREFIX)


def _cap_user_reported(evidence: list) -> list:
    for item in evidence:
        if _is_user_reported(item):
            item["weight"] = min(item.get("weight", 0.0),
                                 MAX_USER_REPORTED_WEIGHT)
    return evidence


def compact_context(context: AddressContext) -> dict:
    data = context.model_dump(by_alias=True)
    missing = missing_fields(context)
    for field in missing:
        data[field] = None
    data["unavailable_fields"] = list(missing)

    contract = data.get("contract")
    if contract and not contract["is_contract"]:
        data["contract"] = {"is_contract": False}
    elif contract:
        bytecode = contract.pop("bytecode") or ""
        contract["bytecode_size_bytes"] = max(len(bytecode) - 2, 0) // 2
        names = [
            e.get("name") for e in contract["abi"]
            if e.get("type") == "function" and e.get("name")
        ]
        contract["abi"] = names[:MAX_ABI_NAMES]

    if data.get("tx_history") is not None:
        txs = data["tx_history"]
        parties = {t["from"].lower()
                   for t in txs} | {t["to"].lower()
                                    for t in txs}
        data["tx_history_count"] = len(txs)
        data["tx_history_counterparties"] = len(parties -
                                                {context.address.lower(), ""})
        if txs:
            data["tx_history_oldest_fetched"] = txs[0]["timestamp"]
        data["tx_history"] = txs[-MAX_TXS_SHOWN:]

    if data.get("tokens") is not None:
        data["tokens_count"] = len(data["tokens"])
        data["tokens"] = data["tokens"][:MAX_TOKENS_SHOWN]
    return data


def _confidence_from_evidence(evidence: list[dict]) -> float:
    if not evidence:
        return 0.0
    total = sum(item.get("weight", 0.0) for item in evidence)
    return min(1.0, round(total, 2))


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
            f"Scam Checker did not return valid JSON. Raw output:\n{text}"
        ) from e
