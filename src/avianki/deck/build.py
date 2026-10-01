"""Selection, note planning and the genanki writer (spec section 6, ADR 0009).

Everything here is deterministic on purpose: the browser (M6) reimplements `select_species`
and the .apkg writer and must produce the same notes. The same inputs give the same note
fields, GUIDs and note order, whatever the order of any dict or set passed in.
"""

from __future__ import annotations

import html
import logging
import shutil
import tempfile
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

import genanki

from avianki.catalog.format import Manifest, MediaRef, RegionFile, SpeciesEntry, SpeciesFile
from avianki.deck.credits import credits_field, deck_description
from avianki.deck.notetypes import CARD_TYPES, FIELDS, MODELS, stable_id

log = logging.getLogger("bird_deck")

DECK_NAME: Final = "AviAnki"  # frozen (ADR 0009)
MEDIA_PREFIX: Final = "avianki_"

TIER_STANDARD: Final = "standard"
TIER_EVERYTHING: Final = "everything"
TIERS: Final = (TIER_STANDARD, TIER_EVERYTHING)
STANDARD_LIMIT: Final = 100


# ---------------------------------------------------------------------------------------
# Identity (frozen, ADR 0009)
# ---------------------------------------------------------------------------------------


def full_deck_name(deck_name: str, subdeck: str | None) -> str:
    """``AviAnki``, or ``AviAnki::<Region name>`` when a subdeck is asked for."""
    return f"{deck_name}::{subdeck}" if subdeck else deck_name


def deck_id(name: str) -> int:
    """``int(md5(name).hexdigest()[:8], 16)``, the prototype's convention."""
    return stable_id(name)


def note_guid(species_id: str, card_type: str) -> str:
    """The frozen note GUID: ``genanki.guid_for("avianki", species_id, card_type)``."""
    return genanki.guid_for("avianki", species_id, card_type)


# ---------------------------------------------------------------------------------------
# Selection (spec section 6, steps 1-3)
# ---------------------------------------------------------------------------------------


def _wanted_card_types(cards: Collection[str]) -> list[str]:
    """``cards`` in the fixed card-type order; unknown names are an error."""
    unknown = set(cards) - set(CARD_TYPES)
    if unknown:
        raise ValueError(f"unknown card types {sorted(unknown)}; expected some of {CARD_TYPES}")
    return [ct for ct in CARD_TYPES if ct in cards]


def _card_media(entry: SpeciesEntry, card_type: str) -> tuple[MediaRef | None, MediaRef | None] | None:
    """``(photo, audio)`` when ``entry`` has the media ``card_type`` needs, else None.

    ``photo`` needs a photo, ``audio`` a recording and ``photo_audio`` both. Both first
    assets are returned either way, because every back shows the photo and plays the
    recording (spec section 6). Only the first photo and first recording are ever used.
    """
    photo = entry.photo[0] if entry.photo else None
    audio = entry.audio[0] if entry.audio else None
    needs_photo = card_type in ("photo", "photo_audio")
    needs_audio = card_type in ("audio", "photo_audio")
    if (needs_photo and photo is None) or (needs_audio and audio is None):
        return None
    return photo, audio


def has_notes(entry: SpeciesEntry, cards: Collection[str]) -> bool:
    """Whether a species would get at least one note for these card types."""
    return any(_card_media(entry, ct) is not None for ct in _wanted_card_types(cards))


def select_species(
    region: RegionFile,
    species: SpeciesFile,
    cards: Collection[str],
    *,
    tier: str,
    month: int | None,
) -> list[str]:
    """Species ids for a region that will each get at least one note, in rank order.

    1. Take the region's ordered list.
    2. With a ``month`` (1-12), keep a species when ``monthly[month-1] >= 0.1 * max(monthly)``.
       A species whose monthly vector is all zeros is never kept. The comparison is done
       in integers (``10 * value >= max``) so a value at exactly 10% of the peak is kept;
       ``0.1 * 30`` in floating point is 3.0000000000000004 and would wrongly drop it.
    3. Keep only species that would get a note for the selected ``cards``: a photo card
       needs a photo, an audio card a recording, ``photo_audio`` both. A species missing
       from the species file has no media and is dropped with a warning.
    4. Take the first 100 for ``standard`` or all for ``everything``.

    The media check comes before the limit so that a Standard deck has 100 birds whenever
    the region has that many with media (amended 2026-09-30; it used to cut at 100 first).
    """
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
    if month is not None and not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12 or None, got {month!r}")
    _wanted_card_types(cards)  # validates

    ids: list[str] = []
    for species_id, monthly in region.species:
        if month is not None:
            peak = max(monthly)
            if peak == 0 or monthly[month - 1] * 10 < peak:
                continue
        if species_id not in species:
            log.warning("species %r is not in the species file; skipped", species_id)
            continue
        if not has_notes(species[species_id], cards):
            continue
        ids.append(species_id)
        if tier == TIER_STANDARD and len(ids) == STANDARD_LIMIT:
            break
    return ids


