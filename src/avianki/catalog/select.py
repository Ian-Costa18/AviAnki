"""Pure decision logic for asset selection (ADR 0011, 0014, 0023).

Nothing here touches the network, the disk or a clock. `catalog.build` does the I/O and
asks this module the questions that have a rule for an answer:

* is a previous catalog's asset still good, or must it be rebuilt (`sticky_problem`)?
* which candidates may be tried, in what order, how many (`screen_candidates`, `slots_left`)?
* what do the provenance entry and the stored credit for a chosen asset look like
  (`provenance_entry`, `media_ref`, `reused_media_ref`)?
* in what order do species rank overall (`overall_order`)?

Every function takes plain values and returns plain values, so the rules are tested
exhaustively without any fake source.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from avianki.catalog.credit import render_credit
from avianki.catalog.format import Kind, MediaRef, ProvenanceEntry, ProvenanceFile, SpeciesFile, Verified
from avianki.catalog.pins import Pin
from avianki.catalog.report import Rejection
from avianki.catalog.validate import BIRDNET_MIN_CONFIDENCE
from avianki.core.licences import AssetRecord, is_allowed
from avianki.sources.contract import AssetKind, Candidate

__all__ = [
    "MAX_AUDIO_CANDIDATES",
    "MIN_PHOTO_LONG_SIDE",
    "PHOTO_CANDIDATES",
    "PreviousAsset",
    "final_record",
    "hard_problem",
    "kind_name",
    "media_ref",
    "overall_order",
    "previous_asset",
    "provenance_entry",
    "reused_media_ref",
    "screen_candidates",
    "slots_left",
    "sticky_problem",
]

PHOTO_CANDIDATES = 5  # photos asked of each source per species (ADR 0011)
MAX_AUDIO_CANDIDATES = 5  # recordings BirdNET may look at per species, all sources together (ADR 0023)
MIN_PHOTO_LONG_SIDE = 800  # ADR 0011; `media.images.process_image` enforces it on the pixels too


def kind_name(kind: AssetKind) -> Kind:
    """The catalog's spelling of an asset kind. Only photos and audio are catalog media."""
    if kind is AssetKind.PHOTO:
        return "photo"
    if kind is AssetKind.AUDIO:
        return "audio"
    raise ValueError(f"{kind} is not a catalog media kind")


# ---------------------------------------------------------------------------------------
# Sticky selections (ADR 0014)
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviousAsset:
    """One role's asset in the previous catalog: the reference and its audit record.

    ``provenance`` is None when the previous catalog has no record for the file, which
    makes the asset unusable (it can be neither credited nor checked).
    """

    ref: MediaRef
    provenance: ProvenanceEntry | None


def previous_asset(
    species: SpeciesFile | None,
    provenance: ProvenanceFile | None,
    species_id: str,
    kind: Kind,
) -> PreviousAsset | None:
    """The previous catalog's asset for a species and role, or None if it had none."""
    if species is None or species_id not in species:
        return None
    entry = species[species_id]
    refs = entry.photo if kind == "photo" else entry.audio
    if not refs:
        return None
    ref = refs[0]
    prov = provenance.entries.get(ref.file) if provenance is not None else None
    return PreviousAsset(ref, prov)


def hard_problem(
    species_id: str,
    kind: Kind,
    asset: PreviousAsset,
    pin: Pin | None,
    media_problem: str | None,
) -> str | None:
    """Why the previous asset can never be published again, or None.

    These are the reasons that would fail the publish gate or break a takedown request,
    so the asset can't be kept even as a fallback: no audit record, an exclusion by a pin,
    a licence no longer on the allowlist, an incomplete credit, a missing or corrupt file,
    and (audio) no BirdNET verification.
    """
    prov = asset.provenance
    if prov is None:
        return "no provenance record"
    if prov.species_id != species_id or prov.kind != kind:
        return f"provenance is for {prov.species_id} {prov.kind}"
    if pin is not None and pin.excludes(prov.record.source, prov.token):
        return f"excluded by a pin ({prov.record.source}:{prov.token})"
    if not is_allowed(prov.record.licence_id):
        return f"licence {prov.record.licence_id!r} is not allowed"
    missing = prov.record.missing_required_fields()
    if missing:
        return f"missing credit fields: {', '.join(missing)}"
    if media_problem:
        return f"media: {media_problem}"
    try:
        render_credit(kind, prov.record)
    except ValueError as exc:
        return f"credit can't be rendered: {exc}"
    if kind == "audio":
        if prov.verified is None:
            return "audio was never verified"
        if prov.verified == "pinned":
            pinned = pin.forced(AssetKind.AUDIO) if pin is not None else None
            if pinned is None or (pinned.source, pinned.token) != (prov.record.source, prov.token):
                return "audio was pinned but no pin names it any more, and it never passed BirdNET"
        if prov.verified == "birdnet" and (
            prov.birdnet_confidence is None or prov.birdnet_confidence < BIRDNET_MIN_CONFIDENCE
        ):
            return f"BirdNET confidence below {BIRDNET_MIN_CONFIDENCE}"
    return None


