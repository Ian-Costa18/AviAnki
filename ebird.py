"""eBird API helpers."""

import logging
import os

import requests

log = logging.getLogger("bird_deck")


def _headers() -> dict:
    return {"X-eBirdApiToken": os.getenv("EBIRD_API_KEY", "")}


def fetch_species(region_code: str, limit: int | None = None) -> list[dict]:
    """
    Return [{speciesCode, comName, sciName}] for every species recorded in a region.
    Results are in eBird taxonomic order.
    """
    log.info("Fetching eBird species list for %s…", region_code)
    r = requests.get(
        f"https://api.ebird.org/v2/product/spplist/{region_code}",
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    codes: list[str] = r.json()
    log.info("  %d species recorded in %s", len(codes), region_code)

    if limit:
        codes = codes[:limit]

    # Resolve codes → full names in batches (safe URL length)
    species: list[dict] = []
    for i in range(0, len(codes), 200):
        batch = codes[i : i + 200]
        r2 = requests.get(
            "https://api.ebird.org/v2/ref/taxonomy/ebird",
            params={"species": ",".join(batch), "fmt": "json"},
            headers=_headers(),
            timeout=30,
        )
        r2.raise_for_status()
        for t in r2.json():
            species.append({
                "speciesCode": t["speciesCode"],
                "comName": t["comName"],
                "sciName": t["sciName"],
            })

    log.info("  Resolved %d species names", len(species))
    return species
