"""The publish gate (ADR 0014): a build is released only if `validate_catalog` says ok.

Pure: it reads the catalog directory (and hashes media) but does no network and reads no
clock. Each check is its own small function returning a `ValidationResult`, and
`validate_catalog` merges them. Every `Problem` carries a stable machine-readable
``code`` (``area.what``) so a workflow, a test or the build report can key on it; the
human wording in ``message`` may change.

Codes
-----
``format.invalid``               a file failed to load or violated its schema
``media.missing|size|hash``      a referenced media file is absent, the wrong size, or its
                                 bytes don't hash to its name
``media.orphan_file`` (warning)  a file in ``media/`` that species.json doesn't reference
``provenance.absent``            the manifest has no provenance file
``provenance.missing_entry``     a referenced media file has no provenance record
``provenance.orphan``            a provenance record for a file species.json doesn't use
``provenance.species_mismatch``  the record names a different species than references it
``provenance.kind_mismatch``     the record's kind disagrees with photo/audio placement
``licence.not_allowed``          ``licence_id`` is off the exact allowlist
``licence.incomplete``           the record lacks a field the licence requires (ADR 0012)
``credit.unsafe``                stored credit HTML uses more than ``<a href>``, ``<b>``, ``<i>``
``credit.stale``                 stored credit lacks the licence label or the creator
``audio.unverified``             audio with ``verified`` unset
``audio.low_confidence``         ``verified == "birdnet"`` without confidence >= 0.5
``audio.scores_missing``         audio chosen under rule 2 or later without presence, competitor and quality
``pins.excluded_present``        an asset whose token a pin excludes is still in the catalog
``pins.unbacked`` (warning)      ``verified == "pinned"`` but no pin names that token
``size.total``                   the site on disk exceeds ``max_site_bytes``
``size.manifest_mismatch`` (w)   ``manifest.total_bytes`` disagrees with the disk
``shrink.region``                a region lost more than 10% of its species
``shrink.assets``                the catalog lost more than 5% of its media assets
``region.unknown_species``       a region lists an id that species.json lacks
``region.duplicate_species``     a region lists one id twice
``species.name_missing`` / ``species.sci_missing``  blank name or scientific name
"""

from __future__ import annotations

import html
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avianki.catalog.credit import credit_is_safe, licence_label
from avianki.media.verify import MIN_CONFIDENCE
from avianki.catalog.format import (
    AUDIO_RULE,
    FormatError,
    LoadedCatalog,
    file_digest16,
    load_catalog,
)
from avianki.core.licences import is_allowed

log = logging.getLogger("bird_deck")

MAX_SITE_BYTES = 900_000_000
BIRDNET_MIN_CONFIDENCE = MIN_CONFIDENCE
REGION_SHRINK_LIMIT_PCT = 10
ASSET_SHRINK_LIMIT_PCT = 5
# manifest.total_bytes should equal what's on disk; allow rounding-level slack only.
TOTAL_BYTES_TOLERANCE_PCT = 1
TOTAL_BYTES_TOLERANCE_MIN = 1024

# species id -> a pin table (mapping with photo/audio/exclude keys, or an object with
# those attributes). Kept structural so this module doesn't depend on catalog.select.
Pins = Mapping[str, Any]


@dataclass(frozen=True)
class Problem:
    """One finding. ``code`` is stable and machine-readable; ``subject`` is the species
    id, region slug or media filename it is about ("" for catalog-wide findings)."""

    code: str
    message: str
    subject: str = ""


@dataclass
class ValidationResult:
    errors: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, message: str, subject: str = "") -> None:
        self.errors.append(Problem(code, message, subject))

    def warn(self, code: str, message: str, subject: str = "") -> None:
        self.warnings.append(Problem(code, message, subject))

    def merge(self, other: ValidationResult) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def downgraded(self) -> ValidationResult:
        """The same findings with every error demoted to a warning."""
        return ValidationResult([], [*self.errors, *self.warnings])


# ---------------------------------------------------------------------------------------
# 1. Schema and file hashes
# ---------------------------------------------------------------------------------------


def check_media_files(catalog: LoadedCatalog) -> ValidationResult:
    """Every referenced media file exists, has its declared size and hashes to its name."""
    res = ValidationResult()
    for name, ref in sorted(catalog.referenced_media().items()):
        path = catalog.media_path(name)
        if not path.is_file():
            res.error("media.missing", "file is missing", name)
            continue
        size = path.stat().st_size
        if size != ref.bytes:
            res.error("media.size", f"{size} bytes on disk, {ref.bytes} in species.json", name)
        elif file_digest16(path) != Path(name).stem:
            res.error("media.hash", "content does not hash to its filename", name)
    return res