def sticky_problem(
    species_id: str,
    kind: Kind,
    asset: PreviousAsset,
    pin: Pin | None,
    media_problem: str | None,
) -> str | None:
    """Why the previous asset must be rebuilt rather than reused, or None to keep it.

    Everything in `hard_problem`, plus a pin that now names a different asset. A previous
    asset that the pin merely *replaces* is still publishable, which lets the build fall
    back to it if the new pin can't be honoured.
    """
    hard = hard_problem(species_id, kind, asset, pin, media_problem)
    if hard is not None:
        return hard
    forced = pin.forced(AssetKind.PHOTO if kind == "photo" else AssetKind.AUDIO) if pin is not None else None
    prov = asset.provenance
    assert prov is not None  # hard_problem returned None
    if forced is not None and (forced.source, forced.token) != (prov.record.source, prov.token):
        return f"a pin now names {forced}"
    return None


# ---------------------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------------------


def slots_left(tried: int, cap: int = MAX_AUDIO_CANDIDATES) -> int:
    """How many more audio candidates may be evaluated for a species that has had ``tried``."""
    return max(0, cap - tried)


def screen_candidates(
    candidates: Iterable[Candidate],
    *,
    species_id: str,
    kind: AssetKind,
    source: str,
    pin: Pin | None,
) -> tuple[list[Candidate], list[Rejection]]:
    """Drop what may not be tried, keeping the source's own ranking for the rest.

    Removed, each with a `Rejection`: candidates for another species, candidates a pin
    excludes (a credit-removal request), licences off the allowlist, records too
    incomplete to credit, and photos whose advertised size is under 800 px. Candidates the
    source gave no size for are kept; `process_image` measures the real pixels.
    """
    kept: list[Candidate] = []
    rejections: list[Rejection] = []
    label = kind_name(kind)

    def reject(c: Candidate, why: str) -> None:
        rejections.append(Rejection(species_id, label, source, c.token, why))

    for c in candidates:
        if c.species_id != species_id or c.kind is not kind:
            reject(c, f"wrong target: candidate is {c.species_id} {c.kind.value}")
        elif pin is not None and pin.excludes(source, c.token):
            reject(c, "excluded by pin")
        elif not is_allowed(c.record.licence_id):
            reject(c, f"licence: {c.record.licence_id}")
        elif c.record.missing_required_fields():
            reject(c, f"incomplete credit: {', '.join(c.record.missing_required_fields())}")
        elif kind is AssetKind.PHOTO and c.width and c.height and max(c.width, c.height) < MIN_PHOTO_LONG_SIDE:
            reject(c, f"too small: {c.width}x{c.height}")
        else:
            kept.append(c)
    return kept, rejections


# ---------------------------------------------------------------------------------------
# Assembling what gets published
# ---------------------------------------------------------------------------------------


def final_record(record: AssetRecord, modifications: Iterable[str]) -> AssetRecord:
    """The record with the pipeline's own processing steps appended to ``modifications``."""
    for step in modifications:
        record = record.with_modification(step)
    return record


def media_ref(kind: Kind, file: str, size: int, record: AssetRecord) -> MediaRef:
    """The species-file reference for a new asset. Raises ValueError if it can't be credited."""
    return MediaRef(file=file, bytes=size, credit=render_credit(kind, record))


def reused_media_ref(kind: Kind, asset: PreviousAsset) -> MediaRef:
    """A kept asset's reference. The credit is re-rendered from its provenance, so a change
    to the credit format reaches reused assets too (the media bytes are never touched)."""
    assert asset.provenance is not None
    return MediaRef(asset.ref.file, asset.ref.bytes, render_credit(kind, asset.provenance.record))


def provenance_entry(
    record: AssetRecord,
    *,
    species_id: str,
    kind: Kind,
    token: str,
    verified: Verified | None,
    birdnet_confidence: float | None = None,
) -> ProvenanceEntry:
    """The audit record for a chosen asset. ``verified`` is ``"birdnet"`` (with the best
    confidence found), ``"pinned"`` (no confidence), or None for an unverified photo."""
    if verified == "birdnet" and birdnet_confidence is None:
        raise ValueError("a birdnet-verified asset needs its confidence")
    if verified != "birdnet" and birdnet_confidence is not None:
        raise ValueError("only birdnet-verified assets carry a confidence")
    return ProvenanceEntry(
        record=record,
        species_id=species_id,
        kind=kind,
        token=token,
        verified=verified,
        birdnet_confidence=birdnet_confidence,
    )


# ---------------------------------------------------------------------------------------
# Species order
# ---------------------------------------------------------------------------------------


def overall_order(regions: Mapping[str, Sequence[str]]) -> list[str]:
    """Every species id in the region lists, most widespread-and-common first.

    Each region list is in rank order. A species' overall key is its best (lowest) rank in
    any region, then the number of regions it appears in (more first), then its id, so the
    order is deterministic and independent of dict order. ``--max-species N`` keeps the
    first N.
    """
    best: dict[str, int] = {}
    count: dict[str, int] = {}
    for ids in regions.values():
        for rank, sid in enumerate(ids, start=1):
            best[sid] = min(best.get(sid, rank), rank)
            count[sid] = count.get(sid, 0) + 1
    return sorted(best, key=lambda sid: (best[sid], -count[sid], sid))
