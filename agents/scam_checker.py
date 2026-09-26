import json
from typing import List, Literal, Optional

from pydantic import BaseModel

from llm_providers.base import LLMProvider
from schema import AddressContext, DetectionResult, Evidence


class ScamCheckerReply(BaseModel):
    label: Literal["scam", "not_scam", "insufficient_evidence"]
    risk_type: Optional[str]
    confidence: float
    evidence: List[Evidence]
    explanation: str
    reasoning_trace: Optional[str] = None


SYSTEM_PROMPT = """You are the Scam Checker for a blockchain scam-detection chat assistant.

You are given a JSON "AddressContext" object (contract info, transaction history, token balances, liquidity/pool data) for one address. Reason over this evidence only, do not invent facts that are not present in the context. If the context is too sparse to judge, say so honestly with label "insufficient_evidence" rather than guessing.

Data availability: fetcher_provenance lists which fields were actually fetched. Any field NOT listed there (for example contract, tx_history or tokens when only "liquidity" appears) was not checked at all - treat it as unknown. Never cite an unchecked field as evidence in either direction, never describe what it contains, and never apply a red-flag or reassuring pattern that depends on it. Mention the unchecked fields once in the reasoning_trace so the user knows what was not verified.

Before writing your conclusions, re-read each field you plan to cite and quote its exact literal value from the JSON (e.g. "contract.verified_source is false", not "the contract is verified"). For a field that WAS fetched (listed in fetcher_provenance), a false boolean or an empty array means the described thing did NOT happen, never phrase it as if it did. For a field that was NOT fetched, an empty or null value means unknown, not "did not happen".

The context is a summary: contract.bytecode_size_bytes replaces the raw bytecode, contract.abi lists function names only (empty when the source is unverified), tx_history shows only the latest entries and tokens only the first few - use tx_history_count, tx_history_counterparties and tokens_count for the totals. tx_history_count tops out at 100 because only the newest 100 transactions are fetched, so 100 means "at least 100". Token balances are estimates from transfer history; a long token list is usually unsolicited airdrops, not evidence about this address.

Known red-flag patterns to check for explicitly (each is meaningful evidence on its own, do not require multiple before treating the address as risky):
- Rug pull: a liquidity pool with a "remove" event in liquidity_events, especially one that follows an "add" event within a short time, or where the removed amount is close to the added amount.
- Thin liquidity: judge this on the LARGEST pool only (the first pool in the liquidity list). If its liquidity_usd is under 5000 (compare the numbers digit by digit - e.g. 24917 is MORE than 5000), the token can be crashed by a small sell, so treat it as risky even with no removal yet. Smaller secondary pools alongside a deep main pool are normal for real tokens and are not a red flag.
- Hidden logic: contract.verified_source is false and/or contract.abi is empty, no one can audit what the contract actually does. Only apply this when contract.is_contract is true - a wallet (is_contract false) has no code, so an unverified source or empty ABI is normal and not a red flag.
- Concentration risk: a single token balance that represents an implausibly large share of a small/new token's apparent supply. Only apply this if the context includes the token's total supply; never estimate supply. Tokens held by a wallet are usually unsolicited airdrops and are not evidence against the wallet.
- Fresh, thin history: a contract with only one or two tx_history entries and a recent creation_tx has no track record to vouch for it.
None of these alone proves "scam" with certainty, but each one should raise confidence and pull the label away from "not_scam", do not let the mere presence of a creator address or a creation_tx (which every contract has) offset these red flags, since those fields carry no positive signal by themselves.

Known reassuring patterns worth logging as evidence when the label is "not_scam", but ONLY when the field involved was fetched and its actual values show the pattern - cite fewer items rather than inventing one (these are genuine positive signal, unlike a bare creator/creation_tx):
- contract.verified_source is true (source code can be audited).
- liquidity_usd well above the ~$5,000 thin-liquidity line, with no "remove" events in liquidity_events.
- Multiple tx_history entries over time from varied counterparties, showing a real usage history rather than a single fresh transaction.
- No implausibly large single token balance relative to apparent supply.
- An empty liquidity_events list is only weak evidence (weight 0.1 at most), because removal events can only be detected after the same pool has been checked more than once.

Produce:
- label: exactly one of "scam", "not_scam", "insufficient_evidence"
- risk_type: a short category (e.g. "rug_pull", "honeypot", "unverified_contract"), or null if not applicable
- confidence: a number from 0.0 to 1.0 reflecting how strong the evidence is whether that evidence points toward risk or toward legitimacy. Do not default to a high number just because you found one red flag, and do not default to 0 for a clean "not_scam" verdict either, if the reassuring patterns above are present, confidence should be well above 0.
- evidence: a list of {"description": <plain-language finding tied to a specific field in the context>, "weight": <0.0-1.0>}. Populate this for BOTH "scam" and "not_scam" labels - cite the reassuring patterns above when the label is "not_scam", not just red flags when it is "scam". Do not leave this list empty unless the label is "insufficient_evidence".
- explanation: 3-5 sentences total. The first 2-4 sentences give your findings in a natural conversational tone, as if you were telling the user directly what you found - not a dry technical citation dump. Still ground them in the strongest evidence and stay accurate to the literal field values, just phrase it the way a person would explain it out loud rather than restating field names. Always state which chain and token address you checked (from the "chain" and "address" fields), so the user can tell if it is not the token they meant. The final sentence is one short offer that keeps the conversation open rather than landing as a closed verdict, tied to something specific in this address's evidence - e.g. offering to dig into the particular red flag you found, walk through what a reassuring pattern would have looked like here, or check a related address that appears in the context.
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


class ScamChecker:

    def __init__(self,
                 provider: LLMProvider,
                 temperature: float = 0.0,
                 max_tokens: int = 800):
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens

    def check(self, context: AddressContext) -> DetectionResult:
        response = self.provider.generate(
            system_prompt=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": json.dumps(compact_context(context), indent=2)
            }],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_schema=ScamCheckerReply,
            frequency_penalty=0.5,
        )
        data = _parse_json(response.text)
        data["confidence"] = _confidence_from_evidence(data.get(
            "evidence", []))
        return DetectionResult(**data)


MAX_TXS_SHOWN = 10
MAX_TOKENS_SHOWN = 10
MAX_ABI_NAMES = 30


def compact_context(context: AddressContext) -> dict:
    data = context.model_dump(by_alias=True)

    contract = data.get("contract")
    if contract:
        bytecode = contract.pop("bytecode") or ""
        contract["bytecode_size_bytes"] = max(len(bytecode) - 2, 0) // 2
        names = [
            e.get("name") for e in contract["abi"]
            if e.get("type") == "function" and e.get("name")
        ]
        # Still empty when unverified, which the prompt treats as a red flag.
        contract["abi"] = names[:MAX_ABI_NAMES]

    if "tx_history" in data:
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

    if "tokens" in data:
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
