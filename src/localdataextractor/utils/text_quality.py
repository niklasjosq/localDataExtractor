from __future__ import annotations

import unicodedata

REPLACEMENT_CHAR = "�"


def _is_garbled_codepoint(ch: str) -> bool:
    """Codepoints that indicate a broken or missing Unicode mapping."""
    if ch == REPLACEMENT_CHAR:
        return True
    cp = ord(ch)
    if 0xE000 <= cp <= 0xF8FF:
        return True
    if 0xF0000 <= cp <= 0xFFFFD:
        return True
    if 0x100000 <= cp <= 0x10FFFD:
        return True
    try:
        category = unicodedata.category(ch)
    except ValueError:
        return True
    if category in {"Cn", "Co", "Cs"}:
        return True
    return False


def replacement_ratio(text: str) -> float:
    """Share of characters that point to a broken Unicode mapping."""
    if not text:
        return 0.0
    visible = [c for c in text if not c.isspace()]
    if not visible:
        return 0.0
    bad = sum(1 for c in visible if _is_garbled_codepoint(c))
    return bad / len(visible)


def looks_garbled(text: str, threshold: float = 0.05) -> bool:
    """True when the text appears to come from a broken PDF text layer."""
    return replacement_ratio(text) > threshold
