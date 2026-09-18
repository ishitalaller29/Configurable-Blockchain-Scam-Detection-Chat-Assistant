from dataclasses import dataclass
from typing import Dict, List, Optional

from agents.business_analyser import BusinessAnalyser
from agents.scam_checker import ScamChecker
from fake_data import build_fake_address_context
from llm_providers.base import LLMProvider
from schema import AddressContext, BusinessAnalyserOutput, DetectionResult

_LABEL_WORDS = {
    "scam": "Risky",
    "not_scam": "Looks fine",
    "insufficient_evidence": "Inconclusive",
}

_INFO_FIELDS = ("chain", "contract", "tx_history", "tokens", "liquidity")


def summarize_detection(result: DetectionResult) -> str:
    label_word = _LABEL_WORDS[result.label]
    pct = round(result.confidence * 100)
    return f"{label_word} ({result.label}, {pct}% confidence). {result.explanation}"


def format_address_info(context: AddressContext,
                        requested_fields: List[str]) -> str:
    fields = [f for f in requested_fields if f in _INFO_FIELDS
              ] or list(_INFO_FIELDS)
    parts = []
    for field in fields:
        if field == "chain":
            parts.append(f"Chain: {context.chain}.")
        elif field == "contract":
            c = context.contract
            if c is None or not c.is_contract:
                parts.append("This address is not a contract.")
            else:
                verified = "verified" if c.verified_source else "unverified"
                parts.append(
                    f"Contract: {verified} source, created by {c.creator or 'unknown'} "
                    f"in tx {c.creation_tx or 'unknown'}.")
        elif field == "tx_history":
            if not context.tx_history:
                parts.append("No transaction history found.")
            else:
                latest = context.tx_history[-1]
                parts.append(
                    f"Transaction history: {len(context.tx_history)} recorded tx(s), "
                    f"most recent {latest.method or 'transfer'} of {latest.value} "
                    f"from {latest.from_} to {latest.to}.")
        elif field == "tokens":
            if not context.tokens:
                parts.append("No token balances found.")
            else:
                token_list = ", ".join(f"{t.balance} {t.symbol}"
                                       for t in context.tokens)
                parts.append(f"Token balances: {token_list}.")
        elif field == "liquidity":
            if not context.liquidity:
                parts.append("No liquidity pools found.")
            else:
                pool_bits = []
                for pool in context.liquidity:
                    pair = "/".join(pool.token_pair)
                    had_remove = any(e.type == "remove"
                                     for e in pool.liquidity_events)
                    pool_bits.append(
                        f"{pair} on {pool.dex} (${pool.liquidity_usd:,.0f} liquidity"
                        f"{', with a remove event' if had_remove else ''})")
                parts.append("Liquidity: " + "; ".join(pool_bits) + ".")
    return " ".join(parts)


@dataclass
class TurnResult:
    reply: str
    ba_output: BusinessAnalyserOutput
    detection_result: Optional[DetectionResult] = None


class ChatSession:

    def __init__(self,
                 provider: LLMProvider,
                 temperature: float = 0.3,
                 max_tokens: int = 800,
                 max_history_messages: int = 500,
                 send_window_messages: int = 20):
        self.ba = BusinessAnalyser(provider, temperature, max_tokens)
        self.sc = ScamChecker(provider, temperature, max_tokens)
        self.history: List[Dict[str, str]] = []
        # In-memory only - the last N messages (user + assistant turns combined), not persisted anywhere.
        self.max_history_messages = max_history_messages
        # Only the most recent send_window_messages are actually sent to the LLM
        # per call - local models have a small context window
        self.send_window_messages = send_window_messages

    def _remember(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_history_messages:
            self.history = self.history[-self.max_history_messages:]

    def _send_window(self) -> List[Dict[str, str]]:
        window = self.history[-self.send_window_messages:]
        if window and window[0]["role"] == "assistant":
            window = window[1:]
        return window

    def handle_message(self, user_text: str) -> TurnResult:
        self._remember("user", user_text)
        ba_output = self.ba.analyse(self._send_window())

        detection_result = None

        if not ba_output.in_scope:
            reply = ba_output.direct_response or "That's outside what I can help with."
        elif ba_output.request_type == "address_info":
            if ba_output.raw_input is None or ba_output.raw_input.type == "unknown":
                reply = "I couldn't pin down which address, token, or transaction you mean - could you share the exact one?"
            else:
                context = build_fake_address_context(ba_output.raw_input.value,
                                                     chain=ba_output.chain
                                                     or "ethereum")
                reply = format_address_info(context,
                                            ba_output.requested_fields)
        elif ba_output.request_type != "scam_check":
            reply = ba_output.direct_response or "I can't help with that yet."
        elif ba_output.raw_input is None or ba_output.raw_input.type == "unknown":
            reply = "I couldn't pin down a concrete address, token, or transaction - could you share the exact one you mean?"
        else:
            context = build_fake_address_context(ba_output.raw_input.value,
                                                 chain=ba_output.chain
                                                 or "ethereum")
            detection_result = self.sc.check(context)
            reply = summarize_detection(detection_result)

        remembered = reply
        if detection_result is not None and detection_result.evidence:
            evidence_lines = "\n".join(
                f"- {e.description} (weight {e.weight:.2f})"
                for e in detection_result.evidence)
            remembered = f"{reply}\n\nEvidence behind this verdict:\n{evidence_lines}"
        self._remember("assistant", remembered)
        return TurnResult(reply=reply,
                          ba_output=ba_output,
                          detection_result=detection_result)
