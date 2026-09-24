from dataclasses import dataclass
from typing import Dict, List, Optional

from agents.business_analyser import BusinessAnalyser
from agents.scam_checker import ScamChecker
from context_builder import build_address_context
from llm_providers.base import LLMProvider
from schema import AddressContext, BusinessAnalyserOutput, DetectionResult

LABEL_WORDS = {
    "scam": "Risky",
    "not_scam": "Looks fine",
    "insufficient_evidence": "Inconclusive",
}

_INFO_FIELDS = ("chain", "contract", "tx_history", "tokens", "liquidity")

# Which component produced a DetectionResult . Only the Scam Checker fallback path is built, so that is the only value produced
SOURCE_SCAM_CHECKER = "scam_checker"
SOURCE_DETECTOR = "detector"

# Shared wording so the CLI and the chat box label the source identically.
SOURCE_WORDS = {
    SOURCE_SCAM_CHECKER: "Scam Checker (no detector configured)",
    SOURCE_DETECTOR: "Configured detector",
}


def summarize_detection(result: DetectionResult) -> str:
    return result.explanation


_CHAIN_NAMES = {
    "ethereum": "Ethereum",
    "bsc": "BNB Chain",
    "polygon": "Polygon",
    "arbitrum": "Arbitrum",
    "optimism": "Optimism",
    "base": "Base",
}

_THIN_LIQUIDITY_USD = 5000


def _chain_name(chain: str) -> str:
    return _CHAIN_NAMES.get(chain.lower(), chain)


def _say_chain(context: AddressContext) -> str:
    return f"It's on {_chain_name(context.chain)}."


def _say_contract(context: AddressContext) -> str:
    c = context.contract
    if c is None or not c.is_contract:
        return "This one's a plain wallet address rather than a contract."
    if c.verified_source:
        line = "The contract's source is verified, so its code can actually be audited."
    else:
        line = ("The contract's source isn't verified, so there's no way to "
                "audit what its code really does.")
    if c.creator and c.creation_tx:
        line += f" It was deployed by {c.creator} in transaction {c.creation_tx}."
    elif c.creator:
        line += f" It was deployed by {c.creator}."
    elif c.creation_tx:
        line += f" It was deployed in transaction {c.creation_tx}."
    return line


def _say_tx_history(context: AddressContext) -> str:
    if not context.tx_history:
        return "There's no transaction history on record for it."
    latest = context.tx_history[-1]
    method = latest.method or "transfer"
    movement = (f"a {method} of {latest.value} from {latest.from_} "
                f"to {latest.to}")
    if len(context.tx_history) == 1:
        return f"There's just one transaction on record: {movement}."
    return (f"There are {len(context.tx_history)} transactions on record; "
            f"the most recent is {movement}.")


def _say_tokens(context: AddressContext) -> str:
    if not context.tokens:
        return "It isn't holding any token balances."
    held = [f"{t.balance} {t.symbol}" for t in context.tokens]
    if len(held) == 1:
        return f"It's holding {held[0]}."
    return f"It's holding {', '.join(held[:-1])} and {held[-1]}."


def _say_liquidity(context: AddressContext) -> str:
    if not context.liquidity:
        return "There aren't any liquidity pools tied to it."
    bits = []
    for pool in context.liquidity:
        pair = "/".join(pool.token_pair)
        bit = (f"{pair} on {pool.dex}, holding about "
               f"${pool.liquidity_usd:,.0f}")
        if any(e.type == "remove" for e in pool.liquidity_events):
            bit += " (liquidity has been pulled from it at least once)"
        bits.append(bit)
    if len(bits) == 1:
        return f"There's one liquidity pool: {bits[0]}."
    return f"There are {len(bits)} liquidity pools: " + "; ".join(bits) + "."


_FIELD_SENTENCES = {
    "chain": _say_chain,
    "contract": _say_contract,
    "tx_history": _say_tx_history,
    "tokens": _say_tokens,
    "liquidity": _say_liquidity,
}


