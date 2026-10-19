import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agents.business_analyser import BusinessAnalyser
from agents.forensic_investigator import ForensicInvestigator
from agents.scam_checker import ScamChecker
from config_loader import get_active_detector
from detector.connector import (ERROR_CONFIG, ERROR_REJECTED, DetectorOutcome,
                                run_detector)
from fetchers.context_builder import (FETCHERS, STATUS_FAILED, missing_fields)
from fetchers.etherscan import (ADDRESS_RE, TX_HASH_RE, InvalidInputError,
                                UnsupportedChainError)
from fetchers.fetcher_output import (get_address_context, is_supported,
                                     resolve_address)
from raw_data import build_raw_data, merge_raw_data
from fetchers.tx_hash_resolver_fetcher import TxNotFoundError
from fetchers.tx_history_fetcher import MAX_TXS
from llm_providers.base import LLMProvider
from schema import (AddressContext, BusinessAnalyserOutput, DetectionResult,
                    DetectorConfig, RawInput)

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


def describe_source(source: str, detector_name: Optional[str] = None) -> str:
    words = SOURCE_WORDS.get(source, source)
    if source == SOURCE_DETECTOR and detector_name:
        return f"{words} ({detector_name})"
    return words


def summarize_detection(result: DetectionResult) -> str:
    return result.explanation


_DETECTOR_VERDICT_WORDS = {
    "scam": "flags this as a scam",
    "not_scam": "doesn't flag this as a scam",
    "insufficient_evidence": "couldn't reach a scam or not-scam verdict on this one",
}
_MAX_FINDINGS_NAMED = 3


def _template_explanation(result: DetectionResult, detector_name: str) -> str:
    reply = (f"{detector_name} {_DETECTOR_VERDICT_WORDS[result.label]} "
             f"(confidence {round(result.confidence * 100)}%).")
    if not result.evidence:
        return reply + " It didn't give any supporting evidence for that."
    strongest = sorted(result.evidence, key=lambda e: e.weight, reverse=True)
    findings = "; ".join(
        e.description.rstrip(". ") for e in strongest[:_MAX_FINDINGS_NAMED])
    return reply + f" Its strongest findings: {findings}."


def explain_detector_result(result: DetectionResult, detector_name: str,
                            context: Optional[AddressContext]) -> DetectionResult:
    return result.model_copy(
        update={"explanation": _template_explanation(result, detector_name)})


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

MAX_ADDRESSES_PER_CHECK = 3

# Fixed wording so an insufficient_evidence reply always says so, whatever the LLM's explanation says.
_INSUFFICIENT_INTRO = "I don't have enough evidence to give a complete verdict on this."
_FINAL_INSUFFICIENT_INTRO = (
    "Even with what you've told me, there still isn't enough evidence for a "
    "firm verdict, so insufficient evidence is my final call on this one.")
_QUESTIONS_OUTRO = "That would help me give a more accurate answer."
_PROFILE_FALLBACK_REPLY = "No problem, pick whichever fits best:"

_PROFILE_FALLBACK_PROFILES = {
    "Just checking before I buy or invest": ("beginner", "investment"),
    "Investigating this for work (police, legal, compliance)":
    ("beginner", "investigative_legal"),
    "I'm a developer/researcher looking into this myself":
    ("professional", "investigative_legal"),
    "Not sure yet, just exploring": ("beginner", "investment"),
}
_PROFILE_FALLBACK_OPTIONS = list(_PROFILE_FALLBACK_PROFILES)

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


_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_RUN_ON_RE = re.compile(r"(?<=[0-9a-fA-F])(?=0x)")


def _hex_inputs(text: str) -> List[Dict[str, str]]:
    found = []
    for token in _HEX_RE.findall(_RUN_ON_RE.sub(" ", text)):
        kind = "tx_hash" if TX_HASH_RE.match(token) else "address"
        found.append({"type": kind, "value": token})
    return found


def _with_inputs_from(ba_output: BusinessAnalyserOutput, text: str,
                      answering: bool) -> BusinessAnalyserOutput:
    found = _hex_inputs(text)
    if not found or (answering and len(found) < 2):
        return ba_output
    data = ba_output.model_dump()
    data["raw_inputs"] = found + [
        raw for raw in data["raw_inputs"] if raw["type"] == "token_name"
    ]
    data["raw_input"] = None
    return BusinessAnalyserOutput.model_validate(data)


