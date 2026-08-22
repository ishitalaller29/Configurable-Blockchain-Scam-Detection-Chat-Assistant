from llm_providers.openai_compatible import OpenAICompatibleProvider

LLM_CONFIG = dict(
    base_url="http://localhost:11434/v1",
    api_key="not-needed",
    model="llama3.1",
    temperature=0.3,
    max_tokens=800,
)


def build_default_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"],
        model=LLM_CONFIG["model"],
    )
