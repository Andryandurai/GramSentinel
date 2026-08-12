"""Optional LLM access, used only for plain-language synthesis.

Three constraints this module exists to enforce:

1. If the LLM is unavailable, misconfigured or slow, every caller falls back to
   a deterministic template. The healthcare workflow never depends on it.
2. Only already-aggregated, non-identifying material is sent. Callers pass
   counts and percentages, never patient records.
3. Nothing here influences the Safety Engine. Narrative produced by this client
   is screened *by* the engine (Rule 6), never the other way round.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("gramsentinel.llm")


class LLMUnavailable(RuntimeError):
    """Raised internally when no usable LLM is configured or the call fails."""


class LLMClient:
    def __init__(
        self,
        api_key: str = "",
        api_url: str = "",
        model: str = "",
        timeout: float = 12.0,
        enabled: bool = False,
    ) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.timeout = timeout
        self.enabled = enabled and bool(api_key)

    @property
    def available(self) -> bool:
        return self.enabled

    def summarise(self, system_prompt: str, user_prompt: str, max_tokens: int = 400) -> str:
        """Return a short narrative, or raise LLMUnavailable.

        Callers must catch LLMUnavailable and use their deterministic fallback.
        """

        if not self.available:
            raise LLMUnavailable("No LLM configured; using deterministic narrative.")

        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailable("requests not installed") from exc

        try:
            response = requests.post(
                self.api_url,
                headers={
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            blocks = payload.get("content", [])
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if not text.strip():
                raise LLMUnavailable("Empty completion")
            return text.strip()
        except LLMUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure degrades gracefully
            logger.warning("LLM call failed, falling back to template: %s", exc)
            raise LLMUnavailable(str(exc)) from exc


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient(
            api_key=getattr(settings, "LLM_API_KEY", ""),
            api_url=getattr(settings, "LLM_API_URL", ""),
            model=getattr(settings, "LLM_MODEL", ""),
            timeout=getattr(settings, "LLM_TIMEOUT_SECONDS", 12.0),
            enabled=getattr(settings, "LLM_ENABLED", False),
        )
    return _client
