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
    """Replace the bird's common name (and all word-parts/plurals) with <em>[redacted]</em>."""
    parts = com_name.split()

    candidates: list[str] = []
    seen: set[str] = set()
    for part in [com_name] + parts:
        for form in [part, _pluralize(part)]:
            if form.lower() not in seen:
                seen.add(form.lower())
                candidates.append(form)

    candidates.sort(key=len, reverse=True)
    pattern = r"\b(" + "|".join(re.escape(c) for c in candidates) + r")\b"
    return re.sub(pattern, _REDACTED, desc)
