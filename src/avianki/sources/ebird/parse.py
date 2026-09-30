"""Pure parsers for the two eBird API 2.0 responses `EbirdSpeciesSource` uses.

A shape they don't recognise is a `SourceError`, never an empty list (ADR 0007).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from avianki.core.http import SourceError

# `ref/taxonomy` marks each row's rank; species is the only one a flashcard can be about.
# (The others are slashes, spuhs, hybrids, forms and domestics.)
SPECIES_CATEGORY = "species"


@dataclass(frozen=True)
class TaxonRow:
    code: str
    common_name: str
    sci_name: str
    category: str | None


def species_codes(payload: Any, what: str) -> list[str]:
    """``product/spplist/<region>``: a JSON array of eBird species codes, in eBird's order."""
    if not isinstance(payload, list) or not all(isinstance(c, str) and c for c in payload):
        raise SourceError(f"eBird species list for {what} is not a list of species codes")
    return list(dict.fromkeys(str(c) for c in payload))  # a code twice would only make a duplicate note


def taxonomy_rows(payload: Any) -> dict[str, TaxonRow]:
    """``ref/taxonomy/ebird``: rows by species code.

    ``comName`` and ``sciName`` must be non-empty strings; ``category`` is optional in the
    payload (a missing one is None) so old recordings still parse.
    """
    if not isinstance(payload, list):
        raise SourceError("eBird taxonomy response is not a list")
    rows: dict[str, TaxonRow] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise SourceError("eBird taxonomy response holds a row that is not an object")
        code, com, sci = item.get("speciesCode"), item.get("comName"), item.get("sciName")
        if not (isinstance(code, str) and code and isinstance(com, str) and com and isinstance(sci, str) and sci):
            raise SourceError(f"eBird taxonomy row lacks speciesCode, comName or sciName: {item!r:.120}")
        category = item.get("category")
        rows[code] = TaxonRow(code, com, sci, category if isinstance(category, str) else None)
    return rows


def is_species(row: TaxonRow) -> bool:
    return row.category is None or row.category == SPECIES_CATEGORY
