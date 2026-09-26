"""LLM selection for the audit crew.

Groq is the default provider because that is the key this project is set up
with. The model is a LiteLLM string, so pointing MODEL at another provider
(openai/gpt-4o, anthropic/claude-sonnet-4-5, ...) and supplying that
provider's key is all it takes to switch.
"""

import logging
import os
import re
import time

from crewai import LLM

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "groq/openai/gpt-oss-120b"


class _DropProxyImportNoise(logging.Filter):
    """Hide LiteLLM's optional-proxy import error, which is harmless here.

    LiteLLM logs a full traceback about missing `fastapi` every time it builds
    a logging object, because its proxy extra isn't installed. Nothing in this
    project uses the proxy, and the completion still succeeds, but the noise
    buries the crew's actual output. This drops only that message — every
    other LiteLLM error still comes through.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not ("fastapi" in message and "proxy" in message.lower())


logging.getLogger("LiteLLM").addFilter(_DropProxyImportNoise())

# Groq's free tier caps tokens per minute, and tells you how long to wait.
RETRY_HINT = re.compile(r"try again in ([0-9.]+)\s*s", re.IGNORECASE)
FALLBACK_WAIT_SECONDS = 25.0
MAX_WAIT_SECONDS = 90.0


class RateLimitAwareLLM(LLM):
    """An LLM that waits out a token-per-minute limit instead of failing.

    LiteLLM's own `num_retries` retries almost immediately, which is useless
    against a rolling per-minute token budget — the retries just burn through
    while the window is still full. This reads the wait the provider asks for
    and actually sleeps it.
    """

    # Generous by default: on Groq's free tier a burst of large prompts can
    # keep the token window full for several minutes, and waiting is strictly
    # better than losing a completed run's work.
    max_rate_limit_retries: int = 10

    def call(self, *args, **kwargs):
        for attempt in range(1, self.max_rate_limit_retries + 1):
            try:
                return super().call(*args, **kwargs)
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt == self.max_rate_limit_retries:
                    raise
                wait = _advised_wait(str(exc))
                logger.warning(
                    "Rate limited by the provider; waiting %.1fs before retry %d/%d.",
                    wait,
                    attempt + 1,
                    self.max_rate_limit_retries,
                )
                print(f"  [rate limited — waiting {wait:.0f}s before retrying]")
                time.sleep(wait)

        raise RuntimeError("unreachable: retry loop exited without returning")


def _is_rate_limit(exc: Exception) -> bool:
    """Identify a rate-limit error without importing litellm's exception tree."""
    if type(exc).__name__ == "RateLimitError":
        return True
    return "rate limit" in str(exc).lower() or "rate_limit_exceeded" in str(exc)


def _advised_wait(message: str) -> float:
    """Use the provider's own 'try again in Xs', plus a margin for clock skew."""
    match = RETRY_HINT.search(message)
    wait = float(match.group(1)) + 3.0 if match else FALLBACK_WAIT_SECONDS
    return min(wait, MAX_WAIT_SECONDS)


def get_llm() -> LLM:
    """Build the LLM every agent in the crew shares."""
    model = os.environ.get("MODEL", "").strip() or DEFAULT_MODEL

    if model.startswith("groq/") and not os.environ.get("GROQ_API_KEY"):
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your "
            "Groq key, or set MODEL to a provider you do have a key for."
        )

    # Extraction and auditing want the least creative output available: every
    # figure in the report has to come from the document or the tool.
    return RateLimitAwareLLM(model=model, temperature=0.0)
