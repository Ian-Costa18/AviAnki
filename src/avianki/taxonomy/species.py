"""Load, mint and save ``data/species.csv``: minted species ids and each source's native key (ADR 0008).

An id is the IOC scientific name as a slug at the time it was minted and never changes.
A lumped (retired) id stays as an alias row whose ``alias_of`` names its successor.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from pathlib import Path
from typing import NamedTuple

from avianki.core.text import strip_accents
from avianki.taxonomy import DATA_DIR

SPECIES_CSV = DATA_DIR / "species.csv"

_ID_RE = re.compile(r"[a-z]+(?:-[a-z]+)*")


@dataclass(frozen=True)
class SpeciesRow:
    id: str
    sci_name: str
    common_name: str
    gbif_key: int | None = None
    inat_taxon_id: int | None = None
    wikipedia_title: str | None = None
    ebird_code: str | None = None
    birdnet_label: str | None = None
    alias_of: str | None = None
    # The IOC English name, only where it is a genuinely different name for the same bird
    # from common_name (eBird's); empty everywhere else (ADR 0027). Last column.
    ioc_name: str = ""

    @property
    def is_alias(self) -> bool:
        return self.alias_of is not None


HEADER = tuple(f.name for f in fields(SpeciesRow))


class Minted(NamedTuple):
    row: SpeciesRow
    created: bool


def _normalise_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def mint_id(sci_name: str) -> str:
    """Slug an IOC scientific name: ``"Cardinalis cardinalis"`` -> ``"cardinalis-cardinalis"``."""
    if "×" in sci_name:
        raise ValueError(f"refusing to mint an id for a hybrid: {sci_name!r}")
    slug = "-".join(strip_accents(sci_name).lower().split())
    if not _ID_RE.fullmatch(slug):
        raise ValueError(f"not a plain scientific name, can't mint an id: {sci_name!r}")
    return slug


class SpeciesTable:
    def __init__(self, rows: Iterable[SpeciesRow] = ()) -> None:
        self._rows: dict[str, SpeciesRow] = {}
        self._live_by_gbif: dict[int, SpeciesRow] = {}
        self._live_by_name: dict[str, SpeciesRow] = {}
        for row in rows:
            self._insert(row)
        self._check_aliases()

    def add(self, row: SpeciesRow) -> None:
        self._insert(row)
        try:
            self._check_aliases()
        except ValueError:
            self._remove(row)
            raise

    def _insert(self, row: SpeciesRow) -> None:
        if row.id in self._rows:
            raise ValueError(f"duplicate species id {row.id!r}")
        if not row.is_alias:
            if row.gbif_key is not None and row.gbif_key in self._live_by_gbif:
                other = self._live_by_gbif[row.gbif_key]
                raise ValueError(f"gbif_key {row.gbif_key} already belongs to live species {other.id!r}")
            name = _normalise_name(row.sci_name)
            if name in self._live_by_name:
                other = self._live_by_name[name]
                raise ValueError(f"sci_name {row.sci_name!r} already belongs to live species {other.id!r}")
            if row.gbif_key is not None:
                self._live_by_gbif[row.gbif_key] = row
            self._live_by_name[name] = row
        self._rows[row.id] = row

    def _remove(self, row: SpeciesRow) -> None:
        del self._rows[row.id]
        if not row.is_alias:
            self._live_by_name.pop(_normalise_name(row.sci_name), None)
            if row.gbif_key is not None:
                self._live_by_gbif.pop(row.gbif_key, None)

    def _check_aliases(self) -> None:
        for row in self._rows.values():
            if row.is_alias:
                self._resolve(row)

    def _resolve(self, row: SpeciesRow) -> SpeciesRow:
        seen = {row.id}
        while row.alias_of is not None:
            successor = self._rows.get(row.alias_of)
            if successor is None:
                raise ValueError(f"species {row.id!r} is an alias of unknown id {row.alias_of!r}")
            if successor.id in seen:
                raise ValueError(f"alias cycle through species {successor.id!r}")
            seen.add(successor.id)
            row = successor
        return row

    def get(self, species_id: str, *, follow_aliases: bool = True) -> SpeciesRow:
        try:
            row = self._rows[species_id]
        except KeyError:
            raise KeyError(f"unknown species id {species_id!r}") from None
        return self._resolve(row) if follow_aliases else row

    def by_gbif_key(self, key: int) -> SpeciesRow:
        if key in self._live_by_gbif:
            return self._live_by_gbif[key]
        for row in self._rows.values():
            if row.gbif_key == key:
                return self._resolve(row)
        raise KeyError(f"no species with gbif_key {key}")

    def by_sci_name(self, name: str) -> SpeciesRow:
        wanted = _normalise_name(name)
        if wanted in self._live_by_name:
            return self._live_by_name[wanted]
        for row in self._rows.values():
            if _normalise_name(row.sci_name) == wanted:
                return self._resolve(row)
        raise KeyError(f"no species with scientific name {name!r}")

    def find(self, sci_name: str, gbif_key: int | None) -> SpeciesRow | None:
        """The known species for this GBIF key or scientific name, or None (what `mint` would reuse)."""
        if gbif_key is not None:
            try:
                return self.by_gbif_key(gbif_key)
            except KeyError:
                pass
        try:
            return self.by_sci_name(sci_name)
        except KeyError:
            return None

    def mint(self, sci_name: str, common_name: str, gbif_key: int | None) -> Minted:
        """Return the known species for this GBIF key or name, else mint and add a new row."""
        known = self.find(sci_name, gbif_key)
        if known is not None:
            return Minted(known, created=False)
        row = SpeciesRow(id=mint_id(sci_name), sci_name=" ".join(sci_name.split()), common_name=common_name, gbif_key=gbif_key)
        self.add(row)
        return Minted(row, created=True)

    def __contains__(self, species_id: object) -> bool:
        return species_id in self._rows

    def __iter__(self) -> Iterator[SpeciesRow]:
        """Live rows (no aliases), in id order."""
        return (row for row in self.all_rows() if not row.is_alias)

    def __len__(self) -> int:
        return len(self._live_by_name)

    def all_rows(self) -> list[SpeciesRow]:
        """Every row, aliases included, in id order."""
        return [self._rows[k] for k in sorted(self._rows)]


def _parse_row(record: list[str], path: Path, line: int) -> SpeciesRow:
    if len(record) != len(HEADER):
        raise ValueError(f"{path}:{line}: expected {len(HEADER)} columns, got {len(record)}")
    v = dict(zip(HEADER, record))

    def text(name: str) -> str | None:
        return v[name] or None

    def integer(name: str) -> int | None:
        if not v[name]:
            return None
        try:
            return int(v[name])
        except ValueError:
            raise ValueError(f"{path}:{line}: {name} must be an integer, got {v[name]!r}") from None

    return SpeciesRow(
        id=v["id"],
        sci_name=v["sci_name"],
        common_name=v["common_name"],
        gbif_key=integer("gbif_key"),
        inat_taxon_id=integer("inat_taxon_id"),
        wikipedia_title=text("wikipedia_title"),
        ebird_code=text("ebird_code"),
        birdnet_label=text("birdnet_label"),
        alias_of=text("alias_of"),
        ioc_name=v["ioc_name"],
    )


def load_species(path: Path = SPECIES_CSV) -> SpeciesTable:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = tuple(next(reader, ()))
        if header != HEADER:
            raise ValueError(f"{path}: expected header {','.join(HEADER)}, got {','.join(header)}")
        return SpeciesTable(_parse_row(record, path, reader.line_num) for record in reader if record)


def save_species(table: SpeciesTable, path: Path = SPECIES_CSV) -> None:
    """Write every row sorted by id with the fixed header, UTF-8 and ``\\n`` endings, for reviewable diffs."""
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(HEADER)
        for row in table.all_rows():
            writer.writerow("" if (v := getattr(row, name)) is None else v for name in HEADER)
