"""Pure parsing and arithmetic for GBIF responses: facets, monthly vectors, IOC names.

Every "this doesn't look like what GBIF documents" case raises `SourceError`; nothing here
turns a malformed or truncated response into a shorter list.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from avianki.core.http import SourceError

CC_BY_4 = "creativecommons.org/licenses/by/4.0"


def facet_counts(payload: Any, field: str, facet_limit: int, what: str) -> dict[int, int]:
    """``{facet value: count}`` from an occurrence-search facet response.

    A facet returns at most ``facet_limit`` buckets, silently dropping the rest, so a
    response that fills the limit may be truncated and raises instead.
    """
    try:
        facets = payload["facets"]
        if not facets:
            return {}  # no records at all: GBIF omits the facet block
        (facet,) = [f for f in facets if f["field"] == field]
        buckets = facet["counts"]
        counts = {int(b["name"]): int(b["count"]) for b in buckets}
    except (KeyError, TypeError, ValueError) as e:
        raise SourceError(f"gbif: malformed {field} facet for {what}: {e!r}") from e
    if len(buckets) >= facet_limit:
        raise SourceError(
            f"gbif: {field} facet for {what} returned {len(buckets)} buckets, the facetLimit; "
            "the list may be truncated (raise facet_limit)"
        )
    if len(counts) != len(buckets) or any(c < 0 for c in counts.values()):
        raise SourceError(f"gbif: {field} facet for {what} has duplicate or negative buckets")
    return counts


def _round_half_up(x: Fraction) -> int:
    return int((x + Fraction(1, 2)).__floor__())


def monthly_vector(counts: Mapping[int, int], totals: Mapping[int, int], what: str) -> tuple[int, ...]:
    """12 values 0..255: the species' share of each month's records, peak month = 255.

    Dividing by the region's total records that month normalises for effort (more
    birders in May). 0 means not recorded that month; a recorded month is at least 1.
    """
    shares: list[Fraction] = []
    for month in range(1, 13):
        c = counts.get(month, 0)
        if c == 0:
            shares.append(Fraction(0))
            continue
        total = totals.get(month, 0)
        if total < c:
            raise SourceError(f"gbif: {what} has {c} records in month {month} but the region has {total}")
        shares.append(Fraction(c, total))
    peak = max(shares)
    if peak == 0:
        return (0,) * 12
    return tuple(0 if s == 0 else max(1, _round_half_up(255 * s / peak)) for s in shares)


@dataclass(frozen=True)
class IocName:
    sci_name: str
    common_name: str | None


def ioc_entries(payload: Any) -> tuple[list[tuple[int, IocName]], int, bool]:
    """Parse one page of the IOC checklist's species search: ``(nubKey, name)`` pairs,
    the total count, and endOfRecords. Entries without a backbone key are skipped."""
    try:
        out: list[tuple[int, IocName]] = []
        for r in payload["results"]:
            nub = r.get("nubKey")
            if nub is None:
                continue
            eng = [v["vernacularName"] for v in r.get("vernacularNames", []) if v.get("language") == "eng"]
            out.append((int(nub), IocName(" ".join(str(r["canonicalName"]).split()), eng[0] if eng else None)))
        return out, int(payload["count"]), bool(payload["endOfRecords"])
    except (KeyError, TypeError, ValueError) as e:
        raise SourceError(f"gbif: malformed IOC checklist page: {e!r}") from e


def ioc_vernacular(payload: Any) -> str | None:
    """The English name a species' vernacularNames list attributes to the IOC World Bird List."""
    try:
        for v in payload["results"]:
            if v.get("language") == "eng" and str(v.get("source", "")).startswith("IOC World Bird List"):
                return str(v["vernacularName"])
    except (KeyError, TypeError) as e:
        raise SourceError(f"gbif: malformed vernacularNames response: {e!r}") from e
    return None


def synonym_keys_and_names(payload: Any) -> Iterable[tuple[int, str]]:
    try:
        return [(int(r["key"]), str(r.get("canonicalName") or "")) for r in payload["results"]]
    except (KeyError, TypeError, ValueError) as e:
        raise SourceError(f"gbif: malformed synonyms response: {e!r}") from e


def dataset_version(payload: Any) -> str:
    """A string that changes whenever GBIF republishes the EOD.

    ``pubDate`` is the annual release; the DwC-A endpoint URL names the archive year
    (``2024-eBird-dwca-1.0.zip``); ``dwca.modified`` moves when GBIF re-ingests it.
    A metadata-only edit changes none of these, so it doesn't trigger a rebuild.
    """
    try:
        pub = str(payload["pubDate"])[:10]
        archives = sorted(e["url"].rsplit("/", 1)[-1] for e in payload["endpoints"] if e["type"] == "DWC_ARCHIVE")
        ingested = str(payload["dwca"]["modified"])
        licence = str(payload["license"])
    except (KeyError, TypeError, AttributeError) as e:
        raise SourceError(f"gbif: malformed EOD dataset metadata: {e!r}") from e
    if not archives:
        raise SourceError("gbif: EOD dataset metadata lists no DwC-A endpoint")
    if CC_BY_4 not in licence:
        raise SourceError(f"gbif: EOD licence is now {licence!r}, not CC BY 4.0; it can't feed the catalog")
    return f"{pub} {'+'.join(archives)} ingested {ingested}"
