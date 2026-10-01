import hashlib
from typing import Any, Dict

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Mock detector")

VERDICTS = [
    (["whitelisted"], 3, True),
    (["no_graph_data"], 10, True),
    (["lp_not_locked", "no_renounce_ownership"], 55, True),
    (["honeypot", "sell_failed", "lp_not_locked"], 88, True),
    (["unrestricted_mint", "previous_scam_tokens", "low_liquidity"], 76, True),
    (["no_dex_pair", "unverified_contract", "insufficient_data"], 9, True),
    (["no_graph_data"], 0, False),
]


def _verdict(address: str) -> Dict[str, Any]:
    if not (address.startswith("0x") and len(address) == 42):
        raise HTTPException(400, {"error": "invalid_address"})
    digest = int(hashlib.sha256(address.lower().encode()).hexdigest(), 16)
    flags, score, analyzed = VERDICTS[digest % len(VERDICTS)]
    return {
        "address": address,
        "score": score,
        "flags": flags,
        "analyzed": analyzed
    }


@app.get("/v1/token/{address}")
def token(address: str):
    return _verdict(address)


@app.post("/detect")
def detect(body: Dict[str, Any]):
    address = str(body.get("address", ""))
    verdict = _verdict(address)
    score = verdict["score"]
    unknown = (not verdict["analyzed"]
               or "insufficient_data" in verdict["flags"])
    label = ("insufficient_evidence" if unknown else "scam" if score >= 70 else
             "not_scam" if score < 40 else "insufficient_evidence")
    return {
        "label":
        label,
        "risk_type":
        "honeypot" if "honeypot" in verdict["flags"] else None,
        "confidence":
        score / 100,
        "evidence": [{
            "description": f"Mock template flag: {flag}",
            "weight": 0.5
        } for flag in verdict["flags"]],
        "explanation":
        f"Mock template verdict: {label} (score {score}).",
    }
