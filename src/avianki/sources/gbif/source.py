"""`GbifSpeciesSource`: region species lists from the eBird Observation Dataset (ADR 0004).

Per region it makes 14 occurrence-search facet requests (annual species counts, the
region's records per month, and species counts for each month). Names come from the IOC
World Bird List checklist on GBIF, fetched once per source and keyed by backbone key.
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
class _Names:
    sci_name: str
    common_name: str
    ioc_matched: bool


class GbifSpeciesSource(SpeciesSource):
    name = "gbif"
    republishable = True
    limits = LIMITS

    def __init__(self, client: HttpClient, regions: RegionTable, *, facet_limit: int = 3000) -> None:
        self._client = client
        self._regions = regions
        self._facet_limit = facet_limit
        self._ioc: tuple[dict[int, parse.IocName], dict[str, parse.IocName]] | None = None
        self._names: dict[int, _Names] = {}
        self._fallbacks: dict[int, NameFallback] = {}

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

        # Several backbone keys can resolve to one IOC species; merge them.
        groups: dict[str, list[int]] = {}
        for key in annual:
            groups.setdefault(self._resolve(key).sci_name, []).append(key)

        merged: list[tuple[int, int, _Names, dict[int, int]]] = []  # (count, primary key, names, monthly)
        for sci, keys in groups.items():
            keys.sort(key=lambda k: (-annual[k], k))
            if len(keys) > 1:
                log.info("gbif: %s: backbone keys %s all resolve to %s; merged", region, keys, sci)
            monthly: dict[int, int] = {}
            for k in keys:
                for m, c in by_month.get(k, {}).items():
                    monthly[m] = monthly.get(m, 0) + c
            merged.append((sum(annual[k] for k in keys), keys[0], self._resolve(keys[0]), monthly))

        merged.sort(key=lambda t: (-t[0], t[1]))
        records = []
        for rank, (count, key, names, monthly) in enumerate(merged, start=1):
            vector = parse.monthly_vector(monthly, totals, f"{region} species {key}")
            if not any(vector):
                log.warning("gbif: %s: %s (%d) has %d records but none with a month", region, names.sci_name, key, count)
            records.append(SpeciesRecord(
                species_id=None,
                sci_name=names.sci_name,
                common_name=names.common_name,
                source_key=str(key),
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

    # ── names (ADR 0004): IOC checklist, else IOC vernacular, else the EOD record ─

    def _resolve(self, key: int) -> _Names:
        if key not in self._names:
            self._names[key] = self._lookup_names(key)
        return self._names[key]

    def _lookup_names(self, key: int) -> _Names:
        by_nub, by_name = self._ioc_map()
        if key in by_nub:
            return self._from_ioc(key, by_nub[key])
        # The backbone often keeps an older genus (Phalacrocorax auritus = IOC Nannopterum
        # auritum); match by name, then through the backbone's synonyms.
        usage = self._get(f"/species/{key}")
        canonical = " ".join(str(usage.get("canonicalName") or "").split()) if isinstance(usage, dict) else ""
        if not canonical:
            raise SourceError(f"gbif: backbone species {key} has no canonicalName")
        if canonical.casefold() in by_name:
            return self._from_ioc(key, by_name[canonical.casefold()])
        synonyms = parse.synonym_keys_and_names(self._get(f"/species/{key}/synonyms", {"limit": 100}))
        for syn_key, syn_name in synonyms:
            hit = by_nub.get(syn_key) or by_name.get(syn_name.casefold())
            if hit is not None:
                log.debug("gbif: backbone %s (%d) matched IOC %s via synonym", canonical, key, hit.sci_name)
                return self._from_ioc(key, hit)

        common, how = self._fallback_common_name(key, usage)
        common = common or canonical
        log.warning("gbif: no IOC match for backbone species %d %s; using %r (%s)", key, canonical, common,
                    how or "sci-name")
        self._fallbacks[key] = NameFallback(str(key), canonical, common, how or "sci-name")
        return _Names(canonical, common, ioc_matched=False)

    def _from_ioc(self, key: int, name: parse.IocName) -> _Names:
        if name.common_name:
            return _Names(name.sci_name, name.common_name, ioc_matched=True)
        common, how = self._fallback_common_name(key, None)
        log.warning("gbif: IOC %s has no English name; using %r (%s)", name.sci_name, common, how)
        return _Names(name.sci_name, common or name.sci_name, ioc_matched=True)

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