def _typed_by_shape(
        ba_output: BusinessAnalyserOutput) -> BusinessAnalyserOutput:
    if not ba_output.raw_inputs:
        return ba_output
    data = ba_output.model_dump()
    for raw in data["raw_inputs"]:
        value = raw["value"].strip()
        if TX_HASH_RE.match(value):
            raw["type"] = "tx_hash"
        elif ADDRESS_RE.match(value) and raw["type"] in ("tx_hash", "unknown"):
            raw["type"] = "address"
    data["raw_input"] = None
    return BusinessAnalyserOutput.model_validate(data)


def _multi_check_reply(checks: List["AddressCheck"],
                       skipped: List[RawInput]) -> str:
    parts = [f"I checked {len(checks)} addresses - here's what I found for each:"]
    for i, check in enumerate(checks, 1):
        head = f"{i}. {check.input.value}"
        if check.detection_result is not None:
            head += f" - {LABEL_WORDS[check.detection_result.label]}"
        parts.append(head + "\n" + check.reply)
    if skipped:
        left_out = ", ".join(raw.value for raw in skipped)
        parts.append(
            f"I only check {MAX_ADDRESSES_PER_CHECK} at a time, so I left "
            f"out {left_out} - send {'it' if len(skipped) == 1 else 'those'} "
            "in another message and I'll take a look.")
    return "\n\n".join(parts)


def _evidence_notes(result: DetectionResult) -> List[str]:
    sections = []
    if result.evidence:
        sections.append("Evidence behind this verdict:\n" + "\n".join(
            f"- {e.description} (weight {e.weight:.2f})"
            for e in result.evidence))
    if result.reasoning_trace:
        sections.append("How I reached it:\n" + result.reasoning_trace)
    return sections


def _detector_failed_reply(outcome: DetectorOutcome) -> str:
    reply = f"No verdict this time - {outcome.error}"
    if outcome.error_kind in (ERROR_CONFIG, ERROR_REJECTED):
        return reply + (" That's a problem with how the detector is set up, "
                        "not a sign either way about this address.")
    return reply + (" So I can't say either way yet - want to try again in "
                    "a minute?")


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
class AddressCheck:
    input: RawInput
    reply: str = ""
    address: Optional[str] = None
    detection_result: Optional[DetectionResult] = None
    detection_source: Optional[str] = None
    detector_name: Optional[str] = None
    missing_fields: List[str] = field(default_factory=list)
    clarifying_questions: List[str] = field(default_factory=list)
    ask_for: Optional[Tuple[str, str]] = None
    notes_for: Optional[Tuple[str, str]] = None


@dataclass
class TurnResult:
    reply: str
    ba_output: BusinessAnalyserOutput
    detection_result: Optional[DetectionResult] = None
    detection_source: Optional[str] = None
    detector_name: Optional[str] = None
    # Context fields that couldn't be checked this turn
    missing_fields: List[str] = field(default_factory=list)
    # Questions asked this turn because the evidence was insufficient
    clarifying_questions: List[str] = field(default_factory=list)
    # Optional buttons shown beneath the assistant response.
    quick_replies: List[str] = field(default_factory=list)
    # The identifiers (tx hashes, contract/wallet/account addresses) the data sources returned for this turn, for the page to display. See raw_data.py.
    raw_data: Optional[Dict] = None
    address_checks: List[AddressCheck] = field(default_factory=list)
    skipped_inputs: List[str] = field(default_factory=list)