# ---------------------------------------------------------------------------------------
# 2. Licences, provenance coverage and credit lines
# ---------------------------------------------------------------------------------------


def check_licences(catalog: LoadedCatalog) -> ValidationResult:
    """Every provenance record is on the exact allowlist and creditable (ADR 0012)."""
    res = ValidationResult()
    if catalog.provenance is None:
        return res  # check_provenance_coverage reports the absence once
    for name, entry in sorted(catalog.provenance.items()):
        rec = entry.record
        if not is_allowed(rec.licence_id):
            res.error("licence.not_allowed", f"licence {rec.licence_id!r} is not allowed", name)
        missing = rec.missing_required_fields()
        if missing:
            res.error(
                "licence.incomplete", f"missing required fields: {', '.join(missing)}", name
            )
    return res


def _references(catalog: LoadedCatalog) -> dict[str, set[tuple[str, str]]]:
    """media file -> {(species_id, kind)} for every place species.json uses it."""
    refs: dict[str, set[tuple[str, str]]] = {}
    for sid, entry in catalog.species.items():
        for kind, media in (("photo", entry.photo), ("audio", entry.audio)):
            for m in media:
                refs.setdefault(m.file, set()).add((sid, kind))
    return refs


def check_provenance_coverage(catalog: LoadedCatalog) -> ValidationResult:
    """species.json and provenance cover the same media files; nothing is left on disk."""
    res = ValidationResult()
    refs = _references(catalog)
    if catalog.provenance is None:
        res.error("provenance.absent", "the manifest names no provenance file")
    else:
        prov = catalog.provenance
        for name in sorted(refs):
            if name not in prov:
                res.error("provenance.missing_entry", "referenced but has no provenance", name)
        for name, entry in sorted(prov.items()):
            used_by = refs.get(name)
            if used_by is None:
                res.error("provenance.orphan", "provenance for a file species.json never uses", name)
                continue
            if entry.species_id not in {sid for sid, _ in used_by}:
                res.error(
                    "provenance.species_mismatch",
                    f"provenance says {entry.species_id!r}, "
                    f"species.json uses it for {sorted(sid for sid, _ in used_by)}",
                    name,
                )
            if entry.kind not in {kind for _, kind in used_by}:
                res.error(
                    "provenance.kind_mismatch",
                    f"provenance says {entry.kind!r}, species.json uses it as "
                    f"{sorted(kind for _, kind in used_by)}",
                    name,
                )
    media_dir = catalog.root / "media"
    if media_dir.is_dir():
        for path in sorted(media_dir.iterdir()):
            name = f"media/{path.name}"
            if path.is_file() and name not in refs:
                res.warn("media.orphan_file", "on disk but not referenced by species.json", name)
    return res


def check_credits(catalog: LoadedCatalog) -> ValidationResult:
    """Each stored credit line is safe HTML and still names the licence and creator."""
    res = ValidationResult()
    if catalog.provenance is None:
        return res
    for sid, entry in sorted(catalog.species.items()):
        for m in (*entry.photo, *entry.audio):
            prov = catalog.provenance.entries.get(m.file)
            if prov is None:
                continue  # reported by check_provenance_coverage
            if not credit_is_safe(m.credit):
                res.error("credit.unsafe", "credit HTML uses more than <a href>, <b>, <i>", m.file)
            rec = prov.record
            missing = []
            if is_allowed(rec.licence_id) and html.escape(licence_label(rec.licence_id)) not in m.credit:
                missing.append(f"licence label {licence_label(rec.licence_id)!r}")
            creator = (rec.creator or "").strip()
            # A blank creator is already a licence.incomplete; "" is trivially "contained".
            if creator and html.escape(creator) not in m.credit:
                missing.append(f"creator {creator!r}")
            if missing:
                res.error("credit.stale", f"credit for {sid} lacks {' and '.join(missing)}", m.file)
    return res


# ---------------------------------------------------------------------------------------
# 3. Audio verification (and pins)
# ---------------------------------------------------------------------------------------


def check_audio_verified(catalog: LoadedCatalog) -> ValidationResult:
    """Audio passed BirdNET at >= 0.5 or is pinned. Photos may be either (ADR 0011)."""
    res = ValidationResult()
    if catalog.provenance is None:
        return res
    for sid, entry in sorted(catalog.species.items()):
        for m in entry.audio:
            prov = catalog.provenance.entries.get(m.file)
            if prov is None:
                continue
            if prov.verified is None:
                res.error("audio.unverified", f"audio for {sid} was neither BirdNET-verified nor pinned", m.file)
            elif prov.verified == "birdnet":
                conf = prov.birdnet_confidence
                if conf is None or conf < BIRDNET_MIN_CONFIDENCE:
                    shown = "no confidence recorded" if conf is None else f"confidence {conf}"
                    res.error(
                        "audio.low_confidence",
                        f"audio for {sid}: {shown}, need >= {BIRDNET_MIN_CONFIDENCE}",
                        m.file,
                    )
                elif prov.audio_rule is not None and prov.audio_rule >= AUDIO_RULE:
                    scores = (prov.presence, prov.competitor, prov.quality)
                    if any(v is None for v in scores):
                        res.error(
                            "audio.scores_missing",
                            f"audio for {sid} was chosen under rule {prov.audio_rule} but lacks "
                            "presence, competitor or quality",
                            m.file,
                        )
    return res