# ---------------------------------------------------------------------------------------
# Planning notes
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedNote:
    """One note to write: a species, its card type and the media that card type uses."""

    species_id: str
    card_type: str
    photo: MediaRef | None = None
    audio: MediaRef | None = None


def plan_notes(
    species_ids: Collection[str], species: SpeciesFile, cards: Collection[str]
) -> list[PlannedNote]:
    """One note per selected card type whose media exists, in rank then card-type order.

    ``species_ids`` must already be in rank order (a list, as `select_species` returns;
    a set would make the order arbitrary). ``photo`` needs ``photo[0]``, ``audio`` needs
    ``audio[0]`` and ``photo_audio`` needs both; every note then carries both assets
    the species has, for the back. Only the first photo and first audio are
    used, because ``Photo2`` and ``Audio2`` stay empty. A species missing from the species
    file is skipped with a warning, never an error; a repeated id is planned once.
    """
    wanted = _wanted_card_types(cards)  # fixed order, whatever ``cards`` is

    notes: list[PlannedNote] = []
    seen: set[str] = set()
    for species_id in species_ids:
        if species_id in seen:
            continue
        seen.add(species_id)
        if species_id not in species:
            log.warning("species %r is not in the species file; skipped", species_id)
            continue
        entry = species[species_id]
        for card_type in wanted:
            media = _card_media(entry, card_type)
            if media is not None:
                # Every back shows the photo and plays the recording (spec section 6), so a note
                # carries both of the species' assets whichever one its front asks about.
                notes.append(PlannedNote(species_id, card_type, photo=media[0], audio=media[1]))
    return notes


# ---------------------------------------------------------------------------------------
# Writing the .apkg
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeckSummary:
    """What `write_deck` wrote."""

    path: Path
    deck_name: str
    notes_by_type: dict[str, int] = field(default_factory=dict)
    media_count: int = 0

    @property
    def note_count(self) -> int:
        return sum(self.notes_by_type.values())


def package_media_name(catalog_file: str) -> str:
    """``media/1a2b.webp`` -> ``avianki_1a2b.webp``: the name inside the .apkg."""
    return MEDIA_PREFIX + PurePosixPath(catalog_file).name


def _text(value: str) -> str:
    return html.escape(value, quote=False)


def _note_fields(note: PlannedNote, species: SpeciesFile) -> list[str]:
    entry = species[note.species_id]
    values = {
        "SpeciesId": _text(note.species_id),
        "Name": _text(entry.name),
        "SciName": _text(entry.sci),
        "Photo": f'<img src="{package_media_name(note.photo.file)}">' if note.photo else "",
        "Photo2": "",
        "Audio": f"[sound:{package_media_name(note.audio.file)}]" if note.audio else "",
        "Audio2": "",
        "Credits": credits_field(note.photo, note.audio),
        "IocName": _text(entry.ioc_name),
    }
    return [values[name] for name in FIELDS]


def write_deck(
    notes: list[PlannedNote],
    species: SpeciesFile,
    manifest: Manifest,
    *,
    media: Callable[[str], Path],
    out: Path,
    deck_name: str = DECK_NAME,
    subdeck: str | None = None,
    ebird: bool = False,
    timestamp: float | None = None,
) -> DeckSummary:
    """Write ``notes`` (in the order given) as a .apkg at ``out``.

    ``media(catalog_file)`` returns the local path of a catalog media file such as
    ``media/1a2b.webp``. Inside the package each file is named ``avianki_<basename>``, so
    identical media keeps its name across builds. genanki names a package's media by the
    file's basename, so files are staged under those names in a temporary directory first.

    ``timestamp`` (seconds since the epoch) is the note ``mod``/id base and defaults to
    now. Anki updates the fields of an existing GUID only when the incoming note is newer,
    so real builds leave it unset; tests fix it to compare two packages exactly.
    """
    name = full_deck_name(deck_name, subdeck)
    deck = genanki.Deck(deck_id(name), name, description=deck_description(manifest, ebird=ebird))

    by_type = dict.fromkeys(CARD_TYPES, 0)
    staged: dict[str, str] = {}  # package name -> catalog file, in first-use order
    for note in notes:
        deck.add_note(
            genanki.Note(
                model=MODELS[note.card_type],
                fields=_note_fields(note, species),
                guid=note_guid(note.species_id, note.card_type),
            )
        )
        by_type[note.card_type] += 1
        for ref in (note.photo, note.audio):
            if ref is not None:
                staged.setdefault(package_media_name(ref.file), ref.file)

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="avianki_media_") as tmp:
        paths: list[str] = []
        for package_name, catalog_file in staged.items():
            target = Path(tmp) / package_name
            shutil.copyfile(media(catalog_file), target)
            paths.append(str(target))
        genanki.Package(deck, media_files=paths).write_to_file(str(out), timestamp=timestamp)

    summary = DeckSummary(out, name, by_type, len(staged))
    # DEBUG: the CLI's own summary says this, and at INFO it printed twice.
    log.debug("wrote %s: %d notes, %d media files", out, summary.note_count, summary.media_count)
    return summary
