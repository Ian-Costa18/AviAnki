import re


def _pluralize(word: str) -> str:
    low = word.lower()
    if low.endswith("mouse"):
        return word[:-5] + "mice"
    if low.endswith("goose"):
        return word[:-5] + "geese"
    if low.endswith(("ch", "sh", "x", "s", "z")):
        return word + "es"
    return word + "s"


def redact_name(desc: str, com_name: str) -> str:
    """Replace the bird's common name (and variants) with 'this/these bird(s)'."""
    parts = com_name.split()
    last = parts[-1]
    plural_full = _pluralize(com_name)
    plural_last = _pluralize(last)
    replacements: dict[str, str] = {
        com_name.lower(): "this bird",
        plural_full.lower(): "these birds",
        last.lower(): "this bird",
        plural_last.lower(): "these birds",
    }
    full_name_keys = {com_name.lower(), plural_full.lower()}
    seen: set[str] = set()
    candidates: list[str] = []
    for c in [com_name, plural_full, last, plural_last]:
        if c.lower() not in seen:
            seen.add(c.lower())
            candidates.append(c)
    candidates.sort(key=len, reverse=True)
    pattern = r"\b(the\s+)?(" + "|".join(re.escape(c) for c in candidates) + r")\b"

    def _replace(m: re.Match[str]) -> str:
        name = m.group(2)
        rep = replacements[name.lower()]
        # Lowercase last-word-only matches are generic usage → "type of this/these bird(s)"
        if name.lower() not in full_name_keys and name[0].islower():
            rep = "type of " + rep
        # Capitalise only at a sentence boundary, not just because the word was capitalised
        before = desc[:m.start()].rstrip()
        is_sentence_start = not before or before[-1] in ".!?"
        return rep[0].upper() + rep[1:] if is_sentence_start else rep

    return re.sub(pattern, _replace, desc, flags=re.IGNORECASE)
