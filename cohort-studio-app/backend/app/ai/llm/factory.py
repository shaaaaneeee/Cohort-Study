"""Choose the language model client from the settings.

    LLM_PROVIDER=openai      any OpenAI-compatible API, with LLM_API_KEY, LLM_BASE_URL,
                             LLM_MODEL and LLM_MAX_TOKENS (the government gateway)
    LLM_PROVIDER=anthropic   Claude directly, with LLM_API_KEY, LLM_BASE_URL and LLM_MODEL
    LLM_PROVIDER=demo        the three demonstration scenarios, picked by the question
    LLM_PROVIDER=scripted    canned replies from the JSON file in LLM_SCRIPT
    unset                    openai when LLM_API_KEY is set, demo otherwise

Another provider is one more class with a step() method, and a branch here.
"""

from app.ai.llm.anthropic_client import AnthropicClient
from app.ai.llm.base import LLMClient, LLMError
from app.ai.llm.openai_client import OpenAICompatibleClient
from app.ai.llm.scripted import DemoClient, ScriptedClient
from app.core.config import Settings


def client_from_settings(settings: Settings) -> LLMClient:
    provider = settings.resolved_llm_provider
    if provider == "openai":
        return OpenAICompatibleClient(
            model=settings.llm_model,
            api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
            base_url=settings.llm_base_url,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
    if provider == "anthropic":
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        return AnthropicClient(
            model=settings.llm_model,
            effort=settings.llm_effort,
            api_key=key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
        )
    if provider == "demo":
        return DemoClient()
    if settings.llm_script is None:
        raise LLMError("LLM_PROVIDER=scripted needs LLM_SCRIPT, the path of a script file.")
    return ScriptedClient.from_file(settings.llm_script)
