import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from agents.business_analyser import BusinessAnalyser
from agents.scam_checker import ScamChecker
from fetchers.context_builder import (FETCHERS, STATUS_FAILED, missing_fields)
from fetchers.etherscan import InvalidInputError, UnsupportedChainError
from fetchers.fetcher_output import get_address_context, is_supported
from fetchers.tx_hash_resolver_fetcher import TxNotFoundError
from fetchers.tx_history_fetcher import MAX_TXS
from llm_providers.base import LLMProvider
from schema import (AddressContext, BusinessAnalyserOutput, DetectionResult,
                    RawInput)

logger = logging.getLogger(__name__)

LABEL_WORDS = {
    "scam": "Scam",
    "not_scam": "Not scam",
    "insufficient_evidence": "Suspicious",
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
_MAX_TOKENS_LISTED = 5


def _invalid_input_reply(error: InvalidInputError) -> str:
    # A typo'd address/hash is the user's to fix, so answer it instead of failing the turn.
    return f"That doesn't look quite right - {error}. Could you double-check it and send it again?"


def _unresolved_input_reply(raw_input: Optional[RawInput]) -> str:
    # ask rather than guess when the input can't be resolved.
    if raw_input is not None and raw_input.type == "token_name":
        return (f"I can't look tokens up by name yet, and plenty of tokens "
                f"share a name like \"{raw_input.value}\", so I'd rather not "
                "guess which one you mean. Could you paste its contract "
                "address?")
    return ("I couldn't pin down a concrete address, token, or transaction - "
            "could you share the exact one you mean?")


def _lookup_error_reply(error: Exception, chain: str) -> str:
    # The lookup failed before any context existed (, so there's nothing partial to fall back on and say what went wrong and what the user can do.
    if isinstance(error, InvalidInputError):
        return _invalid_input_reply(error)
    if isinstance(error, UnsupportedChainError):
        return (f"I can only look things up on Ethereum right now, so I "
                f"can't check it on {_chain_name(chain)}. Is it actually on "
                "Ethereum? If so, let me know and I'll take a look.")
    if isinstance(error, TxNotFoundError):
        return ("I couldn't find that transaction on Ethereum - it may be "
                "mistyped, still pending, or on another chain. Could you "
                "double-check the hash, or paste the address you're worried "
                "about instead?")
    return ("I couldn't reach the blockchain data source to look that up just "
            "now. Could you try again in a minute?")


# Plain-language names for the context fields, used when saying what couldn't be checked.
MISSING_FIELD_WORDS = {
    "contract": "contract details",
    "tx_history": "transaction history",
    "tokens": "token balances",
    "liquidity": "liquidity pool data",
}

# One round of clarifying questions per address, so the bot can't loop on asking.
MAX_CLARIFICATION_ROUNDS = 1

# Fixed wording so an insufficient_evidence reply always says so, whatever the LLM's explanation says.
_INSUFFICIENT_INTRO = "I don't have enough evidence to give a complete verdict on this."
_FINAL_INSUFFICIENT_INTRO = (
    "Even with what you've told me, there still isn't enough evidence for a "
    "firm verdict, so insufficient evidence is my final call on this one.")
_QUESTIONS_OUTRO = "That would help me give a more accurate answer."


def _fallback_questions(context: AddressContext) -> List[str]:
    # Used when the Scam Checker gives none
    questions = [
        "Where did you come across this address - was it sent to you, or "
        "did you find it yourself?",
        "Were you asked to send funds, connect your wallet or approve a "
        "token for it?",
    ]
    if context.contract is not None and not context.contract.is_contract:
        questions[1] = ("It's a plain wallet rather than a contract - if "
                        "you're really worried about a token, could you "
                        "paste the token's contract address?")
    return questions


def _with_questions(reply: str, questions: List[str]) -> str:
    # Asked in plain sentences
    return reply + "\n\n" + " ".join(questions) + " " + _QUESTIONS_OUTRO


def _no_data_reply(context: AddressContext) -> str:
    return (f"I couldn't reach the blockchain data source for any of the "
            f"checks on {context.address} just now, so I've got nothing "
            "on-chain to judge it by, and I'd rather not guess. Try asking "
            "again in a minute.")


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
    movement = (f"a {method} of {latest.value} ETH from {latest.from_} "
                f"to {latest.to}")
    if len(context.tx_history) == 1:
        return f"There's just one transaction on record: {movement}."
    if len(context.tx_history) >= MAX_TXS:
        return (
            f"It's busy - I pulled its {MAX_TXS} most recent transactions; "
            f"the latest is {movement}.")
    return (f"There are {len(context.tx_history)} transactions on record; "
            f"the most recent is {movement}.")


def _say_tokens(context: AddressContext) -> str:
    if not context.tokens:
        return "It isn't holding any token balances."
    held = [f"{t.balance} {t.symbol}" for t in context.tokens]
    # Worked out from transfer history, so said as an estimate.
    if len(held) == 1:
        return f"From its transfer history, it looks to be holding {held[0]}."
    if len(held) > _MAX_TOKENS_LISTED:
        shown = ", ".join(held[:_MAX_TOKENS_LISTED])
        return (
            f"From its transfer history, it looks to be holding {len(held)} different tokens, "
            f"including {shown} (a long list like this is often mostly unsolicited airdrops)."
        )
    return f"From its transfer history, it looks to be holding {', '.join(held[:-1])} and {held[-1]}."


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
    if fields == ["tokens"] and "liquidity" not in missing_fields(context):
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

    # A field whose fetcher failed is said as "couldn't pull", never through its _say_* sentence - that would read its empty default as "there's none".
    missing = missing_fields(context)
    parts = []
    for field in fields:
        if field in missing:
            parts.append(_say_missing(field, missing[field]))
        else:
            parts.append(_FIELD_SENTENCES[field](context))

    shown = [f for f in fields if f not in missing]
    if shown:
        parts.append(_follow_up(context, shown))
    elif STATUS_FAILED in missing.values():
        parts.append("Want me to try again in a minute?")
    else:
        parts.append("Anything else you want me to pull up on it?")
    return " ".join(parts)


def _say_missing(field: str, status: str) -> str:
    words = MISSING_FIELD_WORDS.get(field, field)
    if status == STATUS_FAILED:
        return (f"I couldn't pull its {words} just now - the data source "
                "didn't come through, so I can't say either way.")
    return (f"I can't look up {words} yet - there's no data source hooked "
            "up for that.")


@dataclass
class TurnResult:
    reply: str
    ba_output: BusinessAnalyserOutput
    detection_result: Optional[DetectionResult] = None
    detection_source: Optional[str] = None
    # Context fields that couldn't be checked this turn
    missing_fields: List[str] = field(default_factory=list)
    # Questions asked this turn because the evidence was insufficient
    clarifying_questions: List[str] = field(default_factory=list)


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
        # Clarification state, keyed by (chain, address). _awaiting_answer holds the address questions were just asked about, for the next turn only.
        self._awaiting_answer: Optional[Tuple[str, str]] = None
        self._rounds_asked: Dict[Tuple[str, str], int] = {}
        self._user_notes: Dict[Tuple[str, str], List[str]] = {}

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

    def _fetch_context(
        self,
        ba_output: BusinessAnalyserOutput,
        requested_fields: Optional[List[str]] = None
    ) -> Tuple[Optional[AddressContext], Optional[str]]:
        # Returns (context, None), or (None, reply) when the lookup failed before any context could be built. Per-fetcher failures don't land here. They come back inside the context as missing fields.
        chain = ba_output.chain or "ethereum"
        try:
            return get_address_context(ba_output, requested_fields), None
        except Exception as e:
            logger.warning("lookup for %s failed: %s", ba_output.raw_input,
                           type(e).__name__)
            return None, _lookup_error_reply(e, chain)

    def _run_turn(self) -> TurnResult:
        user_text = self.history[-1]["content"]
        # Only the turn right after questions were asked can be the answer to them.
        answering_for = self._awaiting_answer
        ba_output = self.ba.analyse(self._send_window())

        detection_result = None
        detection_source = None
        missing: Dict[str, str] = {}
        questions: List[str] = []
        ask_for: Optional[Tuple[str, str]] = None
        notes_for: Optional[Tuple[str, str]] = None

        if not ba_output.in_scope:
            reply = ba_output.direct_response or "That's outside what I can help with."
        elif ba_output.request_type == "address_info":
            if not is_supported(ba_output.raw_input):
                reply = _unresolved_input_reply(ba_output.raw_input)
            else:
                context, reply = self._fetch_context(
                    ba_output, ba_output.requested_fields)
                if context is not None:
                    missing = missing_fields(context)
                    reply = format_address_info(context,
                                                ba_output.requested_fields)
        elif ba_output.request_type != "scam_check":
            reply = ba_output.direct_response or "I can't help with that yet."
        elif not is_supported(ba_output.raw_input):
            reply = _unresolved_input_reply(ba_output.raw_input)
        else:
            context, reply = self._fetch_context(ba_output)
            if context is not None:
                missing = missing_fields(context)
                key = (context.chain.lower(), context.address.lower())
                # The user's answer is extra (user-reported) evidence for the address the questions were about. Moving on to a different address is a fresh check, not an answer.
                notes = self._user_notes.get(key, [])
                if answering_for == key:
                    notes = notes + [user_text]
                    notes_for = key

                can_ask = self._rounds_asked.get(key,
                                                 0) < MAX_CLARIFICATION_ROUNDS
                if len(missing) >= len(FETCHERS):
                    # Nothing on-chain came back, so there's nothing for the Scam Checker to ground a verdict in.
                    reply = _no_data_reply(context)
                    questions = _fallback_questions(context)
                else:
                    detection_result, questions = self.sc.check(context, notes)
                    detection_source = SOURCE_SCAM_CHECKER
                    reply = summarize_detection(detection_result)
                    if detection_result.label == "insufficient_evidence":
                        questions = questions or _fallback_questions(context)
                        intro = (_FINAL_INSUFFICIENT_INTRO if not can_ask
                                 and notes else _INSUFFICIENT_INTRO)
                        reply = intro + " " + reply

                if questions and can_ask:
                    ask_for = key
                    reply = _with_questions(reply, questions)
                else:
                    questions = []

        # State only changes once the turn has succeeded, so a failed turn (rolled back in handle_message) leaves it as it was.
        if notes_for is not None:
            self._user_notes[notes_for] = self._user_notes.get(
                notes_for, []) + [user_text]
        if ask_for is not None:
            self._rounds_asked[ask_for] = self._rounds_asked.get(ask_for,
                                                                 0) + 1
        self._awaiting_answer = ask_for

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
                          detection_source=detection_source,
                          missing_fields=list(missing),
                          clarifying_questions=questions)
