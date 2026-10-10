# Detector Connector + mapping file

Lets a scam check go to an external detector instead of the Scam Checker. Built
from *External API Pointer Documentation – Mapping File Integration Requirements & Draft*.


## Mapping file format

The format is shaped around a real detector (RektRadar).

- `label`: `path`, then `overrides` (another field forces the label), `value.map` (word/code → enum), `ranges` (number → enum), `fallback`
- `confidence`: `path` + `scale` (+ optional `default`, used only when the field is missing)
- `risk_type`: `path` only, capped at 64 characters. Left out for RektRadar, which has no category field.
- `evidence`: `mode: list` (array of objects + `item` paths) or `mode: code_list` (array of strings + a `codes` table).
  A code missing from `codes` still shows up, as the raw code at `default_weight`.
- `explanation`: `path` to the detector's own text. Required when `is_llm_based: true`, otherwise unused.

For RektRadar, `label.overrides` turns an `insufficient_data` flag or `analyzed: false` into
*insufficient evidence* - both come with a low score that would otherwise read as *not scam*.


## How a scam check flows

1. `ChatSession` reads the active detector once at start-up. The Business
   Analyser only gets its id and `required_input_type`.
2. `required_input_type: address` → only the input is resolved (a tx hash still goes through Etherscan); no context fetchers run.
   `address_with_context` → the context fetchers run first, and failed ones show up as "Not checked".
3. `run_detector` calls it. **Generic**: raw JSON → `map_response`. **Template**: the reply is already `DetectionResult`-shaped, so it is only validated.
4. `is_llm_based: true` → the detector's own explanation is used as-is.
   `false` → `conversation.explain_detector_result` writes one from the evidence. That is the
   Forensic Investigator's slot; `forensic_investigator.py` is **not plugged in yet**, so
   a fixed-wording stand-in fills it for now. Label, confidence and evidence are never changed.
5. The chat shows the verdict with `Source: Configured detector (<name>)`.

## Trying it

Needs Ollama running llama3.1 with 8192 context (`OLLAMA_CONTEXT_LENGTH=8192 ollama serve`, or the Ollama app's Context length setting).

```bash
uvicorn mock_detector.app:app --port 9000                 # terminal 1

ACTIVE_DETECTOR=rektradar_mock python cli.py "is 0x0000000000000000000000000000000000000003 a scam?"
ACTIVE_DETECTOR=template_mock  python cli.py "is 0xdAC17F958D2ee523a2206206994597C13D831ec7 a scam?"   # fetches context first - needs ETHERSCAN_API_KEY
ACTIVE_DETECTOR=rektradar      python cli.py "is 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 a scam?"   # real API  needs REKTRADAR_API_KEY, or delete its auth block
```

`ACTIVE_DETECTOR` overrides `active_detector` in the config; unset (or `none`) means the
Scam Checker, exactly as before. The web chat picks it up the same way when `uvicorn server:app` is started with it set.
The mock's verdict is fixed per address, so `0x...0001` is always insufficient evidence, `0x...0002` always not scam, `0x...0003` always scam, and so on.

## When the detector fails

Nothing is guessed and the Scam Checker is **not** swapped in - the chat says which detector
failed and why, with no verdict shown.

| What happened | `error_kind` | Mapping runs? |
|---|---|---|
| Malformed address, missing API key, request can't be built | `config` | no |
| Timeout, connection refused, 5xx (after one retry) | `unreachable` | no |
| 4xx (401/403 → "API key missing or wrong", 429 → rate limited) | `rejected` | no |
| Not JSON, over 1 MB, required field (label) missing, confidence present but not a number, template reply not in schema | `unreadable` | stopped with `MappingError` |

