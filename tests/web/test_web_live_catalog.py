"""One build against the published catalog, the way a visitor gets it (``--integration``).

Opens the app with ``?catalog=<the live manifest>``, builds Standard for Massachusetts in Chromium,
and runs the acceptance checks on the package. Needs the network; the numbers it prints are the
real download size and time.
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest
from app_support import DONE, HEAP_SAMPLER, build, import_and_check, open_app

LIVE_CATALOG = "https://ian-costa18.github.io/AviAnki/catalog/"


def _get_json(name: str):
    with urllib.request.urlopen(LIVE_CATALOG + name, timeout=60) as response:  # noqa: S310 - https only
        return json.load(response)


@pytest.mark.integration
def test_build_massachusetts_standard_from_the_published_catalog(new_context, base_url, tmp_path) -> None:
    from avianki.catalog.format import RegionFile, SpeciesFile
    from avianki.deck.build import note_guid, plan_notes, select_species

    manifest = _get_json("manifest.json")
    ref = next(r for r in manifest["regions"] if r["slug"] == "us-ma")
    region = RegionFile.from_dict(_get_json(ref["file"]))
    species = SpeciesFile.from_dict(_get_json(manifest["species_file"]))
    ids = select_species(region, species, ("photo", "audio"), tier="standard", month=None)
    wanted = {note_guid(n.species_id, n.card_type) for n in plan_notes(ids, species, ("photo", "audio"))}

    context = new_context("chromium")
    context.add_init_script(HEAP_SAMPLER)
    page = open_app(context, base_url, f"?catalog={LIVE_CATALOG}manifest.json")
    downloads: list[str] = []
    page.on("response", lambda r: downloads.append(r.url) if r.url.startswith(LIVE_CATALOG + "media/") else None)

    started = time.monotonic()
    files = build(page, tmp_path, region="Massachusetts", timeout=600_000)
    seconds = time.monotonic() - started
    peak = page.evaluate("window.__peak") / (1024 * 1024)

    assert page.is_visible(DONE)
    assert [f.name for f in files] == ["AviAnki-us-ma.apkg"]
    got = import_and_check(tmp_path, files, species=species)
    size = files[0].stat().st_size
    print(
        f"\nlive catalog, us-ma Standard: {seconds:.1f} s, {size / 1e6:.1f} MB, {got['notes']} notes "
        f"({len(ids)} birds), {len(downloads)} media downloads, peak JS heap {peak:.1f} MB"
    )
    assert got["guids"] == wanted
