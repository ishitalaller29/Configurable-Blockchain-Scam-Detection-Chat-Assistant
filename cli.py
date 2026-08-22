import sys

from config import build_default_provider, LLM_CONFIG
from agents.business_analyser import BusinessAnalyser
from agents.scam_checker import ScamChecker
from fake_data import build_fake_address_context


def main():
    if len(sys.argv) < 2:
        print('Usage: python cli.py "your message here"')
        sys.exit(1)

    user_message = sys.argv[1]
    provider = build_default_provider()

    ba = BusinessAnalyser(provider,
                          temperature=LLM_CONFIG["temperature"],
                          max_tokens=LLM_CONFIG["max_tokens"])
    ba_output = ba.analyse(user_message)
    print("Business Analyser output")
    print(ba_output.model_dump_json(indent=2))

    if not ba_output.in_scope:
        print("\n(out of scope: pipeline stops here)")
        print(ba_output.direct_response)
        return

    if ba_output.request_type != "scam_check":
        print(f"\n(request_type={ba_output.request_type}: not wired up yet)")
        print(ba_output.direct_response)
        return

    if ba_output.raw_input is None or ba_output.raw_input.type == "unknown":
        print(
            "\n(could not extract a concrete address: real pipeline would ask a clarifying question here)"
        )
        return

    # No detector configured yet so straight to the Scam Checker fallback.
    context = build_fake_address_context(ba_output.raw_input.value,
                                         chain=ba_output.chain or "ethereum")
    print("\nFake AddressContext fed to Scam Checker")

    sc = ScamChecker(provider,
                     temperature=LLM_CONFIG["temperature"],
                     max_tokens=LLM_CONFIG["max_tokens"])
    result = sc.check(context)
    print("\nScam Checker DetectionResult")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
