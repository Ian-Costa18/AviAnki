"""The M3 catalog build: pick media per species, assemble, validate (spec section 4, ADR 0007, 0011, 0014, 0023).

Two public entry points:

* `build_species` picks the photo and recording for a list of species. It takes every
  collaborator as an argument (species table, source registry, pins, the previous catalog,
  the BirdNET analyser), prints nothing and reads no clock but the one it is handed, so the
  whole pipeline runs against fake sources in tests. It returns the species file, the
  provenance file, the new media bytes and a `BuildReport`.
* `run_build` is the full build: the species half (region lists), `build_species`, writing
  ``site/``, the validation gate, the credits page, the contact sheet and the report.
  ``catalog_cli`` is a thin argument parser around it.

Rules that matter more than the code around them:

* **A failure is never absence** (ADR 0007). A `SourceError` for a species and role means the
  source could not say. The role is not filled from the next source and is not recorded as
  absent: it keeps the previous release's entry when there is one and the species is listed
  as unfinished. Only a real ``[]`` from every source is absence.
* **Sticky** (ADR 0014). A previous asset is kept, byte for byte, unless it can no longer be
  published (`select.sticky_problem`). Species whose roles are all kept make no source calls,
  and BirdNET never re-runs on a kept recording.
* **Audio** (ADR 0023). Candidates are tried in source order, at most five, and the first that
  BirdNET scores at 0.5 or more in some 3 s window (analysing only the first 60 s) wins. Later
  candidates are never downloaded.
* **Pins** (ADR 0011) skip ranking and BirdNET but not the licence gate. A pin that can't be
  honoured is a hard error for its species, reported prominently; the previous entry stays.
"""

from __future__ import annotations

import inspect
import logging
import shutil
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from avianki.catalog.format import (
    DEFAULT_BASE_URL,
    DatasetCredit,
    FormatError,
    Kind,
    LoadedCatalog,
    Manifest,
    MediaRef,
    ProvenanceEntry,
    ProvenanceFile,
    RegionFile,
    RegionRef,
    SpeciesEntry,
    SpeciesFile,
    Verified,
    load_catalog,
    media_filename,
    write_catalog,
    write_media,
)
from avianki.catalog.pins import AssetRef, Pins
from avianki.catalog.report import (
    BuildReport,
    PlausibilityFlag,
    Rejection,
    SourceFailure,
    render_build_report,
    render_contact_sheet,
    render_credits_page,
)
from avianki.catalog.select import (
    PHOTO_CANDIDATES,
    PreviousAsset,
    final_record,
    hard_problem,
    kind_name,
    media_ref,
    overall_order,
    previous_asset,
    provenance_entry,
    reused_media_ref,
    reused_provenance,
    screen_candidates,
    slots_left,
    sticky_problem,
)
from avianki.catalog.species_lists import TOP_N, SpeciesListsResult, build_species_lists
from avianki.catalog.validate import BIRDNET_MIN_CONFIDENCE, ValidationResult, validate_catalog
from avianki.core.http import BudgetExhausted, HttpClient, HttpError, SourceError
from avianki.core.licences import AssetRecord, is_allowed
from avianki.media.audio import excerpt, process_audio
from avianki.media.errors import MediaError
from avianki.media.images import process_image
from avianki.media.verify import (
    Analyzer,
    UnreadableAudio,
    VerifyError,
    VerifyUnavailable,
    analyse,
    birdnet_label,
    load_labels,
)
from avianki.sources.commons.source import CommonsSource
from avianki.sources.commons.xenocanto import XenoCantoLookup
from avianki.sources.contract import AssetKind, AssetSource, Candidate, FetchedAsset, Region, SpeciesSource
from avianki.sources.inaturalist.source import INaturalistSource
from avianki.sources.registry import Registry
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

__all__ = [
    "DEFAULT_BASE_URL",
    "BuildOptions",
    "BuildResult",
    "SpeciesBuild",
    "build_species",
    "dataset_credits",
    "make_registry",
    "run_build",
]

log = logging.getLogger("bird_deck")

CHUNK = 50  # species per `candidates` call
BREAKER = 5  # consecutive per-species failures after which a source is given up on for the run
GONE = frozenset({404, 410})  # a candidate that has disappeared: not a source failure
PHOTO_EXT = "webp"
AUDIO_EXT = "mp3"


# ---------------------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------------------


def make_registry(
    client: HttpClient,
    species_table: SpeciesTable,
    expected_counts: Mapping[str, int] | None = None,
    xc: XenoCantoLookup | None = None,
) -> Registry:
    """A fresh registry with the real asset sources, all sharing ``client``.

    ``expected_counts`` (species id -> EOD North American record count) turns on
    iNaturalist's plausibility check (ADR 0022). ``xc`` lets Commons order its audio by
    xeno-canto metadata (ADR 0031); None leaves the order alone. Order and kinds come from
    `registry.ORDER`.
    """
    registry = Registry()
    registry.register(CommonsSource(client, species_table, xc))
    registry.register(INaturalistSource(client, species_table, expected_counts=expected_counts, today=client.today))
    return registry


