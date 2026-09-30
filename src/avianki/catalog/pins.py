"""``src/avianki/data/pins.toml``: reviewer overrides and credit-removal requests (ADR 0011).

One table per species id::

    [turdus-migratorius]
    photo = "commons:M12345"            # force this photo
    audio = "inaturalist:S987:654"      # force this recording (skips ranking and BirdNET)
    exclude = ["commons:M777"]          # never use these (a credit-removal request)
    note = "why, in a sentence"         # required

A value is ``"<source>:<token>"``, split on the *first* colon, because iNaturalist tokens
themselves contain one. This module only reads and validates the file; resolving a pin
against its source, and honouring an exclusion, is the pipeline's job (`catalog.build`).

Validation is strict on purpose: an unknown species, source or key, or a table without a
``note``, is an error that names the species and the line, and all problems are reported
together. A typo must never mean a takedown request quietly does nothing.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avianki.sources.contract import AssetKind
from avianki.sources.registry import ORDER
from avianki.taxonomy.species import SpeciesTable

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the project supports 3.10, which has no tomllib
    import tomli as tomllib  # ty: ignore[unresolved-import]

__all__ = ["AssetRef", "Pin", "Pins", "PinsError", "load_pins", "parse_pins", "parse_ref"]

KNOWN_SOURCES: frozenset[str] = frozenset(name for names in ORDER.values() for name in names)
_KEYS = frozenset({"photo", "audio", "exclude", "note"})


class PinsError(ValueError):
    """``pins.toml`` is malformed. The message lists every problem found."""


@dataclass(frozen=True)
class AssetRef:
    """A source-native asset: the source's registered name and its pin token."""

    source: str
    token: str

    def __str__(self) -> str:
        return f"{self.source}:{self.token}"


@dataclass(frozen=True)
class Pin:
    """One species' table. ``species_id`` is canonical (an alias in the file is followed)."""

    species_id: str
    note: str
    photo: AssetRef | None = None
    audio: AssetRef | None = None
    exclude: tuple[AssetRef, ...] = ()

    def forced(self, kind: AssetKind) -> AssetRef | None:
        if kind is AssetKind.PHOTO:
            return self.photo
        if kind is AssetKind.AUDIO:
            return self.audio
        return None

    def excludes(self, source: str, token: str) -> bool:
        return any(ref.source == source and ref.token == token for ref in self.exclude)


@dataclass(frozen=True)
class Pins:
    """Every pin in the file, by canonical species id."""

    by_species: Mapping[str, Pin]

    def get(self, species_id: str) -> Pin | None:
        return self.by_species.get(species_id)

    def __iter__(self) -> Iterator[Pin]:
        return iter(self.by_species.values())

    def __len__(self) -> int:
        return len(self.by_species)

    def __bool__(self) -> bool:
        return bool(self.by_species)

    def for_validation(self) -> dict[str, dict[str, Any]]:
        """The shape `catalog.validate.validate_catalog(pins=...)` reads: species id ->
        ``{"audio": <bare token>, "photo": <bare token>, "exclude": [<bare tokens>]}``."""
        return {
            sid: {
                "photo": pin.photo.token if pin.photo else None,
                "audio": pin.audio.token if pin.audio else None,
                "exclude": [ref.token for ref in pin.exclude],
            }
            for sid, pin in self.by_species.items()
        }


def parse_ref(value: object, sources: Collection[str] = KNOWN_SOURCES) -> AssetRef:
    """``"commons:M123"`` -> `AssetRef`. Raises ValueError saying what is wrong."""
    if not isinstance(value, str):
        raise ValueError(f'expected a string like "commons:M123", got {value!r}')
    source, sep, token = value.partition(":")
    source, token = source.strip(), token.strip()
    if not sep or not token:
        raise ValueError(f'{value!r} is not "<source>:<token>"')
    if source not in sources:
        raise ValueError(f"unknown source {source!r} in {value!r} (known: {', '.join(sorted(sources))})")
    return AssetRef(source, token)


def _header_lines(text: str) -> dict[str, int]:
    """Line number of each ``[table]`` header, to point errors at the file."""
    found: dict[str, int] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        m = re.match(r'^\s*\[\s*"?([^\]"]+?)"?\s*\]\s*(?:#.*)?$', line)
        if m:
            found.setdefault(m.group(1), n)
    return found


def parse_pins(
    text: str,
    species: SpeciesTable,
    *,
    origin: str = "pins.toml",
    sources: Collection[str] = KNOWN_SOURCES,
) -> Pins:
    """Parse and validate the file's text. Raises `PinsError` listing every problem."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PinsError(f"{origin}: not valid TOML: {exc}") from exc

    lines = _header_lines(text)
    problems: list[str] = []
    pins: dict[str, Pin] = {}

    for key, table in data.items():
        where = f"{origin}:{lines[key]}" if key in lines else origin
        label = f"{where}: [{key}]"
        if not isinstance(table, dict):
            problems.append(f"{label}: expected a table of pins, got a top-level value")
            continue
        try:
            row = species.get(key)
        except KeyError:
            problems.append(f"{label}: unknown species id (not in species.csv)")
            continue
        unknown = sorted(set(table) - _KEYS)
        if unknown:
            problems.append(f"{label}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(_KEYS))}")

        note = table.get("note")
        if not isinstance(note, str) or not note.strip():
            problems.append(f"{label}: a non-empty `note` is required (say why)")
            note = ""

        refs: dict[str, AssetRef | None] = {"photo": None, "audio": None}
        for kind in refs:
            if kind in table:
                try:
                    refs[kind] = parse_ref(table[kind], sources)
                except ValueError as exc:
                    problems.append(f"{label}: `{kind}`: {exc}")
        excluded: list[AssetRef] = []
        if "exclude" in table:
            raw = table["exclude"]
            if not isinstance(raw, list):
                problems.append(f"{label}: `exclude` must be a list of strings")
            else:
                for item in raw:
                    try:
                        excluded.append(parse_ref(item, sources))
                    except ValueError as exc:
                        problems.append(f"{label}: `exclude`: {exc}")

        for kind, ref in refs.items():
            if ref is not None and any(e == ref for e in excluded):
                problems.append(f"{label}: `{kind}` pins {ref}, which `exclude` also lists")

        if row.id in pins:
            problems.append(f"{label}: {key!r} is an alias of {row.id!r}, which already has a table")
            continue
        pins[row.id] = Pin(
            species_id=row.id,
            note=note.strip(),
            photo=refs["photo"],
            audio=refs["audio"],
            exclude=tuple(excluded),
        )

    if problems:
        raise PinsError("invalid pins:\n  " + "\n  ".join(problems))
    return Pins(pins)


def load_pins(path: Path, species: SpeciesTable, *, sources: Collection[str] = KNOWN_SOURCES) -> Pins:
    """Read ``path``. A missing file is `PinsError`: pass no pins file rather than a wrong path."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PinsError(f"{path}: pins file not found") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise PinsError(f"{path}: unreadable: {exc}") from exc
    return parse_pins(text, species, origin=str(path), sources=sources)
