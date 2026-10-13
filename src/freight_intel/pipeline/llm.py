"""The only file that talks to an LLM provider.

Everything else depends on the small `LLM` protocol below, so tests can plug in a
stub and we could swap OpenAI for Bedrock without touching the pipeline.
"""
import threading
import warnings
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ExtractionFailed(Exception):
    """The model refused, or returned nothing we could parse."""


class LLM(Protocol):
    def extract(self, schema: type[T], system: str, user: str) -> T: ...


class OpenAILLM:
    """gpt-4o-mini with structured output: the API itself guarantees the reply
    matches our Pydantic schema, so we never parse free text with regexes."""

    # Assumed list prices in USD per 1M tokens. VERIFY at openai.com/pricing; they change.
    PRICE_IN_PER_M = 0.15
    PRICE_OUT_PER_M = 0.60

    def __init__(self, model: str, api_key: str):
        from openai import OpenAI
        from langsmith.wrappers import wrap_openai

        # LangSmith re-serialises our parsed objects for its trace and Pydantic grumbles about the
        # type. Harmless, but 6 lines of warning per call hides real output.
        warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)

        # wrap_openai makes every API call show up as a child span in LangSmith,
        # including the exact prompt, the reply and the token counts.
        self._client = wrap_openai(OpenAI(api_key=api_key))
        self.model = model
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0
        # the eval runs several documents at once, and `+=` on a shared counter is not atomic
        self._lock = threading.Lock()

    def extract(self, schema: type[T], system: str, user: str) -> T:
        from openai import OpenAIError
        from pydantic import ValidationError

        try:
            completion = self._client.chat.completions.parse(
                model=self.model,
                temperature=0,  # extraction should be repeatable, not creative
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
            )
        except (OpenAIError, ValidationError) as exc:
            # one bad document (rate limit after retries, truncated reply...) must not kill a whole batch
            raise ExtractionFailed(f"{type(exc).__name__}: {exc}") from exc
        with self._lock:
            self.calls += 1
            if completion.usage:
                self.prompt_tokens += completion.usage.prompt_tokens
                self.completion_tokens += completion.usage.completion_tokens
        message = completion.choices[0].message
        if message.refusal:
            raise ExtractionFailed(f"model refused: {message.refusal}")
        if message.parsed is None:
            raise ExtractionFailed("model returned no parsable output")
        return message.parsed

    @property
    def approx_cost_usd(self) -> float:
        return (self.prompt_tokens * self.PRICE_IN_PER_M + self.completion_tokens * self.PRICE_OUT_PER_M) / 1e6
