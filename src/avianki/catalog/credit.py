"""Renders the answer-side credit HTML for one asset (ADR 0012).

The output is stored in the published catalog and injected into cards as HTML, so it is
pipeline-rendered from the raw `AssetRecord` fields, never copied from a source's markup.
Every value is escaped, and the only tags are ``<a href>``, ``<b>`` and ``<i>``.
`credit_is_safe` is the matching check the validation gate runs over what was stored.

An incomplete record never renders: a credit that lacks a field the licence requires is
worse than no asset (ADR 0012), so `render_credit` raises instead.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from avianki.core.licences import AssetRecord, is_allowed, title_required

_KIND_LABELS = {"photo": "Photo", "audio": "Recording"}

_LICENCE_ID = re.compile(r"^(?P<family>CC0|PDM|CC-BY|CC-BY-SA)-(?P<version>\d\.\d)$")

ALLOWED_TAGS: frozenset[str] = frozenset({"a", "b", "i"})
_ENTITY_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,31}$")
_CHARREF = re.compile(r"^(?:[0-9]{1,7}|[xX][0-9a-fA-F]{1,6})$")


def licence_label(licence_id: str) -> str:
    """The human label for an allowed licence id: ``CC-BY-SA-3.0`` -> ``CC BY-SA 3.0``."""
    m = _LICENCE_ID.match(licence_id) if is_allowed(licence_id) else None
    if m is None:
        raise ValueError(f"not an allowed licence id: {licence_id!r}")
    family, version = m["family"], m["version"]
    if family == "PDM":
        return f"Public Domain Mark {version}"
    if family == "CC0":
        return f"CC0 {version}"
    # "CC-BY" -> "CC BY", "CC-BY-SA" -> "CC BY-SA"
    return f"CC {family[3:]} {version}"


def is_http_url(url: str) -> bool:
    """True for an absolute http(s) URL with a host and no whitespace or control characters."""
    if not url or any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _require_url(name: str, url: str | None) -> str:
    if url is None or not is_http_url(url):
        raise ValueError(f"credit field {name} must be an http(s) URL, got {url!r}")
    return url


def _link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def render_credit(kind: str, record: AssetRecord) -> str:
    """One escaped credit line for an asset, using only ``<a>``, ``<b>`` and ``<i>``.

    ``Photo: <i>Title</i> by <b>Creator</b> · <a>CC BY-SA 3.0</a> · <a>source</a> · resized``

    ``kind`` is ``"photo"`` or ``"audio"`` (audio reads ``Recording:``). The title is
    included whenever the licence requires it (`title_required`) and whenever it is
    present; without one the line reads ``Photo by <b>Creator</b>``. Modifications
    follow a final "·" as lower-case words joined by ", "; none means nothing is added.

    Raises ValueError for an unknown kind, an incomplete record (naming the missing
    fields), a licence outside the allowlist, or a non-http(s) URL.
    """
    label = _KIND_LABELS.get(kind)
    if label is None:
        raise ValueError(f"unknown asset kind {kind!r}; expected one of {sorted(_KIND_LABELS)}")
    missing = record.missing_required_fields()
    if missing:
        raise ValueError(f"cannot render credit, missing required fields: {', '.join(missing)}")

    licence_url = _require_url("licence_url", record.licence_url)
    source_url = _require_url("source_url", record.source_url)
    creator = html.escape((record.creator or "").strip())

    title = (record.title or "").strip()
    if title:
        head = f"{label}: <i>{html.escape(title)}</i> by <b>{creator}</b>"
    else:
        # Reaching here means title_required is False: missing_required_fields checked it.
        assert not title_required(record)
        head = f"{label} by <b>{creator}</b>"

    parts = [
        head,
        _link(licence_url, licence_label(record.licence_id)),
        _link(source_url, "source"),
    ]
    mods = [m.strip().lower() for m in record.modifications if m.strip()]
    if mods:
        parts.append(html.escape(", ".join(mods)))
    return " · ".join(parts)


class _Checker(HTMLParser):
    """Flags anything outside the allowed tag/attribute set, balanced tags included."""

    def __init__(self) -> None:
        # convert_charrefs=False keeps text raw, so a literal "<" in text is detectable
        # and an entity such as &lt; is handled (and allowed) separately.
        super().__init__(convert_charrefs=False)
        self.ok = True
        self._stack: list[str] = []

    def _bad(self) -> None:
        self.ok = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            return self._bad()
        if tag == "a":
            if len(attrs) != 1 or attrs[0][0] != "href" or not is_http_url(attrs[0][1] or ""):
                return self._bad()
        elif attrs:
            return self._bad()
        if self._stack:
            return self._bad()  # a credit is flat: no nesting of allowed tags
        self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._bad()  # <b/> and friends are not something the renderer emits

    def handle_endtag(self, tag: str) -> None:
        if not self._stack or self._stack.pop() != tag:
            self._bad()

    def handle_data(self, data: str) -> None:
        if "<" in data or ">" in data or "&" in data:
            self._bad()

    def handle_entityref(self, name: str) -> None:
        if not _ENTITY_NAME.match(name):
            self._bad()

    def handle_charref(self, name: str) -> None:
        if not _CHARREF.match(name):
            self._bad()

    def handle_comment(self, data: str) -> None:
        self._bad()

    def handle_decl(self, decl: str) -> None:
        self._bad()

    def handle_pi(self, data: str) -> None:
        self._bad()

    def unknown_decl(self, data: str) -> None:
        self._bad()


def credit_is_safe(markup: str) -> bool:
    """Whether ``markup`` uses only ``<a href="http(s)://...">``, ``<b>`` and ``<i>``.

    Tags must be balanced and not nested, ``<a>`` may carry a single ``href`` attribute,
    and ``<b>``/``<i>`` no attributes at all. Comments, declarations, processing
    instructions, a literal ``<``, ``>`` or ``&`` in text, and unclosed tags are all unsafe.
    Plain text (already escaped) is safe.
    """
    checker = _Checker()
    try:
        checker.feed(markup)
        checker.close()
    except Exception:  # noqa: BLE001 - the parser raising on malformed input means unsafe
        return False
    return checker.ok and not checker._stack
