"""Local PII redaction shield applied before outbound LLM calls and restored locally."""
import re

PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
ID_CARD_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")


def mask_pii(text, *, extra_names=()):
    """Replace phone numbers, emails, ID numbers, and optional candidate names with reversible tokens."""
    raw = str(text or "")
    if not raw:
        return raw, {}
    token_map = {}

    def _replace_pattern(source, pattern, prefix):
        idx = 0

        def _sub(match):
            nonlocal idx
            value = match.group(0)
            for existing_token, existing_val in token_map.items():
                if existing_val == value:
                    return existing_token
            idx += 1
            token = f"[{prefix}_{idx}]"
            token_map[token] = value
            return token

        return pattern.sub(_sub, source)

    masked = _replace_pattern(raw, EMAIL_RE, "EMAIL")
    masked = _replace_pattern(masked, ID_CARD_RE, "ID")
    masked = _replace_pattern(masked, PHONE_RE, "PHONE")

    for i, name in enumerate(extra_names or (), 1):
        clean = str(name or "").strip()
        if len(clean) >= 2 and clean in masked:
            token = f"[CANDIDATE_{i}]"
            token_map[token] = clean
            masked = masked.replace(clean, token)

    return masked, token_map


def unmask_pii(text, token_map):
    """Restore reversible PII tokens returned by the LLM back to local values."""
    restored = str(text or "")
    if not restored or not token_map:
        return restored
    for token, original in token_map.items():
        restored = restored.replace(token, original)
    return restored
