import sys

from config import build_default_provider, LLM_CONFIG
from conversation import ChatSession


def print_turn(turn):
    print(f"Bot: {turn.reply}")
    # print("\n[debug] Business Analyser output")
    # print(turn.ba_output.model_dump_json(indent=2))
    # if turn.detection_result is not None:
    #     print("\n[debug] Scam Checker DetectionResult")
    #     print(turn.detection_result.model_dump_json(indent=2))


def run_one_shot(session: ChatSession, message: str):
    turn = session.handle_message(message)
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

        turn = session.handle_message(user_input)
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
