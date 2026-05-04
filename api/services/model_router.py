# -*- coding: utf-8 -*-
"""
ModelRouter — provider-agnostic LLM caller with automatic cascade fallback.

Priority order:
  1. OpenAI  (gpt-4o-mini → gpt-4o → gpt-3.5-turbo)
  2. Anthropic (claude-haiku-4-5-20251001)

Raises ModelRouterError only when ALL providers are exhausted.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("model_router")

# OpenAI cascade — tried in this exact order on model-not-found / permission errors
_OPENAI_CHAIN: list[str] = ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"]
_OPENAI_KNOWN: frozenset[str] = frozenset(_OPENAI_CHAIN)

# Anthropic fallback — used only when every OpenAI model fails
_ANTHROPIC_FALLBACK = "claude-haiku-4-5-20251001"

# All selectable model IDs exposed to callers
AVAILABLE_MODELS: dict[str, str] = {
    "gpt-4o-mini":  "GPT-4o Mini — Rápido",
    "gpt-4o":       "GPT-4o — Balanceado",
    "gpt-3.5-turbo": "GPT-3.5 Turbo — Legado",
}


def _is_openai_model(model: str) -> bool:
    return model in _OPENAI_KNOWN or model.startswith(("gpt-", "o1", "o3"))


class ModelRouterError(RuntimeError):
    """Raised when every provider in the cascade has been exhausted."""


class ModelRouter:
    """
    Single entry-point for all LLM calls in the platform.

    Usage:
        router = ModelRouter()
        text = router.chat("gpt-4o-mini", prompt)
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
    ) -> None:
        self._openai_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        self._anthropic_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    # ── Public API ──────────────────────────────────────────────────────────

    def chat(self, model: str, prompt: str, max_tokens: int = 1024) -> str:
        """
        Call LLM with cascade fallback. Returns response text.
        Raises ModelRouterError only if ALL providers fail.
        """
        return self.messages_create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )

    def messages_create(
        self,
        model: str,
        messages: list,
        system: str = "",
        max_tokens: int = 1024,
    ) -> str:
        """
        Multi-turn conversation with cascade fallback.
        messages must follow the Anthropic format: [{"role": "user"|"assistant", "content": str}].
        Raises ModelRouterError only if ALL providers fail.
        """
        errors: list[str] = []

        # 1. OpenAI cascade (convert Anthropic-format messages to OpenAI format)
        result = self._try_openai_messages(model, messages, system, max_tokens, errors)
        if result is not None:
            return result

        # 2. Anthropic fallback
        result = self._try_anthropic_messages(model, messages, system, max_tokens, errors)
        if result is not None:
            return result

        raise ModelRouterError(
            "All providers exhausted. Attempts:\n" + "\n".join(f"  • {e}" for e in errors)
        )

    # ── Provider implementations ────────────────────────────────────────────

    def _try_openai(
        self, model: str, prompt: str, max_tokens: int, errors: list[str]
    ) -> Optional[str]:
        return self._try_openai_messages(model, [{"role": "user", "content": prompt}], "", max_tokens, errors)

    def _try_openai_messages(
        self, model: str, messages: list, system: str, max_tokens: int, errors: list[str]
    ) -> Optional[str]:
        if not self._openai_key:
            errors.append("OpenAI: no OPENAI_API_KEY configured")
            return None

        try:
            from openai import OpenAI, NotFoundError, PermissionDeniedError, AuthenticationError

            client = OpenAI(api_key=self._openai_key)
            # Convert to OpenAI format: prepend system message if present
            oai_msgs: list = []
            if system:
                oai_msgs.append({"role": "system", "content": system})
            oai_msgs.extend(messages)

            # Build try-order: requested model first, then rest of chain (no dupes)
            resolved = model if _is_openai_model(model) else _OPENAI_CHAIN[0]
            order = [resolved] + [m for m in _OPENAI_CHAIN if m != resolved]

            for attempt in order:
                try:
                    logger.info("ModelRouter → OpenAI model=%r", attempt)
                    resp = client.chat.completions.create(
                        model=attempt,
                        max_tokens=max_tokens,
                        messages=oai_msgs,
                    )
                    logger.info("ModelRouter ✓ OpenAI model=%r", attempt)
                    return resp.choices[0].message.content.strip()

                except (NotFoundError, PermissionDeniedError) as exc:
                    logger.warning("ModelRouter ✗ OpenAI model=%r unavailable: %s", attempt, exc)
                    errors.append(f"OpenAI/{attempt}: {exc}")

            return None  # all OpenAI models exhausted

        except AuthenticationError as exc:
            logger.warning("ModelRouter ✗ OpenAI auth: %s", exc)
            errors.append(f"OpenAI/auth: {exc}")
            return None
        except Exception as exc:
            logger.warning("ModelRouter ✗ OpenAI unexpected: %s", exc)
            errors.append(f"OpenAI/error: {exc}")
            return None

    def _try_anthropic(
        self, prompt: str, max_tokens: int, errors: list[str]
    ) -> Optional[str]:
        return self._try_anthropic_messages(
            _ANTHROPIC_FALLBACK,
            [{"role": "user", "content": prompt}],
            "",
            max_tokens,
            errors,
        )

    def _try_anthropic_messages(
        self, model: str, messages: list, system: str, max_tokens: int, errors: list[str]
    ) -> Optional[str]:
        if not self._anthropic_key:
            errors.append("Anthropic: no ANTHROPIC_API_KEY configured")
            return None

        try:
            import anthropic

            target = model if model in AVAILABLE_MODELS or model.startswith("claude-") else _ANTHROPIC_FALLBACK
            logger.info("ModelRouter → Anthropic model=%r", target)
            client = anthropic.Anthropic(api_key=self._anthropic_key or None)
            kwargs: dict = {"model": target, "max_tokens": max_tokens, "messages": messages}
            if system:
                kwargs["system"] = system
            resp = client.messages.create(**kwargs)
            logger.info("ModelRouter ✓ Anthropic model=%r", target)
            return resp.content[0].text.strip()

        except Exception as exc:
            logger.error("ModelRouter ✗ Anthropic model=%r failed: %s", model, exc)
            errors.append(f"Anthropic/{model}: {exc}")
            return None


# Module-level singleton — re-used across the process lifetime
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