def dataset_credits() -> list[DatasetCredit]:
    """Deck-level dataset credits (ADR 0012) for what the species half is built from."""
    return [
        DatasetCredit(
            text="eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF",
            licence_id="CC-BY-4.0",
            url="https://doi.org/10.15468/aomfnb",
            modifications="filtered and ranked by region; English species names",
        ),
        DatasetCredit(
            text="IOC World Bird List (Gill, Donsker and Rasmussen, eds.), for scientific names",
            licence_id="CC-BY-4.0",
            url="https://www.worldbirdnames.org/",
            modifications="matched to GBIF taxa",
        ),
    ]


# ---------------------------------------------------------------------------------------
# build_species
# ---------------------------------------------------------------------------------------


@dataclass
class SpeciesBuild:
    """What `build_species` chose.

    ``media`` holds only the files built this run (catalog-relative name -> bytes);
    ``reused_media`` names the previous catalog's files the result refers to, which the
    caller copies from the previous catalog's directory.
    """

    species: SpeciesFile
    provenance: ProvenanceFile
    media: dict[str, bytes]
    reused_media: set[str]
    report: BuildReport


@runtime_checkable
class _ResolvesTaxa(Protocol):
    def resolve_taxa(self, species_ids: Iterable[str]) -> dict[str, int]: ...


@runtime_checkable
class _FlagsSpecies(Protocol):
    def flagged(self) -> list: ...  # type: ignore[type-arg]


class _StopSource(Exception):
    """Internal: this source can't be used any more this run (budget spent)."""


@dataclass
class _Role:
    """One (species, photo|audio) slot while the build runs."""

    kind: Kind
    pin: AssetRef | None = None
    ref: MediaRef | None = None
    prov: ProvenanceEntry | None = None
    data: bytes | None = None  # bytes of a media file built this run
    reused: bool = False
    fallback: PreviousAsset | None = None  # previous asset that a new pin replaces
    closed: bool = False  # nothing to try (no BirdNET label, --no-verify)
    incomplete: bool = False  # a source failed, ran out of budget or time: not absence, and no fall-through
    pin_failed: bool = False
    tried: int = 0  # audio candidates evaluated

    @property
    def done(self) -> bool:
        return self.ref is not None

    @property
    def pending(self) -> bool:
        return not self.done and not self.closed and not self.pin_failed and not self.incomplete


def _kind_of(kind: AssetKind) -> Kind:
    return kind_name(kind)


