class BackgroundAIConfigurationError(Exception):
    """Permanent background AI configuration failure (credential, model, or deployment settings)."""


PERMANENT_OPENAI_QUOTA_CODES = frozenset(
    {
        "insufficient_quota",
        "credit_balance_exhausted",
        "billing_hard_limit_reached",
    }
)


def is_openai_quota_exhausted(exc: BaseException) -> bool:
    """True for permanent billing/quota exhaustion, not ordinary transient 429."""
    parts: list[str] = [str(getattr(exc, "code", "") or "")]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            parts.extend(
                str(error.get(key) or "") for key in ("code", "type", "message")
            )
        else:
            parts.append(str(error))
    parts.append(str(exc))
    haystack = " ".join(parts).lower()
    return any(code in haystack for code in PERMANENT_OPENAI_QUOTA_CODES)
