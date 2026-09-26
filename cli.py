import os
import sys

from config import build_default_provider, LLM_CONFIG
from conversation import (ChatSession, LABEL_WORDS, MISSING_FIELD_WORDS,
                          SOURCE_WORDS)

_RESET = "\033[0m"

# Colour only - the wording comes from conversation.LABEL_WORDS so the CLI and the chat box cannot drift apart on what a label is called.
_STATUS_COLOURS = {
    "scam": "\033[31m",
    "not_scam": "\033[32m",
    "insufficient_evidence": "\033[33m",
}


def _use_colour() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(text: str, colour: str) -> str:
    return f"{colour}{text}{_RESET}" if _use_colour() else text


def print_turn(turn):
    print(f"Bot: {turn.reply}")
    # print("\n[debug] Business Analyser output")
    # print(turn.ba_output.model_dump_json(indent=2))
    # if turn.detection_result is not None:
    #     print("\n[debug] Scam Checker DetectionResult")
    #     print(turn.detection_result.model_dump_json(indent=2))

    # Everything below is the structured DetectionResult, which only scam_check turns produce. address_info and general_question replies print as-is.
    detection = turn.detection_result
    if detection is None:
        _print_missing(turn)
        return

    if detection.evidence:
        print("\n  Evidence (strongest first):")
        for item in sorted(detection.evidence,
                           key=lambda e: e.weight,
                           reverse=True):
            print(f"    - {item.description}  [{item.weight:.2f}]")
    else:
        print("\n  Evidence: none itemised for this verdict.")

    word = LABEL_WORDS[detection.label]
    rows = [("Status", _paint(word, _STATUS_COLOURS[detection.label])),
            ("Confidence", f"{round(detection.confidence * 100)}%")]
    # Omitted rather than shown empty when the detector gives no category.
    if detection.risk_type:
        rows.append(("Risk type", detection.risk_type))
    if turn.detection_source:
        rows.append(("Source",
                     SOURCE_WORDS.get(turn.detection_source,
                                      turn.detection_source)))

    print("\n  Detection details:")
    for name, value in rows:
        print(f"    {name:<11} {value}")
    _print_missing(turn)


def _print_missing(turn):
    if turn.missing_fields:
        words = ", ".join(
            MISSING_FIELD_WORDS.get(f, f) for f in turn.missing_fields)
        print(f"\n  Not checked (data unavailable): {words}")


def print_turn_error(error: Exception):
    print(
        _paint(
            "Bot: Something went wrong on that one, so I couldn't answer it.",
            _STATUS_COLOURS["insufficient_evidence"]))
    print(f"     ({type(error).__name__}: {error})")
    print("     If this keeps happening, check that the LLM backend (Ollama) "
          "is running.")


def run_one_shot(session: ChatSession, message: str):
    try:
        turn = session.handle_message(message)
    except Exception as error:
        # Nothing to recover into in one-shot mode, so report and exit non-zero rather than pretending the lookup succeeded.
        print_turn_error(error)
        sys.exit(1)
    print_turn(turn)


def run_interactive(session: ChatSession):
    print("Scam-detection chat assistant. Type 'exit' or 'quit' to leave.\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        try:
            turn = session.handle_message(user_input)
        except KeyboardInterrupt:
            # Ctrl-C mid-answer abandons that turn, not the session.
            print("\n(cancelled)\n")
            continue
        except Exception as error:
            print_turn_error(error)
            print()
            continue

        print_turn(turn)
        print()


def main():
    provider = build_default_provider()
    session = ChatSession(provider,
                          temperature=LLM_CONFIG["temperature"],
                          max_tokens=LLM_CONFIG["max_tokens"])

    if len(sys.argv) >= 2:
        run_one_shot(session, sys.argv[1])
    else:
        run_interactive(session)


if __name__ == "__main__":
    main()
