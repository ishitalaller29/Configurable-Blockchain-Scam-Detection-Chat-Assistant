"""How much blockchain jargon the Scam Checker and Forensic Investigator use.

Both agents write text the user reads, so both get the same wording rule for the
user's extracted expertise tier. Keeping the rule here means the two agents can't
drift apart, and the level of jargon is changed in one place.
"""
from typing import Optional

TIERS = ("beginner", "intermediate", "professional")
DEFAULT_TIER = "beginner"

# What the Business Analyser might not have worked out yet (or ever) is treated as a beginner, because plain language is the safer default.
def normalise_tier(tier: Optional[str]) -> str:
    return tier if tier in TIERS else DEFAULT_TIER


_SCOPE = (
    "This rule only changes how you word the text the user reads. Describe "
    "only findings that are in the data: never add, drop or invent a finding "
    "to fit the jargon level, and never reuse wording from these instructions "
    "as a finding. It never changes the label, risk_type, confidence or "
    "evidence weights, and any required prefix (such as \"User reports: \") "
    "stays exactly as instructed.")

_RULES = {
    "beginner": (
        "Jargon level: BEGINNER. Use the least jargon of any level. Write in "
        "everyday words, as if explaining to a friend with no crypto "
        "background. Never use field names, abbreviations or acronyms. When "
        "one of these terms comes up, use the plain wording instead of the "
        "term:\n"
        "- verified source code: the project's code is public, so anyone can check it\n"
        "- unverified source code or empty ABI: the project's code is hidden, so nobody can check what it does\n"
        "- liquidity pool: the pot of money people trade against\n"
        "- liquidity events: money being added to or taken out of that pot\n"
        "- transaction history: the past activity on the address\n"
        "- approve transactions: permissions people gave the contract to use their tokens\n"
        "- token balances: the tokens it holds\n"
        "- on-chain: recorded publicly\n"
        "- smart contract: the project's program\n"
        "- rug pull: the creators taking the money and leaving\n"
        "Use no more than two technical terms in the whole reply, and explain "
        "each one in the same sentence."),
    "intermediate": (
        "Jargon level: INTERMEDIATE. The user knows common crypto terms, so use "
        "the precise term where the data supports it and do not explain common "
        "ones (wallet, token, transaction, liquidity pool, smart contract, "
        "verified source code). The first time you use a rarer term (for "
        "example ABI, bytecode, counterparties, wash trading), add a short "
        "explanation of a few words in brackets. Do not use raw field names or "
        "JSON keys."),
    "professional": (
        "Jargon level: PROFESSIONAL. Write like an analyst's note to a peer. "
        "Use precise technical terms and never define or explain them. Cite the "
        "exact values from the data (counts, USD amounts, event types, whether "
        "source is verified). Keep the wording compact. Do not use everyday "
        "analogies, reassurance words (such as legitimate, good sign, healthy) "
        "or a closing offer to explain more; this overrides any instruction to "
        "end with an offer."),
}

# The Scam Checker produces the verdict and the evidence list, so it gets a short beginner rule. The long replacement list above is for the Forensic Investigator, which only writes the explanation. A long rule in the verdict call can crowd out the evidence on a small model.
_BEGINNER_COMPACT = (
    "Jargon level: BEGINNER. Use the least jargon of any level. Write in "
    "everyday words, as if explaining to a friend with no crypto background. "
    "Never use field names, abbreviations or acronyms. Use no more than two "
    "technical terms in the whole reply, and explain each in the same "
    "sentence.")

_FORMAL_USE_CASES = ("investigative_legal", "compliance_risk")
_FORMAL_TONE = (
    "The use case is a formal one, so keep the tone factual and neutral, "
    "suitable for a report.")


def audience_rule(tier: Optional[str],
                  use_case: Optional[str] = None,
                  compact: bool = False) -> str:
    # The wording rule for one expertise tier, ready to append to an agent's system prompt. compact=True gives the shorter beginner rule.
    tier = normalise_tier(tier)
    rule = _BEGINNER_COMPACT if compact and tier == "beginner" else _RULES[tier]
    parts = [rule, _SCOPE]
    if use_case in _FORMAL_USE_CASES:
        parts.append(_FORMAL_TONE)
    return "\n".join(parts)