class ChatSession:

    def __init__(self,
                 provider: LLMProvider,
                 temperature: float = 0.3,
                 max_tokens: int = 800,
                 max_history_messages: int = 500,
                 send_window_messages: int = 20,
                 ba_provider: Optional[LLMProvider] = None,
                 sc_provider: Optional[LLMProvider] = None):
        # ba_provider/sc_provider let each agent run on its own configured
        # LLM backend (FR-14). Both default to `provider` so every existing
        # caller that passes just one provider keeps working unchanged.
        self.detector: Optional[DetectorConfig] = None
        detector_id = None
        active = get_active_detector()
        if active is not None:
            detector_id, self.detector = active
        self.ba = BusinessAnalyser(
            ba_provider or provider,
            temperature,
            max_tokens,
            selected_detector=detector_id,
            detector_required_input=(self.detector.required_input_type
                                     if self.detector else None))
        
        self.sc = ScamChecker(sc_provider or provider, temperature, max_tokens)
        # Third agent: rewrites the verdict in plain language for this user.
        # It never changes the label, confidence or evidence.

        self.fi = ForensicInvestigator(provider, temperature, max_tokens)
        self.history: List[Dict[str, str]] = []
        # In-memory only - the last N messages (user + assistant turns combined), not persisted anywhere.
        self.max_history_messages = max_history_messages
        # Only the most recent send_window_messages are actually sent to the LLM per call - local models have a small context window
        self.send_window_messages = send_window_messages
        # Clarification state, keyed by (chain, address). _awaiting_answer holds the address questions were just asked about, for the next turn only.
        self._awaiting_answer: Optional[Tuple[str, str]] = None
        self._rounds_asked: Dict[Tuple[str, str], int] = {}
        self._user_notes: Dict[Tuple[str, str], List[str]] = {}
        # Whether the assistant has already asked the user for their
        # blockchain familiarity and intended use.
        self._awaiting_profile_clarification = False
        self._profile: Optional[Tuple[str, str]] = None
        self._pending_request: Optional[str] = None
        # What this turn fetched, for raw_data on the reply: the address context, and a configured detector's raw reply as (name, JSON).
        self._turn_context: Optional[AddressContext] = None
        self._turn_detector_reply: Optional[Tuple[str, Any]] = None
        self._turn_address: Optional[str] = None

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
            context = get_address_context(ba_output, requested_fields)
            self._turn_context = context
            return context, None
        except Exception as e:
            logger.warning("lookup for %s failed: %s", ba_output.raw_input,
                           type(e).__name__)
            return None, _lookup_error_reply(e, chain)

    def _detector_check(
        self, ba_output: BusinessAnalyserOutput
    ) -> Tuple[str, Optional[DetectionResult], Dict[str, str]]:
        config = self.detector
        chain = ba_output.chain or "ethereum"
        context: Optional[AddressContext] = None
        missing: Dict[str, str] = {}

        if ba_output.required_input_type == "address_with_context":
            context, reply = self._fetch_context(ba_output)
            if context is None:
                return reply, None, missing
            missing = missing_fields(context)
            address = context.address
        else:
            try:
                address = resolve_address(ba_output.raw_input, chain)
                if not ADDRESS_RE.match(address):
                    raise InvalidInputError(
                        f"'{address}' is not a valid address (0x + 40 hex "
                        "characters)")
            except Exception as e:
                logger.warning("lookup for %s failed: %s",
                               ba_output.raw_input, type(e).__name__)
                return _lookup_error_reply(e, chain), None, missing

        self._turn_address = address
        outcome = run_detector(config, address, chain, context)
        if outcome.raw_reply is not None:
            self._turn_detector_reply = (outcome.detector_name,
                                         outcome.raw_reply)
        if not outcome.ok:
            return _detector_failed_reply(outcome), None, missing

        result = DetectionResult(**outcome.core.model_dump(),
                                 explanation=outcome.explanation or "")
        if not config.is_llm_based:
            result = explain_detector_result(result, outcome.detector_name,
                                             context)
            print(">>> EXPLAIN_DETECTOR_RESULT RAN", flush=True)
            result = self.fi.explain(
                result, context,
                expertise_tier=ba_output.expertise_tier,
                use_case=ba_output.use_case)
            print(">>> FORENSIC INVESTIGATOR RAN", flush=True)
        reply = summarize_detection(result)
        if result.label == "insufficient_evidence":
            reply = _INSUFFICIENT_INTRO + " " + reply
        if outcome.notes:
            reply += " " + " ".join(outcome.notes)
        return reply, result, missing

    def _run_turn(self) -> TurnResult:
        user_text = self.history[-1]["content"]

        answering_for = self._awaiting_answer
        self._turn_context = None
        self._turn_detector_reply = None
        self._turn_address = None

        ba_output = self.ba.analyse(self._send_window())

        picked = _PROFILE_FALLBACK_PROFILES.get(user_text.strip())
        if picked is not None:
            self._profile = picked
        elif (not ba_output.needs_clarification and ba_output.expertise_tier
              and ba_output.use_case):
            self._profile = (ba_output.expertise_tier, ba_output.use_case)
        if (self._profile is not None
                and ba_output.request_type in ("scam_check", "address_info")):
            tier, use_case = self._profile
            ba_output = ba_output.model_copy(
                update={
                    "needs_clarification": False,
                    "expertise_tier": ba_output.expertise_tier or tier,
                    "use_case": ba_output.use_case or use_case,
                })

        if ba_output.needs_clarification:
            if self._awaiting_profile_clarification:
                reply = _PROFILE_FALLBACK_REPLY
                quick_replies = list(_PROFILE_FALLBACK_OPTIONS)

                self._awaiting_profile_clarification = False
                self._pending_request = "\n".join(
                    filter(None, [self._pending_request, user_text]))
            else:
                reply = (
                    ba_output.direct_response
                    or "Just so I can explain things the right way, have you used "
                    "crypto much before, and what brings you here today?"
                )
                quick_replies = []
                self._awaiting_profile_clarification = True
                self._pending_request = "\n".join(
                    filter(None, [self._pending_request, user_text]))

            self._remember("assistant", reply)

            return TurnResult(
                reply=reply,
                ba_output=ba_output,
                quick_replies=quick_replies,
            )

        self._awaiting_profile_clarification = False
        if ba_output.request_type == "scam_check":
            ba_output = _with_inputs_from(
                ba_output,
                "\n".join(filter(None, [self._pending_request, user_text])),
                answering=answering_for is not None)
        if ba_output.request_type in ("scam_check", "address_info"):
            ba_output = _typed_by_shape(ba_output)

        detection_result = None
        detection_source = None
        detector_name = None
        missing: List[str] = []
        questions: List[str] = []
        ask_for: Optional[Tuple[str, str]] = None
        notes_for: Optional[Tuple[str, str]] = None
        address_checks: List[AddressCheck] = []
        skipped: List[RawInput] = []
        raw_data: Optional[Dict] = None

        if not ba_output.in_scope:
            reply = ba_output.direct_response or "That's outside what I can help with."
        elif ba_output.request_type == "address_info":
            if not is_supported(ba_output.raw_input):
                reply = _unresolved_input_reply(ba_output.raw_input)
            else:
                context, reply = self._fetch_context(
                    ba_output, ba_output.requested_fields)
                if context is not None:
                    missing = list(missing_fields(context))
                    reply = format_address_info(context,
                                                ba_output.requested_fields)
        elif ba_output.request_type != "scam_check":
            reply = ba_output.direct_response or "I can't help with that yet."
        elif len(ba_output.raw_inputs) > 1:
            address_checks, raw_data = self._multi_scam_check(
                ba_output, user_text, answering_for)
            skipped = ba_output.raw_inputs[MAX_ADDRESSES_PER_CHECK:]
            reply = _multi_check_reply(address_checks, skipped)
            notes_for = next((c.notes_for for c in address_checks
                              if c.notes_for is not None), None)
        else:
            check = self._scam_check_one(ba_output, user_text, answering_for)
            reply = check.reply
            detection_result = check.detection_result
            detection_source = check.detection_source
            detector_name = check.detector_name
            missing = check.missing_fields
            questions = check.clarifying_questions
            ask_for = check.ask_for
            notes_for = check.notes_for

        self._pending_request = None
        if notes_for is not None:
            self._user_notes[notes_for] = self._user_notes.get(
                notes_for, []) + [user_text]
        if ask_for is not None:
            self._rounds_asked[ask_for] = self._rounds_asked.get(ask_for,
                                                                 0) + 1
        self._awaiting_answer = ask_for

        sections = []
        if detection_result is not None:
            sections = _evidence_notes(detection_result)
        for i, check in enumerate(address_checks, 1):
            if check.detection_result is not None:
                sections += [f"Address {i} ({check.input.value}) - {note}"
                             for note in _evidence_notes(check.detection_result)]
        remembered = reply
        if sections:
            remembered = reply + "\n\n" + "\n\n".join(sections)
        self._remember("assistant", remembered)
        if not address_checks:
            raw_data = build_raw_data(ba_output, self._turn_context,
                                      self._turn_detector_reply,
                                      self._turn_address)
        return TurnResult(reply=reply,
                          ba_output=ba_output,
                          detection_result=detection_result,
                          detection_source=detection_source,
                          detector_name=detector_name,
                          missing_fields=missing,
                          clarifying_questions=questions,
                          raw_data=raw_data,
                          address_checks=address_checks,
                          skipped_inputs=[raw.value for raw in skipped])

    def _scam_check_one(self,
                        ba_output: BusinessAnalyserOutput,
                        user_text: str,
                        answering_for: Optional[Tuple[str, str]],
                        allow_questions: bool = True) -> AddressCheck:
        check = AddressCheck(input=ba_output.raw_input)
        if not is_supported(ba_output.raw_input):
            check.reply = _unresolved_input_reply(ba_output.raw_input)
            return check

        if ba_output.detector_configured:
            reply, result, missing = self._detector_check(ba_output)
            check.reply = reply
            check.address = self._turn_address
            check.missing_fields = list(missing)
            if result is not None:
                check.detection_result = result
                check.detection_source = SOURCE_DETECTOR
                check.detector_name = self.detector.name
            return check

        context, reply = self._fetch_context(ba_output)
        check.reply = reply
        if context is None:
            return check
        check.address = context.address
        missing = missing_fields(context)
        check.missing_fields = list(missing)
        key = (context.chain.lower(), context.address.lower())
        notes = self._user_notes.get(key, [])
        if answering_for == key:
            notes = notes + [user_text]
            check.notes_for = key

        can_ask = (allow_questions and self._rounds_asked.get(key, 0)
                   < MAX_CLARIFICATION_ROUNDS)
        questions: List[str] = []
        if len(missing) >= len(FETCHERS):
            check.reply = _no_data_reply(context)
            questions = _fallback_questions(context)
        else:
            result, questions = self.sc.check(context, notes)
            print(">>> SCAM CHECKER RAN", flush=True)
            check.detection_result = result
            check.detection_source = SOURCE_SCAM_CHECKER
            check.reply = summarize_detection(result)
            if result.label == "insufficient_evidence":
                questions = questions or _fallback_questions(context)
                last_round = self._rounds_asked.get(
                    key, 0) >= MAX_CLARIFICATION_ROUNDS
                intro = (_FINAL_INSUFFICIENT_INTRO
                         if last_round and notes else _INSUFFICIENT_INTRO)
                check.reply = intro + " " + check.reply

        if questions and can_ask:
            check.ask_for = key
            check.clarifying_questions = questions
            check.reply = _with_questions(check.reply, questions)
        return check

    def _multi_scam_check(
        self, ba_output: BusinessAnalyserOutput, user_text: str,
        answering_for: Optional[Tuple[str, str]]
    ) -> Tuple[List[AddressCheck], Optional[Dict]]:
        checks: List[AddressCheck] = []
        raw_parts = []
        for raw_input in ba_output.raw_inputs[:MAX_ADDRESSES_PER_CHECK]:
            single = ba_output.model_copy(update={
                "raw_input": raw_input,
                "raw_inputs": [raw_input]
            })
            self._turn_context = None
            self._turn_detector_reply = None
            self._turn_address = None
            try:
                check = self._scam_check_one(single,
                                             user_text,
                                             answering_for,
                                             allow_questions=False)
            except Exception as e:
                logger.warning("scam check on %s failed: %s", raw_input,
                               type(e).__name__)
                check = AddressCheck(
                    input=raw_input,
                    reply="I couldn't finish checking this one just now - "
                    "ask me about it again in a minute.")
            checks.append(check)
            raw_parts.append(
                build_raw_data(single, self._turn_context,
                               self._turn_detector_reply, self._turn_address))
        return checks, merge_raw_data(raw_parts)
