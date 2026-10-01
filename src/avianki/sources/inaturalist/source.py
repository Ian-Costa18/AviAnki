"""`INaturalistSource`: research-grade bird photos and recordings from iNaturalist (ADR 0005, 0011).

The photo fallback and audio source. Everything is keyless, against API v1, through the injected
`HttpClient` (1 request/s, 10,000 requests/day; the client enforces `LIMITS`).

**Species identity.** iNaturalist renames and splits taxa on its own schedule, so a species is
mapped by scientific name and checked twice (ADR 0008): the name must match exactly or through an
iNaturalist synonym, in Aves; and, when the caller supplies expected counts, the taxon's North
American research-grade count must be at least `PLAUSIBILITY_MIN_RATIO` of the expected count
(the ADR's 5% was measured to be far too high; see the constant).
A taxon that fails either check gets no candidates. The mapping is public (`resolve_taxa`) so the
pipeline can write ``inat_taxon_id`` back to ``species.csv``; the source never touches disk.

**Pin tokens** are ``P<observation id>:<photo id>`` and ``S<observation id>:<sound id>``.
iNaturalist has no photo or sound endpoint, and ``photo_id`` is ignored by the observations
search, so an observation id is the only handle that can be looked up.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from avianki.core.http import HttpClient, Limits, SourceError
from avianki.core.licences import AssetRecord, licence_url
from avianki.sources.contract import AssetKind, AssetSource, Candidate, FetchedAsset, SpeciesId
from avianki.sources.inaturalist import parse
from avianki.taxonomy.species import SpeciesRow, SpeciesTable

log = logging.getLogger("bird_deck")

API = "https://api.inaturalist.org/v1"
LIMITS = Limits(requests_per_second=1, max_concurrency=1, daily_request_budget=10_000, needs_secret=None)

NORTH_AMERICA_PLACES = "1,6712"  # place ids: United States, Canada (verified against /v1/places)
TAXA_PAGE = 30  # exact names can rank below many fuzzy matches: Bubo bubo, Puffinus puffinus fell outside the first 5
AVES_TAXON_ID = 3  # restricts /taxa to birds; without it a short name like "Alle alle" is buried under fuzzy matches

# ADR 0008 says 5%. Measured against real data that is wrong by two orders of magnitude: iNaturalist
# research-grade birds in the US and Canada are a small, different sample from EOD's checklist
# records, and over the first 30 species (28 with EOD North America records) the median ratio was
# 2.8%, so 5% would drop 18 of 28 correct mappings. The one real mapping error found,
# Numenius phaeopus (iNaturalist's Eurasian-only taxon against EOD's lumped Whimbrel), scores 0.000014
# and the lowest correct mapping 0.0012, so 0.0002 separates them with margin on both sides. The
# expected count must be EOD's North America (continent) count for the species: the ratio is only
# meaningful against the same geography. Pass ``min_ratio=`` to override.
PLAUSIBILITY_MIN_RATIO = 0.0002
TERMS_VERSION = "2023-07-11"  # iNaturalist Terms of Use revision the licence research read
COUNT_BATCH = 50  # taxon ids per species_counts request

_PIN = re.compile(r"^(?P<kind>[PS])(?P<obs>\d+):(?P<asset>\d+)$")


@dataclass(frozen=True)
class PlausibilityFlag:
    """A taxon whose North American count is implausibly low for the species it was mapped to."""

    species_id: SpeciesId
    taxon_id: int
    na_count: int
    expected: int

    @property
    def ratio(self) -> float:
        return self.na_count / self.expected if self.expected else float("inf")


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((v for k, v in headers.items() if k.lower() == name), "")


class INaturalistSource(AssetSource):
    """iNaturalist photos and sounds.

    ``expected_counts`` maps species ids to EOD's North America record count for the species, which
    the plausibility check compares this source's North America research-grade count against
    (see `PLAUSIBILITY_MIN_RATIO` for why the threshold is not the ADR's 5%). A species missing
    from it is not checked. ``min_ratio`` overrides the threshold.

    ``today`` supplies the ISO date written to ``retrieved_at``. It is injected so this module
    reads no clock of its own in tests; the default is the UTC date.
    """

    name = "inaturalist"
    supplies = frozenset({AssetKind.PHOTO, AssetKind.AUDIO})
    republishable = True
    limits = LIMITS

    def __init__(
        self,
        client: HttpClient,
        species: SpeciesTable,
        *,
        expected_counts: Mapping[SpeciesId, int] | None = None,
        min_ratio: float = PLAUSIBILITY_MIN_RATIO,
        today: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._species = species
        self._expected = dict(expected_counts or {})
        self._min_ratio = min_ratio
        self._today = today or client.today
        self._matches: dict[SpeciesId, parse.TaxonMatch | None] = {}
        self._how: dict[SpeciesId, str] = {}
        self._flagged: dict[SpeciesId, PlausibilityFlag] = {}
        self._checked: set[SpeciesId] = set()
        self._ratios: dict[SpeciesId, float] = {}
        self._table_ids: dict[int, SpeciesId] | None = None
        self._table_names: dict[str, SpeciesId] | None = None

    # ── taxon resolution and plausibility ────────────────────────────────────

    def resolve_taxa(self, species_ids: Iterable[SpeciesId]) -> dict[SpeciesId, int]:
        """iNaturalist taxon id for each species that maps to one, plausibly and unambiguously.

        Species that don't resolve, resolve ambiguously, or fail the plausibility check are
        omitted (absence, logged). Results are cached in-process. Raises `SourceError` if a
        lookup fails.
        """
        wanted = list(dict.fromkeys(species_ids))
        for sid in wanted:
            if sid not in self._matches:
                self._matches[sid] = self._resolve(sid)
        self._check_plausibility([s for s in wanted if self._matches[s] is not None])
        dropped = self._conflicts()
        return {
            sid: match.taxon_id
            for sid in wanted
            if (match := self._matches[sid]) is not None and sid not in self._flagged and sid not in dropped
        }

    def resolution_methods(self) -> dict[SpeciesId, str]:
        """How each species so far was mapped: ``table``, ``exact``, ``synonym`` or ``none``."""
        return dict(self._how)

    def flagged(self) -> list[PlausibilityFlag]:
        """Taxa the plausibility check rejected so far, for the build report."""
        return sorted(self._flagged.values(), key=lambda f: f.species_id)

    def na_ratios(self) -> dict[SpeciesId, float]:
        """iNaturalist NA research-grade count / expected count, for every species checked so far."""
        return dict(self._ratios)

    def _row(self, species_id: SpeciesId) -> SpeciesRow:
        try:
            return self._species.get(species_id)
        except KeyError:
            raise ValueError(f"unknown species id {species_id!r}") from None

    def _resolve(self, species_id: SpeciesId) -> parse.TaxonMatch | None:
        row = self._row(species_id)
        if row.inat_taxon_id is not None:
            # Written back by an earlier run after it passed these same checks.
            self._how[species_id] = "table"
            return parse.TaxonMatch(row.inat_taxon_id, row.sci_name, "exact")
        payload = self._get("/taxa", {"q": row.sci_name, "taxon_id": AVES_TAXON_ID, "rank": "species",
                                      "is_active": "true", "per_page": TAXA_PAGE, "locale": "en"})
        match = parse.pick_taxon(row.sci_name, payload)
        if match is None:
            log.info("inaturalist: no unambiguous active bird taxon for %s (%s)", row.sci_name, species_id)
            self._how[species_id] = "none"
        else:
            self._how[species_id] = match.how
            if match.how == "synonym":
                log.info("inaturalist: %s is %s (%d) on iNaturalist", row.sci_name, match.name, match.taxon_id)
        return match

    def _conflicts(self) -> set[SpeciesId]:
        """Species that share a taxon with another. An exact-name claim beats synonym claims."""
        claims: dict[int, list[SpeciesId]] = {}
        for sid, match in self._matches.items():
            if match is not None and sid not in self._flagged:
                claims.setdefault(match.taxon_id, []).append(sid)
        dropped: set[SpeciesId] = set()
        for taxon_id, sids in claims.items():
            if len(sids) < 2:
                continue
            exact = [s for s in sids if (m := self._matches[s]) is not None and m.how == "exact"]
            keep = set(exact) if len(exact) == 1 else set()
            dropped |= set(sids) - keep
            log.warning("inaturalist: taxon %d claimed by %s; kept %s", taxon_id, sorted(sids), sorted(keep) or "none")
        return dropped

    def _check_plausibility(self, species_ids: list[SpeciesId]) -> None:
        todo = [s for s in species_ids if s in self._expected and s not in self._checked]
        for start in range(0, len(todo), COUNT_BATCH):
            batch = todo[start:start + COUNT_BATCH]
            ids = sorted({m.taxon_id for s in batch if (m := self._matches[s]) is not None})
            payload = self._get("/observations/species_counts", {
                "taxon_id": ",".join(map(str, ids)), "place_id": NORTH_AMERICA_PLACES, "quality_grade": "research",
                "rank": "species", "per_page": 500, "locale": "en"})
            counts = parse.species_counts(payload)
            for sid in batch:
                match = self._matches[sid]
                assert match is not None
                self._checked.add(sid)
                na, expected = counts.get(match.taxon_id, 0), self._expected[sid]
                self._ratios[sid] = na / expected if expected > 0 else float("inf")
                if not parse.is_plausible(na, expected, self._min_ratio):
                    flag = PlausibilityFlag(sid, match.taxon_id, na, expected)
                    self._flagged[sid] = flag
                    log.warning("inaturalist: %s -> taxon %d (%s) looks like a wrong mapping: %d research-grade "
                                "observations in North America against %d expected (%.4f < %.4f)",
                                sid, match.taxon_id, match.name, na, expected, flag.ratio, self._min_ratio)

    # ── contract ─────────────────────────────────────────────────────────────

    def candidates(self, species: list[SpeciesId], kind: AssetKind, limit: int) -> dict[SpeciesId, list[Candidate]]:
        if kind not in self.supplies:
            raise ValueError(f"inaturalist does not supply {kind.value}")
        taxa = self.resolve_taxa(species)
        out: dict[SpeciesId, list[Candidate]] = {sid: [] for sid in species}
        if limit < 1:
            return out
        for sid, taxon_id in taxa.items():
            out[sid] = self._species_candidates(sid, taxon_id, kind, limit)
        return out

    def _species_candidates(self, sid: SpeciesId, taxon_id: int, kind: AssetKind, limit: int) -> list[Candidate]:
        # Over-fetch: the gates below drop some, and only the first page is read.
        if kind is AssetKind.PHOTO:
            params: dict[str, Any] = {"photos": "true", "photo_license": ",".join(parse.ALLOWED_CODES),
                                      "per_page": min(200, max(10, limit * 3))}
        else:
            params = {"sounds": "true", "sound_license": ",".join(parse.ALLOWED_CODES),
                      "per_page": min(200, max(20, limit * 6))}
        params |= {"taxon_id": taxon_id, "quality_grade": "research", "captive": "false", "lrank": "species",
                   "hrank": "species", "order_by": "votes", "locale": "en"}
        found: list[parse.Found] = []
        for obs in parse.observations(self._get("/observations", params)):
            got = parse.photo_asset(obs, taxon_id) if kind is AssetKind.PHOTO else parse.sound_asset(obs, taxon_id)
            if isinstance(got, parse.Reject):
                log.debug("inaturalist: %s: observation %s rejected: %s", sid, obs["id"], got.reason)
            else:
                found.append(got)
        row = self._row(sid)
        built = (self._candidate(sid, row, f) for f in parse.ranked(found))
        return [c for c in built if c is not None][:limit]

    def fetch(self, candidate: Candidate) -> FetchedAsset:
        url = candidate.record.file_url
        resp = self._client.get(self.name, self.limits, url, cache=False)
        ctype = _header(resp.headers, "content-type").split(";")[0].strip().lower()
        allowed = parse.IMAGE_TYPES if candidate.kind is AssetKind.PHOTO else parse.AUDIO_TYPES
        if ctype not in allowed:
            raise SourceError(f"inaturalist: {url} is {ctype or 'of unknown type'}, expected {candidate.kind.value}")
        if not resp.content:
            raise SourceError(f"inaturalist: {url} returned an empty body")
        return FetchedAsset(candidate=candidate, data=resp.content, content_type=ctype, record=candidate.record)

    def resolve_pin(self, token: str) -> Candidate:
        """``P<observation>:<photo>`` or ``S<observation>:<sound>`` back to a candidate.

        Every gate but the identification-agreement floor applies (ADR 0011), and the licence
        gate is never skipped. Raises `SourceError` if the token is malformed, the observation
        or its asset is gone or no longer eligible, or its taxon isn't one of our species.
        """
        m = _PIN.match(token.strip())
        if m is None:
            raise SourceError(f"inaturalist: malformed pin token {token!r}; expected P<obs>:<photo> or S<obs>:<sound>")
        obs_id, asset_id = int(m["obs"]), int(m["asset"])
        payload = self._get(f"/observations/{obs_id}", {"locale": "en"})
        matches = [o for o in parse.observations(payload) if o["id"] == obs_id]
        if not matches:
            raise SourceError(f"inaturalist: pin {token}: observation {obs_id} no longer resolves")
        obs = matches[0]
        taxon = obs["taxon"]
        taxon_id, taxon_name = taxon.get("id"), taxon.get("name")
        sid = self._species_for_taxon(taxon_id, taxon_name)
        if sid is None:
            raise SourceError(f"inaturalist: pin {token}: taxon {taxon_id} ({taxon_name}) is not a known species")
        if m["kind"] == "P":
            got = parse.photo_asset(obs, taxon_id, min_agreements=None, photo_id=asset_id)
        else:
            got = parse.sound_asset(obs, taxon_id, sound_id=asset_id)
        if isinstance(got, parse.Reject):
            raise SourceError(f"inaturalist: pin {token} is no longer eligible: {got.reason}")
        candidate = self._candidate(sid, self._row(sid), got)
        if candidate is None:
            raise SourceError(f"inaturalist: pin {token} has an incomplete credit record")
        return candidate

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get(self, path: str, params: Mapping[str, Any]) -> Any:
        return self._client.get_json(self.name, self.limits, f"{API}{path}", params)

    def _species_for_taxon(self, taxon_id: Any, taxon_name: Any) -> SpeciesId | None:
        """The species a taxon belongs to: an earlier mapping, the table's ``inat_taxon_id``, or its exact name."""
        if not isinstance(taxon_id, int):
            return None
        for sid, match in self._matches.items():
            if match is not None and match.taxon_id == taxon_id and sid not in self._flagged:
                return sid
        if self._table_ids is None or self._table_names is None:
            live = list(self._species)
            self._table_ids = {r.inat_taxon_id: r.id for r in live if r.inat_taxon_id is not None}
            self._table_names = {parse.norm_name(r.sci_name): r.id for r in live}
        if taxon_id in self._table_ids:
            return self._table_ids[taxon_id]
        if isinstance(taxon_name, str):
            return self._table_names.get(parse.norm_name(taxon_name))
        return None

    def _candidate(self, sid: SpeciesId, row: SpeciesRow, f: parse.Found) -> Candidate | None:
        # iNaturalist photos and sounds have no title of their own, and the version of an
        # unversioned cc-by is assumed, which makes the title mandatory (ADR 0012; BY 3.0
        # section 4(c)(ii), "the title of the Work if supplied"). The Work is named the way
        # iNaturalist names its observation page: "Common name (Scientific name)".
        record = AssetRecord(
            source=self.name,
            source_asset_id=str(f.asset_id),
            source_url=f.source_url,
            file_url=f.file_url,
            licence_id=f.licence_id,
            licence_url=licence_url(f.licence_id),
            creator=f.creator,
            creator_url=f.creator_url,
            attribution_text=f.attribution_text,
            title=f"{row.common_name} ({row.sci_name})",
            retrieved_at=self._today(),
            source_terms_version=TERMS_VERSION,
            licence_version_assumed=f.licence_version_assumed,
        )
        missing = record.missing_required_fields()
        if missing:
            log.warning("inaturalist: %s: %s %d has an incomplete credit (missing %s); not offered",
                        sid, f.kind.value, f.asset_id, missing)
            return None
        prefix = "P" if f.kind is AssetKind.PHOTO else "S"
        return Candidate(
            species_id=sid,
            kind=f.kind,
            token=f"{prefix}{f.observation_id}:{f.asset_id}",
            record=record,
            width=f.width,
            height=f.height,
            agreements=f.agreements,
        )
