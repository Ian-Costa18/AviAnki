"""`GbifSpeciesSource`: region species lists from the eBird Observation Dataset (ADR 0004, 0024).

Per region it makes 14 occurrence-search facet requests (annual species counts, the
region's records per month, and species counts for each month). Species are counted by
GBIF backbone key, but the backbone lumps taxa that IOC and eBird split, so each key is
named by the scientific names eBird itself gives its records (`verbatimScientificName`,
one worldwide facet request per key), resolved through the IOC World Bird List checklist
on GBIF. A key whose names resolve to several IOC species gets one more request per region.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from avianki.core.http import HttpClient, Limits, SourceError
from avianki.sources.contract import Region, RegionId, SpeciesRecord, SpeciesSource
from avianki.sources.gbif import parse
from avianki.taxonomy.regions import RegionTable

log = logging.getLogger("bird_deck")

API = "https://api.gbif.org/v1"
EOD_DATASET_KEY = "4fa7b334-ce0d-4e88-aaae-2e0c138d049e"  # doi:10.15468/aomfnb, CC BY 4.0
IOC_DATASET_KEY = "c696e5ee-9088-4d11-bdae-ab88daffab78"  # "IOC World Bird List, v"
IOC_PAGE = 1000
# Names eBird uses under one backbone key (a handful, even for the lumped ones); a facet that
# fills the limit raises rather than risk a missing name.
VERBATIM_LIMIT = 100
DROPPED_SHARE_REPORTED = 0.10  # a dropped minority over this share of a key's regional records is reported

# GBIF publishes no hard rate limit for its API and asks for considerate use. 2 req/s in
# series keeps a full 64-region run (~900 facet requests) under ten minutes, and there is
# no daily quota or key.
LIMITS = Limits(requests_per_second=2, max_concurrency=1, daily_request_budget=None, needs_secret=None)


@dataclass(frozen=True)
class NameFallback:
    """A backbone species the IOC checklist didn't match, and the names used instead."""

    source_key: str
    sci_name: str
    common_name: str
    common_name_from: str  # "gbif-ioc-vernacular" | "eod-record" | "gbif-backbone" | "sci-name"


@dataclass(frozen=True)
class ReResolved:
    """A backbone key that ADR 0024 names differently from the IOC checklist entry for that key."""

    source_key: str  # the backbone key
    region: str  # region slug
    old_sci_name: str  # what ADR 0004 (the backbone path) would have said
    old_common_name: str
    sci_name: str  # what eBird's own names for the records say
    common_name: str
    share: float  # of the key's records (in the region if it was split, else worldwide) under `sci_name`


@dataclass(frozen=True)
class DroppedMinority:
    """Records under a backbone key that went to another species than the one the key was given."""

    source_key: str
    region: str
    sci_name: str  # the species the key took
    common_name: str
    kept_share: float
    dropped: tuple[str, ...]  # scientific names of the species whose records were dropped


@dataclass(frozen=True)
class _Names:
    sci_name: str
    common_name: str
    gbif_key: int | None = None  # the species' own backbone key, when the names came from eBird's records


@dataclass(frozen=True)
class _Pick:
    """What one backbone key is called in one region."""

    names: _Names
    re_resolved: bool


# species (by scientific name) -> its names and its records under one backbone key
_Candidates = dict[str, tuple[_Names, int]]