def _follow_up(context: AddressContext, fields: List[str]) -> str:
    pulled = any(e.type == "remove" for p in context.liquidity
                 for e in p.liquidity_events)
    thin = any(p.liquidity_usd < _THIN_LIQUIDITY_USD
               for p in context.liquidity)
    contract = context.contract

    # Strongest hook first: something in what was just shown looks off, so offer to follow that rather than a generic next step.
    if ("contract" in fields and contract is not None and contract.is_contract
            and not contract.verified_source):
        return ("Want me to run a full scam check on it, given there's no "
                "verified source to go on?")
    if "liquidity" in fields and pulled:
        return ("That removal is worth a closer look - want me to check "
                "whether this looks like a rug pull?")
    if "liquidity" in fields and thin:
        return ("That's thin enough that a small sell could move it a lot - "
                "want me to weigh up how risky it looks overall?")
    # Nothing jumped out, so offer whichever field is the natural next one.
    if fields == ["chain"]:
        return "Want me to dig into the contract itself, or check whether it looks risky?"
    if fields == ["tokens"]:
        return "Want me to look at the liquidity behind those tokens?"
    if fields == ["tx_history"]:
        if len(context.tx_history) > 1:
            return ("Happy to dig into any of those transactions, or look at "
                    "the contract - which would help more?")
        return "Want me to look at the contract behind it, or weigh up how risky it looks?"
    return "Anything else you want me to pull up on it?"


def format_address_info(context: AddressContext,
                        requested_fields: List[str]) -> str:
    fields = []
    for field in requested_fields:
        if field in _INFO_FIELDS and field not in fields:
            fields.append(field)
    fields = fields or list(_INFO_FIELDS)

    parts = [_FIELD_SENTENCES[field](context) for field in fields]
    parts.append(_follow_up(context, fields))
    return " ".join(parts)


@dataclass
class TurnResult:
    reply: str
    ba_output: BusinessAnalyserOutput
    detection_result: Optional[DetectionResult] = None
    detection_source: Optional[str] = None


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
        # Only the most recent send_window_messages are actually sent to the LLM per call - local models have a small context window
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
        try:
            return self._run_turn()
        except Exception:
            self.history.pop()
            raise

    def _run_turn(self) -> TurnResult:
        ba_output = self.ba.analyse(self._send_window())

        detection_result = None
        detection_source = None

        if not ba_output.in_scope:
            reply = ba_output.direct_response or "That's outside what I can help with."
        elif ba_output.request_type == "address_info":
            if ba_output.raw_input is None or ba_output.raw_input.type == "unknown":
                reply = "I couldn't pin down which address, token, or transaction you mean - could you share the exact one?"
            else:
                context = build_address_context(ba_output.raw_input.value,
                                                chain=ba_output.chain,
                                                liquidity_source="dexscreener")
                reply = format_address_info(context,
                                            ba_output.requested_fields)
        elif ba_output.request_type != "scam_check":
            reply = ba_output.direct_response or "I can't help with that yet."
        elif ba_output.raw_input is None or ba_output.raw_input.type == "unknown":
            reply = "I couldn't pin down a concrete address, token, or transaction - could you share the exact one you mean?"
        else:
            context = build_address_context(ba_output.raw_input.value,
                                                chain=ba_output.chain,
                                                liquidity_source="dexscreener")
            detection_result = self.sc.check(context)
            detection_source = SOURCE_SCAM_CHECKER
            reply = summarize_detection(detection_result)

        remembered = reply
        if detection_result is not None:
            sections = []
            if detection_result.evidence:
                sections.append("Evidence behind this verdict:\n" + "\n".join(
                    f"- {e.description} (weight {e.weight:.2f})"
                    for e in detection_result.evidence))
            if detection_result.reasoning_trace:
                sections.append("How I reached it:\n" +
                                detection_result.reasoning_trace)
            if sections:
                remembered = reply + "\n\n" + "\n\n".join(sections)
        self._remember("assistant", remembered)
        return TurnResult(reply=reply,
                          ba_output=ba_output,
                          detection_result=detection_result,
                          detection_source=detection_source)