class _Builder:
    def __init__(
        self,
        species_ids: Iterable[str | SpeciesRow],
        *,
        table: SpeciesTable,
        registry: Registry,
        pins: Pins | None,
        previous: LoadedCatalog | None,
        analyzer: Analyzer | None,
        verify: bool,
        labels: Sequence[str] | None,
        deadline: float | None,
        clock: Callable[[], float],
    ) -> None:
        self.table = table
        self.registry = registry
        self.pins = pins if pins is not None else Pins({})
        self.previous = previous
        self.analyzer = analyzer
        self.verify = verify
        self._labels_arg = labels
        self._labels: list[str] | None = None
        self.deadline = deadline
        self.clock = clock
        self.report = BuildReport()
        self.calls = 0
        self.exhausted: set[str] = set()
        self.timed_out = False
        self.owners: dict[str, tuple[str, str]] = {}  # media file -> (species, kind)
        self.pin_error_species: set[str] = set()

        self.rows: dict[str, SpeciesRow] = {}
        for item in species_ids:
            row = item if isinstance(item, SpeciesRow) else table.get(item)
            row = table.get(row.id)
            self.rows.setdefault(row.id, row)
        self.ids = list(self.rows)
        self.roles: dict[str, dict[Kind, _Role]] = {}
        self.labels_by_species: dict[str, str] = {}

    # -- small helpers -----------------------------------------------------------------

    def _expired(self) -> bool:
        if self.deadline is not None and self.clock() >= self.deadline:
            self.timed_out = True
        return self.timed_out

    def _reject(self, sid: str, kind: Kind, source: str, token: str, reason: str) -> None:
        self.report.rejections.append(Rejection(sid, kind, source, token, reason))

    def _fail(self, source: str, sid: str | None, exc: Exception) -> None:
        log.warning("%s: %s: %s", source, sid or "(batch)", exc)
        self.report.source_failures.append(SourceFailure(source, sid, str(exc)))

    def _exhaust(self, source: str, sid: str | None, exc: Exception) -> None:
        self.exhausted.add(source)
        self.report.budget_exhausted = True
        self._fail(source, sid, exc)

    def _mark_incomplete(self, kind: Kind, sids: Iterable[str]) -> None:
        for sid in sids:
            role = self.roles[sid][kind]
            if role.pending:
                role.incomplete = True

    def _discover(self, sid: str, key: str, value: str) -> None:
        self.report.new_ids_discovered.setdefault(sid, {})[key] = value

    def _unmapped(self, sid: str, what: str) -> None:
        missing = self.report.unmapped_species.setdefault(sid, [])
        if what not in missing:
            missing.append(what)

    def _label(self, sid: str) -> str | None:
        row = self.rows[sid]
        if row.birdnet_label:
            return row.birdnet_label
        if self._labels is None:
            got = self._labels_arg
            if got is None:
                got = getattr(self.analyzer, "labels", None)
            if got is None:
                got = load_labels()
            self._labels = list(got)
        found = birdnet_label(row.sci_name, self._labels)
        if found:
            self._discover(sid, "birdnet_label", found)
        return found

    def _named_source(self, kind: AssetKind, name: str) -> AssetSource | None:
        return next((s for s in self.registry.asset_sources(kind) if s.name == name), None)

    def _pin_error(self, sid: str, kind: Kind, message: str) -> None:
        role = self.roles[sid][kind]
        role.pin_failed = True
        self.pin_error_species.add(sid)
        text = f"{sid} {kind}: pin {role.pin}: {message}"
        log.error("PIN ERROR %s", text)
        self.report.pin_errors.append(text)

    def _accept(
        self,
        role: _Role,
        sid: str,
        token: str,
        data: bytes,
        ext: str,
        record: AssetRecord,
        *,
        verified: Verified | None,
        confidence: float | None = None,
    ) -> str | None:
        """Take a processed asset for ``role``. Returns None on success, else why it was refused."""
        if not is_allowed(record.licence_id):
            return f"licence: {record.licence_id}"
        name = media_filename(data, ext)
        owner = self.owners.get(name)
        if owner is not None and owner != (sid, role.kind):
            return f"duplicate of {owner[0]}'s {owner[1]}"
        try:
            ref = media_ref(role.kind, name, len(data), record)
        except ValueError as exc:
            return f"incomplete credit: {exc}"
        role.ref = ref
        role.prov = provenance_entry(
            record,
            species_id=sid,
            kind=role.kind,
            token=token,
            verified=verified,
            birdnet_confidence=confidence,
        )
        role.data = data
        role.reused = False
        self.owners[name] = (sid, role.kind)
        return None

    # -- phases -------------------------------------------------------------------------

    def run(self) -> SpeciesBuild:
        started = self.clock()
        for sid in self.ids:
            pin = self.pins.get(sid)
            self.roles[sid] = {
                "photo": _Role("photo", pin.photo if pin else None),
                "audio": _Role("audio", pin.audio if pin else None),
            }
        self._sticky()
        self._pinned()
        self._ranked_photos()
        self._ranked_audio()
        self._plausibility()
        for source in self.registry.asset_sources(AssetKind.AUDIO):
            self.report.notes.extend(source.notes())
        result = self._assemble()
        self.report.elapsed_s = self.clock() - started
        return result

    def _sticky(self) -> None:
        prev = self.previous
        for sid in self.ids:
            pin = self.pins.get(sid)
            for kind, role in self.roles[sid].items():
                asset = previous_asset(
                    prev.species if prev else None, prev.provenance if prev else None, sid, kind
                )
                if asset is None or prev is None:
                    continue
                try:
                    media = prev.media_problem(asset.ref.file, asset.ref.bytes)
                except FormatError as exc:
                    media = str(exc)
                problem = sticky_problem(sid, kind, asset, pin, media)
                if problem is None:
                    role.ref = reused_media_ref(kind, asset, self.rows[sid])
                    role.prov = reused_provenance(asset, self.rows[sid])
                    role.reused = True
                    self.owners[asset.ref.file] = (sid, kind)
                    continue
                self.report.sticky_invalidated += 1
                log.info("%s %s: previous asset not kept: %s", sid, kind, problem)
                if hard_problem(sid, kind, asset, pin, media) is None:
                    role.fallback = asset  # only a new pin stands in its way

    def _pinned(self) -> None:
        for sid in self.ids:
            for kind, role in self.roles[sid].items():
                if role.done or role.pin is None:
                    continue
                self._honour_pin(sid, kind, role, role.pin)

    def _honour_pin(self, sid: str, kind: Kind, role: _Role, ref: AssetRef) -> None:
        asset_kind = AssetKind.PHOTO if kind == "photo" else AssetKind.AUDIO
        source = self._named_source(asset_kind, ref.source)
        if source is None:
            self._pin_error(sid, kind, f"source {ref.source!r} is not available for {kind}")
            return
        if source.name in self.exhausted:
            self._pin_error(sid, kind, f"{source.name} has no request budget left")
            return
        try:
            self.calls += 1
            cand = _resolve_pin(source, ref.token, sid)
            if cand.kind is not asset_kind or cand.species_id != sid:
                self._pin_error(
                    sid, kind, f"resolves to {cand.species_id} {cand.kind.value}, not {sid} {kind}"
                )
                return
            if not is_allowed(cand.record.licence_id):
                self._pin_error(sid, kind, f"licence {cand.record.licence_id!r} is not allowed")
                return
            missing = cand.record.missing_required_fields()
            if missing:
                self._pin_error(sid, kind, f"incomplete credit: {', '.join(missing)}")
                return
            self.calls += 1
            fetched = source.fetch(cand)
        except BudgetExhausted as exc:
            self._exhaust(source.name, sid, exc)
            self._pin_error(sid, kind, str(exc))
            return
        except SourceError as exc:
            self._fail(source.name, sid, exc)
            self._pin_error(sid, kind, f"source error: {exc}")
            return
        try:
            if kind == "photo":
                img = process_image(fetched.data)
                data, ext, mods = img.data, PHOTO_EXT, img.modifications
            else:
                clip = process_audio(fetched.data, 0.0)
                data, ext, mods = clip.data, AUDIO_EXT, clip.modifications
        except MediaError as exc:
            self._pin_error(sid, kind, f"could not be processed: {exc}")
            return
        record = final_record(fetched.record, mods)
        why = self._accept(role, sid, cand.token, data, ext, record, verified="pinned")
        if why:
            self._pin_error(sid, kind, why)

    # -- the shared per-source driver ---------------------------------------------------

    def _limit(self, kind: AssetKind, sids: Sequence[str]) -> int:
        excluded = max((len(p.exclude) for sid in sids if (p := self.pins.get(sid))), default=0)
        if kind is AssetKind.PHOTO:
            return PHOTO_CANDIDATES + excluded
        return max((slots_left(self.roles[sid]["audio"].tried) for sid in sids), default=0) + excluded

    def _stage(
        self,
        source: AssetSource,
        asset_kind: AssetKind,
        sids: list[str],
        handle: Callable[[AssetSource, str, list[Candidate]], None],
    ) -> None:
        """Ask ``source`` for ``sids`` in chunks and hand each species' candidates to ``handle``.

        A failed batch is retried species by species; five failures in a row give up on the
        source for the run. `BudgetExhausted` stops the source at once. Every species not
        answered for is marked incomplete (never absent).
        """
        kind = _kind_of(asset_kind)
        name = source.name
        if not sids:
            return
        if name in self.exhausted:
            self._mark_incomplete(kind, sids)
            return
        consecutive = 0
        start = 0
        while start < len(sids):
            if self._expired():
                self._mark_incomplete(kind, sids[start:])
                return
            chunk = sids[start : start + CHUNK]
            start += CHUNK
            rest = sids[start:]
            answers: dict[str, list[Candidate]] = {}
            failed: set[str] = set()
            try:
                self.calls += 1
                answers = dict(source.candidates(chunk, asset_kind, self._limit(asset_kind, chunk)))
            except BudgetExhausted as exc:
                self._exhaust(name, None, exc)
                self._mark_incomplete(kind, [*chunk, *rest])
                return
            except SourceError as exc:
                log.warning("%s: batch of %d failed (%s); retrying one species at a time", name, len(chunk), exc)
                for i, sid in enumerate(chunk):
                    try:
                        self.calls += 1
                        answers.update(source.candidates([sid], asset_kind, self._limit(asset_kind, [sid])))
                        consecutive = 0
                    except BudgetExhausted as exc2:
                        self._exhaust(name, sid, exc2)
                        self._mark_incomplete(kind, [*chunk[i:], *rest])
                        return
                    except SourceError as exc2:
                        self._fail(name, sid, exc2)
                        failed.add(sid)
                        self.roles[sid][kind].incomplete = True
                        consecutive += 1
                        if consecutive >= BREAKER:
                            self.report.notes.append(
                                f"{name}: gave up on {kind} candidates after {BREAKER} failures in a row"
                            )
                            self._mark_incomplete(kind, [*chunk[i + 1 :], *rest])
                            return
            else:
                consecutive = 0
            self._note_taxa(source, [s for s in chunk if s not in failed])
            for i, sid in enumerate(chunk):
                if sid in failed:
                    continue
                if self._expired():
                    self._mark_incomplete(kind, [*chunk[i:], *rest])
                    return
                try:
                    handle(source, sid, list(answers.get(sid) or []))
                except _StopSource:
                    self._mark_incomplete(kind, [*chunk[i + 1 :], *rest])
                    return

    def _note_taxa(self, source: AssetSource, sids: list[str]) -> None:
        """Record iNaturalist taxon ids the run resolved (a cached lookup, no new requests)."""
        if not isinstance(source, _ResolvesTaxa) or not sids:
            return
        try:
            taxa = source.resolve_taxa(sids)
        except SourceError as exc:
            log.debug("%s: taxon lookup failed: %s", source.name, exc)
            return
        flagged = {f.species_id for f in source.flagged()} if isinstance(source, _FlagsSpecies) else set()
        for sid in sids:
            taxon = taxa.get(sid)
            if taxon is None:
                if sid not in flagged:
                    self._unmapped(sid, "inat_taxon_id")
            elif self.rows[sid].inat_taxon_id != taxon:
                self._discover(sid, "inat_taxon_id", str(taxon))

    def _fetch(self, source: AssetSource, cand: Candidate, sid: str, role: _Role) -> tuple[FetchedAsset | None, bool]:
        """Download a candidate. Returns ``(asset, stop)``: ``asset`` None with ``stop`` False
        means skip this candidate (it is gone); ``stop`` True means give up on this species here."""
        self.calls += 1
        try:
            return source.fetch(cand), False
        except HttpError as exc:
            if exc.status in GONE:
                self._reject(sid, role.kind, source.name, cand.token, f"gone: HTTP {exc.status}")
                return None, False
            self._fail(source.name, sid, exc)
        except BudgetExhausted as exc:
            self._exhaust(source.name, sid, exc)
            role.incomplete = True
            raise _StopSource from exc
        except SourceError as exc:
            self._fail(source.name, sid, exc)
        role.incomplete = True
        return None, True

    # -- photos -------------------------------------------------------------------------

    def _ranked_photos(self) -> None:
        for source in self.registry.asset_sources(AssetKind.PHOTO):
            pending = [sid for sid in self.ids if self.roles[sid]["photo"].pending]
            self._stage(source, AssetKind.PHOTO, pending, self._photo_species)

    def _photo_species(self, source: AssetSource, sid: str, candidates: list[Candidate]) -> None:
        role = self.roles[sid]["photo"]
        kept, rejections = screen_candidates(
            candidates, species_id=sid, kind=AssetKind.PHOTO, source=source.name, pin=self.pins.get(sid)
        )
        self.report.rejections.extend(rejections)
        for cand in kept[:PHOTO_CANDIDATES]:
            fetched, stop = self._fetch(source, cand, sid, role)
            if stop:
                return
            if fetched is None:
                continue
            try:
                img = process_image(fetched.data)
            except MediaError as exc:
                self._reject(sid, "photo", source.name, cand.token, f"image: {exc}")
                continue
            record = final_record(fetched.record, img.modifications)
            why = self._accept(role, sid, cand.token, img.data, PHOTO_EXT, record, verified=None)
            if why is None:
                return
            self._reject(sid, "photo", source.name, cand.token, why)

    # -- audio --------------------------------------------------------------------------

    def _ranked_audio(self) -> None:
        if not self.verify:
            skipped = 0
            for sid in self.ids:
                role = self.roles[sid]["audio"]
                if role.pending:
                    role.closed = True
                    skipped += 1
            self.report.notes.append(
                f"AUDIO NOT VERIFIED: built with --no-verify, so audio comes only from pins ({skipped} species "
                "have none). Do not publish this catalog."
            )
            return
        for sid in self.ids:
            role = self.roles[sid]["audio"]
            if not role.pending:
                continue
            label = self._label(sid)
            if label is None:
                role.closed = True
                self._unmapped(sid, "birdnet_label")
            else:
                self.labels_by_species[sid] = label
        for source in self.registry.asset_sources(AssetKind.AUDIO):
            pending = [
                sid
                for sid in self.ids
                if self.roles[sid]["audio"].pending and slots_left(self.roles[sid]["audio"].tried) > 0
            ]
            self._stage(source, AssetKind.AUDIO, pending, self._audio_species)

    def _audio_species(self, source: AssetSource, sid: str, candidates: list[Candidate]) -> None:
        role = self.roles[sid]["audio"]
        label = self.labels_by_species[sid]
        kept, rejections = screen_candidates(
            candidates, species_id=sid, kind=AssetKind.AUDIO, source=source.name, pin=self.pins.get(sid)
        )
        self.report.rejections.extend(rejections)
        for cand in kept[: slots_left(role.tried)]:
            role.tried += 1
            fetched, stop = self._fetch(source, cand, sid, role)
            if stop:
                return
            if fetched is None:
                continue
            _require_ffmpeg()
            try:
                clip = excerpt(fetched.data)
                analysis = analyse(clip, label, min_confidence=BIRDNET_MIN_CONFIDENCE, analyzer=self.analyzer)
            except VerifyUnavailable:
                raise
            except UnreadableAudio as exc:
                self._reject(sid, "audio", source.name, cand.token, f"unreadable: {exc}")
                continue
            except VerifyError as exc:
                # e.g. the species' label isn't a BirdNET label: no candidate can pass
                log.warning("%s: BirdNET could not score %s: %s", sid, label, exc)
                self._reject(sid, "audio", source.name, cand.token, f"birdnet: {exc}")
                role.closed = True
                self._unmapped(sid, "birdnet_label")
                return
            except MediaError as exc:
                self._reject(sid, "audio", source.name, cand.token, f"unreadable: {exc}")
                continue
            if not analysis.passes:
                self._reject(
                    sid, "audio", source.name, cand.token,
                    f"birdnet: best {analysis.best_confidence:.2f} < {BIRDNET_MIN_CONFIDENCE}",
                )  # fmt: skip
                continue
            start, _end = analysis.best_window()
            try:
                processed = process_audio(fetched.data, start)
            except MediaError as exc:
                self._reject(sid, "audio", source.name, cand.token, f"unprocessable: {exc}")
                continue
            record = final_record(fetched.record, processed.modifications)
            why = self._accept(
                role, sid, cand.token, processed.data, AUDIO_EXT, record,
                verified="birdnet", confidence=round(analysis.best_confidence, 4),
            )  # fmt: skip
            if why is None:
                return
            self._reject(sid, "audio", source.name, cand.token, why)

    # -- plausibility, assembly ---------------------------------------------------------

    def _plausibility(self) -> None:
        seen: set[str] = set()
        for kind in (AssetKind.PHOTO, AssetKind.AUDIO):
            for source in self.registry.asset_sources(kind):
                if source.name in seen or not isinstance(source, _FlagsSpecies):
                    continue
                seen.add(source.name)
                for f in source.flagged():
                    self.report.plausibility_flags.append(
                        PlausibilityFlag(
                            f.species_id,
                            source.name,
                            f"{f.na_count} North American records vs {f.expected} expected ({f.ratio:.2%})",
                        )
                    )

    def _assemble(self) -> SpeciesBuild:
        entries: dict[str, SpeciesEntry] = {}
        provenance: dict[str, ProvenanceEntry] = {}
        media: dict[str, bytes] = {}
        reused_media: set[str] = set()
        report = self.report
        unfinished: list[str] = []

        for sid in self.ids:
            roles = self.roles[sid]
            # A pin that failed leaves the previous entry standing.
            for kind, role in roles.items():
                if not role.done and role.fallback is not None:
                    role.ref = reused_media_ref(kind, role.fallback, self.rows[sid])
                    role.prov = reused_provenance(role.fallback, self.rows[sid])
                    role.reused = True
                    self.owners[role.fallback.ref.file] = (sid, kind)
            row = self.rows[sid]
            refs: dict[str, list[MediaRef]] = {"photo": [], "audio": []}
            for kind, role in roles.items():
                if role.ref is None or role.prov is None:
                    continue
                refs[kind].append(role.ref)
                provenance[role.ref.file] = role.prov
                if role.reused:
                    reused_media.add(role.ref.file)
                elif role.data is not None:
                    media[role.ref.file] = role.data
                source = role.prov.record.source
                if kind == "photo":
                    report.photos += 1
                    report.photos_by_source[source] = report.photos_by_source.get(source, 0) + 1
                else:
                    report.audio += 1
                    report.audio_by_source[source] = report.audio_by_source.get(source, 0) + 1
                if role.pin is not None and (source, role.prov.token) == (role.pin.source, role.pin.token):
                    report.pinned_used += 1
            entries[sid] = SpeciesEntry(row.common_name, row.sci_name, refs["photo"], refs["audio"], row.ioc_name)

            if any((r.incomplete and not r.done) or r.pin_failed for r in roles.values()):
                unfinished.append(sid)
            if not roles["photo"].done and not roles["photo"].incomplete and not roles["photo"].pin_failed:
                report.species_without_photo.append(sid)
            if not roles["audio"].done and not roles["audio"].incomplete and not roles["audio"].pin_failed:
                report.species_without_audio.append(sid)

        report.built = sum(
            1 for sid in self.ids if any(not r.reused and not r.closed for r in self.roles[sid].values())
        )
        report.reused = len(self.ids) - report.built
        report.unfinished_species = unfinished
        report.species_total = len(self.ids)
        report.requests_made = self.calls
        if self.timed_out:
            report.notes.append(
                f"Time budget reached: {len(unfinished)} species are unfinished and keep whatever they had."
            )
        return SpeciesBuild(
            SpeciesFile(entries), ProvenanceFile(provenance), media, reused_media, report
        )