def _pin_value(pin: Any, key: str) -> Any:
    return pin.get(key) if isinstance(pin, Mapping) else getattr(pin, key, None)


def check_pins(catalog: LoadedCatalog, pins: Pins | None) -> ValidationResult:
    """Honour exclusions (credit-removal requests, ADR 0011) and flag unbacked pins.

    An excluded token still in the catalog is an error: the CC licences oblige us to
    honour removal. A ``pinned`` audio asset that no pin names any more never passed
    BirdNET, so it is an error too.
    """
    res = ValidationResult()
    if pins is None or catalog.provenance is None:
        return res
    for name, prov in sorted(catalog.provenance.items()):
        pin = pins.get(prov.species_id)
        if pin is not None and prov.token in set(_pin_value(pin, "exclude") or ()):
            res.error("pins.excluded_present", f"token {prov.token!r} is excluded by a pin", name)
        if prov.kind == "audio" and prov.verified == "pinned":
            pinned = _pin_value(pin, "audio") if pin is not None else None
            if pinned != prov.token:
                res.error("pins.unbacked", f"marked pinned but no pin names token {prov.token!r}", name)
    return res


# ---------------------------------------------------------------------------------------
# 4. Size
# ---------------------------------------------------------------------------------------


def site_bytes(root: Path) -> int:
    """Total size of every file under ``root`` (what would be deployed), from the disk."""
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _declared_total_on_disk(catalog: LoadedCatalog) -> int:
    """What ``manifest.total_bytes`` claims to sum: referenced media + the hashed JSON files."""
    total = 0
    for name in catalog.referenced_media():
        path = catalog.media_path(name)
        if path.is_file():
            total += path.stat().st_size
    m = catalog.manifest
    json_files = [m.species_file, *(r.file for r in m.regions)]
    if m.provenance_file:
        json_files.append(m.provenance_file)
    for name in json_files:
        path = catalog.root / name
        if path.is_file():
            total += path.stat().st_size
    return total


