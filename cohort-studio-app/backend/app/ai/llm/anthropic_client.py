"""Claude through the anthropic SDK."""

from typing import Any, cast

import anthropic

from app.ai.llm.base import LLMError, Step, ToolCall


class AnthropicClient:
    """Claude, with the key, base URL and model given by the settings.

    With no api_key the SDK looks for credentials itself (ANTHROPIC_API_KEY or
    an `ant auth login` profile). If a safety classifier declines a request,
    the API retries it on a fallback model it picks itself ("fallbacks":
    "default"), so the user gets an answer instead of a refusal where one is
    possible.
    """

    def __init__(
        self,
        model: str,
        effort: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ):
        try:
            self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout)
        except anthropic.AnthropicError as e:
            raise LLMError(f"Could not set up the Claude client: {e}") from None
        self.model = model
        self.effort = effort

    def step(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Step:
        try:
            # The messages and tools are plain dicts in the Messages API shape
            # (see base.py), which the SDK's TypedDicts describe exactly.
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=cast(Any, messages),
                tools=cast(Any, tools),
                output_config=cast(Any, {"effort": self.effort}),
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise LLMError("Claude rejected the credentials. Check LLM_API_KEY.") from None
        except anthropic.RateLimitError:
            raise LLMError("Claude is rate limiting requests. Try again in a minute.") from None
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude returned an error ({e.status_code}): {e.message}") from None
        except anthropic.APIConnectionError:
            raise LLMError(
                "Could not connect to Claude. Check the network and LLM_BASE_URL."
            ) from None
        except anthropic.AnthropicError as e:
            raise LLMError(f"Could not call Claude: {e}") from None
        except TypeError as e:
            # The SDK raises a TypeError, before sending anything, when no
            # credentials are set. Any other TypeError is a bug and goes up.
            if "authentication" not in str(e):
                raise
            raise LLMError(
                "No Claude credentials are set. Set LLM_API_KEY and restart the server."
            ) from None
        texts = []
        calls = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input)))
        return Step(
            text="\n".join(texts),
            tool_calls=calls,
            content=response.content,
            refused=response.stop_reason == "refusal",
        )