def _resolve_pin(source: AssetSource, token: str, species_id: str) -> Candidate:
    """`resolve_pin`, passing ``species_id`` when the source accepts it (Commons does)."""
    fn = cast(Any, source).resolve_pin
    try:
        accepts = "species_id" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        accepts = False
    return fn(token, species_id=species_id) if accepts else fn(token)


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise VerifyUnavailable("ffmpeg is not on PATH; it is needed to decode and cut audio")


def build_species(
    species: Iterable[str | SpeciesRow],
    *,
    table: SpeciesTable,
    registry: Registry,
    pins: Pins | None = None,
    previous: LoadedCatalog | None = None,
    analyzer: Analyzer | None = None,
    verify: bool = True,
    labels: Sequence[str] | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SpeciesBuild:
    """Choose a photo and a recording for each species.

    ``species`` are ids (or rows) from ``table``, in priority order: that is the order they
    are worked in, so a time budget cuts the tail. ``previous`` is the last published catalog
    (sticky, ADR 0014). ``analyzer`` scores audio (default: the real BirdNET model) and
    ``labels`` is BirdNET's label list, needed only for species whose ``birdnet_label`` is
    empty. ``verify=False`` builds no audio except from pins. ``deadline`` is a value of
    ``clock`` after which no new source call starts.

    Raises `VerifyUnavailable` when BirdNET or ffmpeg is missing (the caller stops the build).
    Everything else that goes wrong is in ``result.report``: source failures, pin errors,
    rejections, unfinished species.
    """
    return _Builder(
        species,
        table=table,
        registry=registry,
        pins=pins,
        previous=previous,
        analyzer=analyzer,
        verify=verify,
        labels=labels,
        deadline=deadline,
        clock=clock,
    ).run()


# ---------------------------------------------------------------------------------------
# The full build
# ---------------------------------------------------------------------------------------


@dataclass
class BuildOptions:
    """Everything `run_build` needs besides its collaborators."""

    out: Path
    regions: Sequence[Region]
    gadm_version: str
    eod_version: str
    catalog_version: str
    top_n: int = TOP_N
    max_species: int | None = None
    previous: LoadedCatalog | None = None
    pins: Pins = field(default_factory=lambda: Pins({}))
    allow_shrink: bool = False
    refresh_species: bool = False  # rebuild region lists even when the EOD version is unchanged
    verify: bool = True
    time_budget_minutes: float | None = None
    base_url: str = DEFAULT_BASE_URL


@dataclass
class BuildResult:
    report: BuildReport
    validation: ValidationResult | None = None
    lists: SpeciesListsResult | None = None
    catalog: LoadedCatalog | None = None
    site_dir: Path | None = None
    errors: list[str] = field(default_factory=list)  # reasons the run must exit non-zero

    @property
    def ok(self) -> bool:
        return not self.errors and (self.validation is None or self.validation.ok) and not self.report.pin_errors


RegionLists = dict[str, list[tuple[str, tuple[int, ...]]]]


@dataclass
class _SpeciesHalf:
    """What the species half hands the rest of `run_build`."""

    region_lists: RegionLists = field(default_factory=dict)
    lists: SpeciesListsResult | None = None  # None when the previous catalog's lists were reused
    notes: list[str] = field(default_factory=list)
    failures: list[SourceFailure] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def expected(self) -> dict[str, int] | None:
        """Species totals for the plausibility check; None when the lists were reused."""
        return dict(self.lists.species_totals) if self.lists is not None else None


def _species_half(
    options: BuildOptions, species_source: SpeciesSource, species_table: SpeciesTable
) -> _SpeciesHalf:
    """Each region's ranked species list: the previous catalog's when the EOD version is
    unchanged, else fresh from ``species_source``, falling back region by region to the
    previous list when a region fails."""
    previous = options.previous
    slugs = [r.slug for r in options.regions]
    half = _SpeciesHalf()
    if (
        previous is not None
        and not options.refresh_species
        and previous.manifest.eod_version == options.eod_version
        and all(slug in previous.regions for slug in slugs)
    ):
        half.region_lists = {slug: list(previous.regions[slug].species) for slug in slugs}
        half.notes.append(
            f"Species half reused from the previous catalog (EOD {options.eod_version} is unchanged); "
            "the iNaturalist plausibility check was skipped."
        )
        return half

    lists = build_species_lists(
        species_source, options.regions, species_table, top_n=options.top_n, dataset_version=options.eod_version
    )
    half.lists = lists
    for slug in slugs:
        if slug in lists.region_files:
            half.region_lists[slug] = [(sid, tuple(monthly)) for sid, monthly in lists.region_files[slug]["species"]]
        elif previous is not None and slug in previous.regions:
            half.region_lists[slug] = list(previous.regions[slug].species)
            half.failures.append(
                SourceFailure("gbif", None, f"region {slug}: {lists.failed.get(slug, 'failed')}; previous list kept")
            )
        else:
            half.errors.append(f"region {slug} failed and there is no previous list: {lists.failed.get(slug)}")
            half.failures.append(SourceFailure("gbif", None, f"region {slug}: {lists.failed.get(slug)}"))
    if lists.minted:
        half.notes.append(
            f"{len(lists.minted)} species minted this run: "
            + ", ".join(r.id for r in lists.minted[:20])
            + (" ..." if len(lists.minted) > 20 else "")
        )
    return half


def _with_previous_names(species_table: SpeciesTable, previous: LoadedCatalog, order: Sequence[str]) -> SpeciesTable:
    """A reused species half never mints, so a species minted by an earlier run and not yet
    committed to species.csv is missing from the table. Its names are in the previous catalog."""
    stubs = [
        SpeciesRow(sid, previous.species[sid].sci, previous.species[sid].name, ioc_name=previous.species[sid].ioc_name)
        for sid in order
        if sid not in species_table and sid in previous.species
    ]
    return SpeciesTable([*species_table.all_rows(), *stubs]) if stubs else species_table


def _stage_media(stage: Path, built: SpeciesBuild, previous: LoadedCatalog | None) -> None:
    """A fresh ``stage`` directory holding every media file the new catalog uses."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name, data in built.media.items():
        written = write_media(stage, data, Path(name).suffix.lstrip("."))
        assert written == name, (written, name)
    for name in sorted(built.reused_media):
        assert previous is not None
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(previous.media_path(name), target)


def _manifest_template(options: BuildOptions, region_lists: RegionLists) -> Manifest:
    """The manifest before `write_catalog` fills in the hashed file names and sizes."""
    return Manifest(
        catalog_version=options.catalog_version,
        base_url=options.base_url,
        gadm_version=options.gadm_version,
        species_file="species.00000000.json",
        regions=[
            RegionRef(r.slug, r.name, r.country, "regions/x.00000000.json", 0)
            for r in options.regions
            if r.slug in region_lists
        ],
        dataset_credits=dataset_credits(),
        total_bytes=0,
        eod_version=options.eod_version,
    )


def _replace_site(
    out: Path, stage: Path, validation: ValidationResult, previous: LoadedCatalog | None, report: BuildReport
) -> str:
    """Move ``stage`` to ``out/site`` and return the directory's name.

    If validation failed and the previous catalog *is* out/site, keep it and leave the
    rejected build beside it, in out/site-rejected.
    """
    site_name = "site"
    if not validation.ok and previous is not None and _same_dir(previous.root, out / "site"):
        site_name = "site-rejected"
        report.notes.append(
            f"Validation failed and the previous catalog is out/site, so the new build is in out/{site_name}/."
        )
    final = out / site_name
    if final.exists():
        shutil.rmtree(final)
    stage.rename(final)
    return site_name


def run_build(
    options: BuildOptions,
    *,
    species_source: SpeciesSource,
    species_table: SpeciesTable,
    registry_factory: Callable[[Mapping[str, int] | None], Registry],
    analyzer: Analyzer | None = None,
    labels: Sequence[str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> BuildResult:
    """Species half, media, assembly, validation and the human-readable outputs.

    Writes ``options.out/site/`` (the catalog), ``build-report.md`` and ``contact-sheet.html``.
    ``registry_factory`` gets the expected counts (or None when the species half is reused)
    and returns the asset sources. Raises `VerifyUnavailable` when audio can't be verified.
    """
    started = clock()
    deadline = started + options.time_budget_minutes * 60 if options.time_budget_minutes is not None else None
    out = options.out
    previous = options.previous
    result = BuildResult(report=BuildReport(catalog_version=options.catalog_version))

    # -- species half --------------------------------------------------------------------
    half = _species_half(options, species_source, species_table)
    result.lists = half.lists
    result.errors.extend(half.errors)
    region_lists = half.region_lists
    built_slugs = [r.slug for r in options.regions if r.slug in region_lists]
    if not built_slugs:
        result.errors.append("no region has a species list to build from")
        result.report.source_failures = half.failures
        result.report.notes = half.notes
        _write_report(out, result, None)
        return result

    # -- species set -------------------------------------------------------------------
    order = overall_order({slug: [sid for sid, _ in region_lists[slug]] for slug in built_slugs})
    if options.max_species is not None:
        order = order[: options.max_species]
        half.notes.append(
            f"--max-species {options.max_species}: only the {len(order)} most widespread species were built."
        )
    keep = set(order)
    region_files = [
        RegionFile(slug, [(sid, m) for sid, m in region_lists[slug] if sid in keep]) for slug in built_slugs
    ]

    # -- media ---------------------------------------------------------------------------
    registry = registry_factory(half.expected)
    reused = half.lists is None
    build_table = _with_previous_names(species_table, previous, order) if reused and previous else species_table
    built = build_species(
        order,
        table=build_table,
        registry=registry,
        pins=options.pins,
        previous=previous,
        analyzer=analyzer,
        verify=options.verify,
        labels=labels,
        deadline=deadline,
        clock=clock,
    )
    report = built.report
    report.catalog_version = options.catalog_version
    report.source_failures = [*half.failures, *report.source_failures]
    report.notes = [*half.notes, *report.notes]
    if half.lists is not None:
        report.re_resolved = list(half.lists.re_resolved)
        report.dropped_minorities = list(half.lists.dropped_minorities)
    result.report = report

    # -- write ---------------------------------------------------------------------------
    stage = out / "site.new"
    _stage_media(stage, built, previous)
    write_catalog(stage, _manifest_template(options, region_lists), region_files, built.species, built.provenance)
    staged = load_catalog(stage)
    validation = validate_catalog(
        staged, previous, allow_shrink=options.allow_shrink, pins=options.pins.for_validation()
    )
    (stage / "credits.html").write_text(render_credits_page(staged), encoding="utf-8")

    site_name = _replace_site(out, stage, validation, previous, report)
    final = out / site_name
    catalog = load_catalog(final)
    (out / "contact-sheet.html").write_text(render_contact_sheet(catalog, f"{site_name}/"), encoding="utf-8")
    report.elapsed_s = clock() - started
    result.catalog = catalog
    result.validation = validation
    result.site_dir = final
    _write_report(out, result, validation)
    return result


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _write_report(out: Path, result: BuildResult, validation: ValidationResult | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "build-report.md").write_text(render_build_report(result.report, validation), encoding="utf-8")