def check_size(catalog: LoadedCatalog, max_site_bytes: int = MAX_SITE_BYTES) -> ValidationResult:
    """The site on disk fits ``max_site_bytes``; the manifest's own total is roughly right."""
    res = ValidationResult()
    total = site_bytes(catalog.root)
    if total > max_site_bytes:
        res.error("size.total", f"site is {total} bytes, limit {max_site_bytes}", "")
    on_disk = _declared_total_on_disk(catalog)
    declared = catalog.manifest.total_bytes
    slack = max(TOTAL_BYTES_TOLERANCE_MIN, on_disk * TOTAL_BYTES_TOLERANCE_PCT // 100)
    if abs(declared - on_disk) > slack:
        res.warn(
            "size.manifest_mismatch",
            f"manifest total_bytes is {declared} but media + JSON on disk is {on_disk}",
            "",
        )
    return res


# ---------------------------------------------------------------------------------------
# 5. Shrink
# ---------------------------------------------------------------------------------------


def _preview(ids: list[str], limit: int = 5) -> str:
    shown = ", ".join(ids[:limit])
    return shown + (f", ... (+{len(ids) - limit})" if len(ids) > limit else "")


def _filled_slots(catalog: LoadedCatalog) -> set[tuple[str, str]]:
    return {
        (sid, role)
        for sid, entry in catalog.species.entries.items()
        for role, refs in (("photo", entry.photo), ("audio", entry.audio))
        if refs
    }


def check_shrink(
    new: LoadedCatalog, previous: LoadedCatalog, *, allow_shrink: bool = False
) -> ValidationResult:
    """No region loses > 10% of its species; the catalog loses <= 5% of its filled photo/audio slots.

    Species are compared by id, so newly added species can't mask lost ones. With
    ``allow_shrink`` (the deliberate-drop override) the same findings are warnings.
    """
    res = ValidationResult()
    for slug, old_region in sorted(previous.regions.items()):
        old_ids = {sid for sid, _ in old_region.species}
        if not old_ids:
            continue
        new_region = new.regions.get(slug)
        new_ids = {sid for sid, _ in new_region.species} if new_region else set()
        lost = sorted(old_ids - new_ids)
        if len(lost) * 100 > len(old_ids) * REGION_SHRINK_LIMIT_PCT:
            what = "was removed" if new_region is None else "lost species"
            res.error(
                "shrink.region",
                f"region {slug} {what}: {len(lost)} of {len(old_ids)} species gone "
                f"({100 * len(lost) / len(old_ids):.1f}% > {REGION_SHRINK_LIMIT_PCT}%): "
                f"{_preview(lost)}",
                slug,
            )
    # A slot is a (species, role) that holds an asset. Swapping one asset for another
    # (a pin, a credit-removal exclusion) keeps the slot; only a slot that empties is a loss.
    old_slots = _filled_slots(previous)
    if old_slots:
        lost_slots = sorted(old_slots - _filled_slots(new))
        if len(lost_slots) * 100 > len(old_slots) * ASSET_SHRINK_LIMIT_PCT:
            res.error(
                "shrink.assets",
                f"{len(lost_slots)} of {len(old_slots)} media assets gone "
                f"({100 * len(lost_slots) / len(old_slots):.1f}% > {ASSET_SHRINK_LIMIT_PCT}%): "
                f"{_preview([f'{sid}/{role}' for sid, role in lost_slots])}",
                "",
            )
    return res.downgraded() if allow_shrink else res


# ---------------------------------------------------------------------------------------
# 6. Structural sanity
# ---------------------------------------------------------------------------------------


def check_structure(catalog: LoadedCatalog) -> ValidationResult:
    """Names are present, and every region species exists in species.json (no dupes)."""
    res = ValidationResult()
    for sid, entry in sorted(catalog.species.items()):
        if not entry.name.strip():
            res.error("species.name_missing", "blank common name", sid)
        if not entry.sci.strip():
            res.error("species.sci_missing", "blank scientific name", sid)
    for slug, region in sorted(catalog.regions.items()):
        seen: set[str] = set()
        for sid, _ in region.species:
            if sid not in catalog.species:
                res.error("region.unknown_species", f"region {slug} lists {sid!r}, absent from species.json", sid)
            if sid in seen:
                res.error("region.duplicate_species", f"region {slug} lists {sid!r} twice", sid)
            seen.add(sid)
    return res


# ---------------------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------------------


def validate_catalog(
    new: LoadedCatalog | Path,
    previous: LoadedCatalog | None = None,
    *,
    allow_shrink: bool = False,
    pins: Pins | None = None,
    max_site_bytes: int = MAX_SITE_BYTES,
) -> ValidationResult:
    """Run every gate check on ``new`` (a loaded catalog or its directory).

    A directory that fails to load is reported as one ``format.invalid`` error (the other
    checks need a loaded catalog). ``previous`` enables the shrink checks; ``pins`` (species
    id -> pin table) enables the exclusion check.
    """
    if isinstance(new, Path):
        try:
            catalog = load_catalog(new)
        except FormatError as exc:
            return ValidationResult([Problem("format.invalid", str(exc), str(new))])
    else:
        catalog = new

    result = ValidationResult()
    for partial in (
        check_media_files(catalog),
        check_provenance_coverage(catalog),
        check_licences(catalog),
        check_credits(catalog),
        check_audio_verified(catalog),
        check_pins(catalog, pins),
        check_size(catalog, max_site_bytes),
        check_structure(catalog),
    ):
        result.merge(partial)
    if previous is not None:
        result.merge(check_shrink(catalog, previous, allow_shrink=allow_shrink))
    log.info("catalog validation: %d error(s), %d warning(s)", len(result.errors), len(result.warnings))
    return result


def format_result(result: ValidationResult) -> str:
    """A plain-text rendering for the CLI and workflow logs."""
    head = "PASSED" if result.ok else "FAILED"
    lines = [f"validation {head}: {len(result.errors)} error(s), {len(result.warnings)} warning(s)"]
    for label, problems in (("ERROR", result.errors), ("WARN ", result.warnings)):
        for p in problems:
            where = f" {p.subject}:" if p.subject else ""
            lines.append(f"{label} [{p.code}]{where} {p.message}")
    return "\n".join(lines)


__all__ = [
    "ASSET_SHRINK_LIMIT_PCT",
    "BIRDNET_MIN_CONFIDENCE",
    "MAX_SITE_BYTES",
    "REGION_SHRINK_LIMIT_PCT",
    "Pins",
    "Problem",
    "ValidationResult",
    "check_audio_verified",
    "check_credits",
    "check_licences",
    "check_media_files",
    "check_pins",
    "check_provenance_coverage",
    "check_shrink",
    "check_size",
    "check_structure",
    "format_result",
    "site_bytes",
    "validate_catalog",
]
