"""`EbirdSpeciesSource`: a region's species list from the eBird API (ADR 0017).

This is the ``avianki --ebird CODE`` source. It is ``republishable = False``: eBird's terms
don't allow redistributing what comes out of it, so it can never be registered for a catalog
build (`Registry.register` refuses it) and a deck built from it says so.

The eBird list carries no frequency data, so ``monthly`` is all zeros ("no monthly data") and
``rank`` is the species' place in eBird's own order (taxonomic, as ``product/spplist`` returns
it). ``count`` is 0. The API key is handed in by the caller (sources read no environment) and
travels in the ``X-eBirdApiToken`` header, which `HttpClient` never caches or logs.
"""

from __future__ import annotations

import logging
import re

from avianki.core.http import HttpClient, Limits, SourceError
from avianki.sources.contract import Region, RegionId, SpeciesRecord, SpeciesSource
from avianki.sources.ebird import parse

log = logging.getLogger("bird_deck")

API = "https://api.ebird.org/v2"
TAXONOMY_BATCH = 200  # species codes per taxonomy request (keeps the URL short)
SECRET = "EBIRD_API_KEY"

# eBird asks for considerate use and publishes no hard limit; a deck needs a handful of calls.
LIMITS = Limits(requests_per_second=2, max_concurrency=1, daily_request_budget=None, needs_secret=SECRET)

# Country (US), subnational1 (US-MA) or subnational2 (US-MA-017); numeric parts are allowed.
_REGION_CODE = re.compile(r"^[A-Z]{2,3}(?:-[A-Z0-9]{1,3}){0,2}$")
_NO_MONTHLY = (0,) * 12


def is_region_code(text: str) -> bool:
    """Whether ``text`` looks like an eBird region code (upper case, e.g. ``US-MA-017``)."""
    return _REGION_CODE.match(text) is not None


class EbirdSpeciesSource(SpeciesSource):
    name = "ebird"
    republishable = False
    limits = LIMITS

    def __init__(self, client: HttpClient, api_key: str) -> None:
        if not api_key:
            raise ValueError(f"an eBird API key is required (the {SECRET} variable)")
        self._client = client
        self._headers = {"X-eBirdApiToken": api_key}

    def regions(self) -> list[Region]:
        """Empty: eBird's regions are open-ended, so `species_for` takes any eBird region code."""
        return []

    def species_for(self, region: RegionId) -> list[SpeciesRecord]:
        """Every species eBird has recorded in ``region`` (an eBird region code), in eBird's order.

        Non-species taxa (slashes, hybrids and the like) are left out. An unknown region is a
        `SourceError` (eBird answers 4xx); a region with no species is ``[]``.
        """
        code = region.strip().upper()
        if not is_region_code(code):
            raise ValueError(f"not an eBird region code: {region!r}")
        payload = self._client.get_json(
            self.name, self.limits, f"{API}/product/spplist/{code}", headers=self._headers
        )
        codes = parse.species_codes(payload, code)
        log.info("eBird: %d species recorded in %s", len(codes), code)

        rows: dict[str, parse.TaxonRow] = {}
        for i in range(0, len(codes), TAXONOMY_BATCH):
            batch = codes[i : i + TAXONOMY_BATCH]
            answer = self._client.get_json(
                self.name,
                self.limits,
                f"{API}/ref/taxonomy/ebird",
                {"species": ",".join(batch), "fmt": "json"},
                headers=self._headers,
            )
            rows.update(parse.taxonomy_rows(answer))

        if codes and not rows:
            raise SourceError(f"eBird's taxonomy returned no rows for the {len(codes)} species listed for {code}")

        records: list[SpeciesRecord] = []
        for species_code in codes:
            row = rows.get(species_code)
            if row is None:  # a stray code (list and taxonomy versions differ); the rest are still good
                log.warning("eBird: %s is listed for %s but not in eBird's taxonomy; skipped", species_code, code)
                continue
            if not parse.is_species(row):
                log.debug("eBird: skipping %s (%s), not a species", row.code, row.category)
                continue
            records.append(
                SpeciesRecord(
                    species_id=None,
                    sci_name=row.sci_name,
                    common_name=row.common_name,
                    source_key=row.code,
                    rank=len(records) + 1,
                    monthly=_NO_MONTHLY,
                    count=0,
                )
            )
        return records
