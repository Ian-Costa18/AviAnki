"""Load ``data/regions.csv``: region slug <-> display name <-> GADM level-1 gid <-> eBird code."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from pathlib import Path

from avianki.core.text import fold
from avianki.taxonomy import DATA_DIR

REGIONS_CSV = DATA_DIR / "regions.csv"


@dataclass(frozen=True)
class RegionRow:
    slug: str
    name: str
    country: str
    gadm_gid: str
    gadm_version: str
    ebird_code: str


HEADER = tuple(f.name for f in fields(RegionRow))


class RegionTable:
    def __init__(self, rows: Iterable[RegionRow]) -> None:
        self._rows = sorted(rows, key=lambda r: r.slug)
        self._by_slug: dict[str, RegionRow] = {}
        self._by_name: dict[str, RegionRow] = {}
        self._by_ebird: dict[str, RegionRow] = {}
        seen_gids: set[str] = set()
        for row in self._rows:
            for index, key, label in (
                (self._by_slug, row.slug.lower(), "slug"),
                (self._by_name, fold(row.name), "name"),
                (self._by_ebird, row.ebird_code.upper(), "ebird_code"),
            ):
                if key in index:
                    raise ValueError(f"duplicate region {label} {key!r}")
                index[key] = row
            if row.gadm_gid in seen_gids:
                raise ValueError(f"duplicate region gadm_gid {row.gadm_gid!r}")
            seen_gids.add(row.gadm_gid)

    def __iter__(self) -> Iterator[RegionRow]:
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def gadm_version(self) -> str:
        versions = {r.gadm_version for r in self._rows}
        if len(versions) != 1:
            raise ValueError(f"regions must share exactly one gadm_version, found {sorted(versions)}")
        return versions.pop()

    def by_slug(self, slug: str) -> RegionRow:
        return self._lookup(self._by_slug, slug.strip().lower(), slug, "slug")

    def by_name(self, name: str) -> RegionRow:
        return self._lookup(self._by_name, fold(name), name, "name")

    def by_ebird(self, code: str) -> RegionRow:
        return self._lookup(self._by_ebird, code.strip().upper(), code, "eBird code")

    def _lookup(self, index: dict[str, RegionRow], key: str, raw: str, label: str) -> RegionRow:
        try:
            return index[key]
        except KeyError:
            raise KeyError(
                f"unknown region {label} {raw!r}; the catalog covers {len(self)} regions "
                f"(e.g. {', '.join(r.slug for r in self._rows[:3])})"
            ) from None


def load_regions(path: Path = REGIONS_CSV) -> RegionTable:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = tuple(next(reader, ()))
        if header != HEADER:
            raise ValueError(f"{path}: expected header {','.join(HEADER)}, got {','.join(header)}")
        return RegionTable(RegionRow(*row) for row in reader if row)
