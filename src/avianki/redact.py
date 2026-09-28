import re

_REDACTED = "<em>[redacted]</em>"


def _pluralize(word: str) -> str:
    low = word.lower()
    if low.endswith("goose"):
        return word[:-5] + "geese"
    if low.endswith(("ch", "sh", "x", "s", "z")):
        return word + "es"
    if low.endswith("y") and len(low) >= 2 and low[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def redact_name(desc: str, com_name: str) -> str:
    """Replace the bird's common name (and all word-parts/plurals) with <em>[redacted]</em>.

    Matching is case-insensitive, so prose that lowercases the name mid-sentence
    ("The king eider is...") is redacted too. Hyphenated words are redacted
    whole and also part by part ("Dark-eyed" -> "dark-eyed", "dark", "eyed").
    """
    words = com_name.split()
    parts = words + [p for w in words if "-" in w for p in w.split("-") if p]

    # dict.fromkeys dedupes while keeping a deterministic order.
    forms = (form.lower() for part in [com_name] + parts for form in (part, _pluralize(part)))
    candidates: list[str] = list(dict.fromkeys(forms))

    # Longest first so the full name wins over its individual words.
    candidates.sort(key=len, reverse=True)
    pattern = r"\b(" + "|".join(re.escape(c) for c in candidates) + r")\b"
    return re.sub(pattern, _REDACTED, desc, flags=re.IGNORECASE)