class GbifSpeciesSource(SpeciesSource):
    name = "gbif"
    republishable = True
    limits = LIMITS

    def __init__(self, client: HttpClient, regions: RegionTable, *, facet_limit: int = 3000) -> None:
        self._client = client
        self._regions = regions
        self._facet_limit = facet_limit
        self._ioc: tuple[dict[int, parse.IocName], dict[str, parse.IocName]] | None = None
        # ADR 0004's answer per backbone key (never a region's choice) and the fallback it implies
        self._backbone: dict[int, tuple[_Names, NameFallback | None]] = {}
        self._worldwide: dict[int, _Candidates] = {}  # backbone key -> species eBird names under it, anywhere
        self._fallbacks: dict[int, NameFallback] = {}
        self._re_resolved: dict[tuple[int, str], ReResolved] = {}
        self._dropped: dict[tuple[int, str], DroppedMinority] = {}

    # ── contract ─────────────────────────────────────────────────────────────

    def regions(self) -> list[Region]:
        return [Region(r.slug, r.name, r.country, r.gadm_gid) for r in self._regions]

    def species_for(self, region: RegionId) -> list[SpeciesRecord]:
        row = self._regions.by_slug(region)
        gid = row.gadm_gid
        annual = self._facet(gid, "speciesKey", "SPECIES_KEY", self._facet_limit, f"{region} (annual)")
        if not annual:
            return []
        # 12 months fit in a limit of 13 without tripping the truncation check.
        totals = self._facet(gid, "month", "MONTH", 13, f"{region} (records per month)")
        by_month: dict[int, dict[int, int]] = {}  # species key -> month -> count
        for month in range(1, 13):
            counts = self._facet(gid, "speciesKey", "SPECIES_KEY", self._facet_limit, f"{region} (month {month})",
                                 month=month)
            for key, c in counts.items():
                if key in annual:
                    by_month.setdefault(key, {})[month] = c

        picks = {key: self._pick(key, region, gid) for key in annual}

        # Several backbone keys can resolve to one IOC species; merge them.
        groups: dict[str, list[int]] = {}
        for key in annual:
            groups.setdefault(picks[key].names.sci_name, []).append(key)

        merged: list[tuple[int, int, _Names, dict[int, int], str]] = []  # (count, primary key, names, monthly, id key)
        for sci, keys in groups.items():
            keys.sort(key=lambda k: (-annual[k], k))
            if len(keys) > 1:
                log.info("gbif: %s: backbone keys %s all resolve to %s; merged", region, keys, sci)
            monthly: dict[int, int] = {}
            for k in keys:
                for m, c in by_month.get(k, {}).items():
                    monthly[m] = monthly.get(m, 0) + c
            names = picks[keys[0]].names
            # A key that took another species' name is no longer that species' key: identify the
            # record by the species' own backbone key, or species.csv would map it back (ADR 0024).
            moved = any(picks[k].re_resolved for k in keys) and names.gbif_key is not None
            merged.append((sum(annual[k] for k in keys), keys[0], names, monthly,
                           str(names.gbif_key) if moved else str(keys[0])))

        merged.sort(key=lambda t: (-t[0], t[1]))
        records = []
        for rank, (count, key, names, monthly, source_key) in enumerate(merged, start=1):
            vector = parse.monthly_vector(monthly, totals, f"{region} species {key}")
            if not any(vector):
                log.warning("gbif: %s: %s (%d) has %d records but none with a month", region, names.sci_name, key, count)
            records.append(SpeciesRecord(
                species_id=None,
                sci_name=names.sci_name,
                common_name=names.common_name,
                source_key=source_key,
                rank=rank,
                monthly=vector,
                count=count,
            ))
        return records

    # ── extras for the build ─────────────────────────────────────────────────

    def dataset_version(self) -> str:
        """The EOD release this run would read; never served from the HTTP cache (ADR 0014)."""
        payload = self._client.get_json(self.name, self.limits, f"{API}/dataset/{EOD_DATASET_KEY}", cache=False)
        return parse.dataset_version(payload)

    def name_fallbacks(self) -> list[NameFallback]:
        """Species seen so far that the IOC checklist didn't match, by backbone key."""
        return [self._fallbacks[k] for k in sorted(self._fallbacks)]

    def re_resolved(self) -> list[ReResolved]:
        """Keys named differently from ADR 0004's answer, by backbone key then region."""
        return [self._re_resolved[k] for k in sorted(self._re_resolved)]

    def dropped_minorities(self) -> list[DroppedMinority]:
        """Regional records dropped from a split key, when they were over 10% of the key's records."""
        return [self._dropped[k] for k in sorted(self._dropped)]

    # ── requests ─────────────────────────────────────────────────────────────

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._client.get_json(self.name, self.limits, f"{API}{path}", params)

    def _facet(self, gid: str, facet: str, field: str, limit: int, what: str, **extra: Any) -> dict[int, int]:
        params = {"datasetKey": EOD_DATASET_KEY, "gadmGid": gid, "limit": 0, "facet": facet, "facetLimit": limit,
                  **extra}
        return parse.facet_counts(self._get("/occurrence/search", params), field, limit, what)

    def _ioc_map(self) -> tuple[dict[int, parse.IocName], dict[str, parse.IocName]]:
        if self._ioc is not None:
            return self._ioc
        by_nub: dict[int, parse.IocName] = {}
        seen = 0
        offset, expected, end = 0, None, False
        while not end:
            page = self._get("/species/search", {"datasetKey": IOC_DATASET_KEY, "rank": "SPECIES",
                                                "status": "ACCEPTED", "limit": IOC_PAGE, "offset": offset})
            entries, count, end = parse.ioc_entries(page)
            if expected is None:
                expected = count
            elif count != expected:
                raise SourceError(f"gbif: IOC checklist count changed while paging ({expected} -> {count})")
            n = len(page.get("results", []))
            seen += n
            if not end and n == 0:
                raise SourceError("gbif: IOC checklist paging stalled before endOfRecords")
            offset += n
            for nub, name in entries:
                if nub in by_nub and by_nub[nub] != name:
                    log.warning("gbif: IOC species %s and %s share backbone key %d; dropping both from the key map",
                                by_nub[nub].sci_name, name.sci_name, nub)
                    by_nub[nub] = parse.IocName("", None)
                else:
                    by_nub[nub] = name
        if not expected or seen != expected:
            raise SourceError(f"gbif: IOC checklist paging returned {seen} species, expected {expected}")
        by_nub = {k: v for k, v in by_nub.items() if v.sci_name}
        by_name: dict[str, parse.IocName] = {}
        for name in by_nub.values():
            by_name[name.sci_name.casefold()] = name
        log.info("gbif: IOC checklist: %d species with a backbone key", len(by_nub))
        self._ioc = (by_nub, by_name)
        return self._ioc

    # ── names: eBird's own (ADR 0024), else the backbone's IOC entry (ADR 0004) ─

    def _verbatim(self, key: int, gid: str | None, what: str) -> dict[str, int]:
        params: dict[str, Any] = {"datasetKey": EOD_DATASET_KEY, "speciesKey": key, "limit": 0,
                                  "facet": "verbatimScientificName", "facetLimit": VERBATIM_LIMIT}
        if gid is not None:
            params["gadmGid"] = gid
        return parse.verbatim_name_counts(self._get("/occurrence/search", params), VERBATIM_LIMIT, what)

    def _candidates(self, key: int, names: dict[str, int]) -> _Candidates:
        """The IOC species eBird's names resolve to, with their records.

        A name that isn't an IOC species (an old genus, ``sp.``, a hybrid) is the backbone's
        answer for the key.
        """
        _, by_name = self._ioc_map()
        backbone, _ = self._backbone_for(key)
        out: _Candidates = {}
        for name, count in names.items():
            hit = by_name.get(name)
            if hit is None or hit.sci_name == backbone.sci_name:
                resolved = backbone
            elif hit.common_name:
                resolved = _Names(hit.sci_name, hit.common_name, hit.nub_key)
            else:
                log.warning("gbif: IOC %s has no English name; using the scientific name", hit.sci_name)
                resolved = _Names(hit.sci_name, hit.sci_name, hit.nub_key)
            out[resolved.sci_name] = (resolved, out.get(resolved.sci_name, (resolved, 0))[1] + count)
        return out

    def _pick(self, key: int, region: RegionId, gid: str) -> _Pick:
        """The species this backbone key is called in this region."""
        if key not in self._worldwide:
            self._worldwide[key] = self._candidates(key, self._verbatim(key, None, f"species {key} (worldwide)"))
        candidates = self._worldwide[key]
        if len(candidates) == 1:
            ((names, _),) = candidates.values()
            share = 1.0
        else:
            # Split key: the region's own records decide. The other names' records are dropped here.
            candidates = self._candidates(key, self._verbatim(key, gid, f"species {key} in {region}"))
            total = sum(c for _, c in candidates.values())
            names, count = sorted(candidates.values(), key=lambda t: (-t[1], t[0].sci_name))[0]
            share = count / total
            log.info("gbif: %s: backbone key %d holds %d IOC species; took %s (%.0f%% of its records)",
                     region, key, len(candidates), names.sci_name, 100 * share)
            if 1 - share > DROPPED_SHARE_REPORTED:
                self._dropped[key, region] = DroppedMinority(
                    str(key), region, names.sci_name, names.common_name, share,
                    tuple(sorted(n.sci_name for n, _ in candidates.values() if n.sci_name != names.sci_name)),
                )

        old, fallback = self._backbone_for(key)
        if names.sci_name == old.sci_name:
            if fallback is not None:
                self._fallbacks[key] = fallback  # the backbone's answer is what's used, and it isn't IOC
            return _Pick(names, False)
        log.info("gbif: %s: backbone key %d is %s (%s), not %s (%s), by eBird's own names", region, key,
                 names.sci_name, names.common_name, old.sci_name, old.common_name)
        self._re_resolved[key, region] = ReResolved(
            str(key), region, old.sci_name, old.common_name, names.sci_name, names.common_name, share
        )
        return _Pick(names, True)

    # ── the backbone's own answer (ADR 0004): IOC checklist, else IOC vernacular, else the EOD record ─

    def _backbone_for(self, key: int) -> tuple[_Names, NameFallback | None]:
        if key not in self._backbone:
            self._backbone[key] = self._lookup_names(key)
        return self._backbone[key]

    def _lookup_names(self, key: int) -> tuple[_Names, NameFallback | None]:
        by_nub, by_name = self._ioc_map()
        if key in by_nub:
            return self._from_ioc(key, by_nub[key]), None
        # The backbone often keeps an older genus (Phalacrocorax auritus = IOC Nannopterum
        # auritum); match by name, then through the backbone's synonyms.
        usage = self._get(f"/species/{key}")
        canonical = " ".join(str(usage.get("canonicalName") or "").split()) if isinstance(usage, dict) else ""
        if not canonical:
            raise SourceError(f"gbif: backbone species {key} has no canonicalName")
        if canonical.casefold() in by_name:
            return self._from_ioc(key, by_name[canonical.casefold()]), None
        synonyms = parse.synonym_keys_and_names(self._get(f"/species/{key}/synonyms", {"limit": 100}))
        for syn_key, syn_name in synonyms:
            hit = by_nub.get(syn_key) or by_name.get(syn_name.casefold())
            if hit is not None:
                log.debug("gbif: backbone %s (%d) matched IOC %s via synonym", canonical, key, hit.sci_name)
                return self._from_ioc(key, hit), None

        common, how = self._fallback_common_name(key, usage)
        common = common or canonical
        log.warning("gbif: no IOC match for backbone species %d %s; using %r (%s)", key, canonical, common,
                    how or "sci-name")
        return _Names(canonical, common), NameFallback(str(key), canonical, common, how or "sci-name")

    def _from_ioc(self, key: int, name: parse.IocName) -> _Names:
        if name.common_name:
            return _Names(name.sci_name, name.common_name)
        common, how = self._fallback_common_name(key, None)
        log.warning("gbif: IOC %s has no English name; using %r (%s)", name.sci_name, common, how)
        return _Names(name.sci_name, common or name.sci_name)

    def _fallback_common_name(self, key: int, usage: Any) -> tuple[str | None, str | None]:
        ioc = parse.ioc_vernacular(self._get(f"/species/{key}/vernacularNames", {"limit": 1000}))
        if ioc:
            return ioc, "gbif-ioc-vernacular"
        occ = self._get("/occurrence/search", {"datasetKey": EOD_DATASET_KEY, "speciesKey": key, "limit": 1})
        try:
            results = occ["results"]
        except (KeyError, TypeError) as e:
            raise SourceError(f"gbif: malformed occurrence search for species {key}: {e!r}") from e
        if results and results[0].get("vernacularName"):
            return str(results[0]["vernacularName"]), "eod-record"
        if isinstance(usage, dict) and usage.get("vernacularName"):
            return str(usage["vernacularName"]), "gbif-backbone"
        return None, None
