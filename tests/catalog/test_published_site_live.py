"""The published site on GitHub Pages (ADR 0020 check 3; run with --integration).

Three facts a visitor depends on: the manifest loads and parses; a media file the species file
points at is served with `access-control-allow-origin: *` (the web app fetches media cross-origin
when it is opened from another origin, and the CLI does too); and the web app itself is served.
"""

from __future__ import annotations

import random
import re
from html import unescape
from pathlib import Path

import pytest
import requests

from avianki.catalog.format import DEFAULT_BASE_URL, Manifest, SpeciesFile

SITE = DEFAULT_BASE_URL.removesuffix("catalog/")
TIMEOUT = 60
INDEX_HTML = Path(__file__).resolve().parents[2] / "web" / "index.html"
TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)


def get(url: str, **kwargs) -> requests.Response:
    # An explicit Origin makes a server that only adds CORS headers for cross-origin requests do so.
    headers = {"Origin": "https://example.org"}
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    response = get(DEFAULT_BASE_URL + "manifest.json")
    assert response.status_code == 200
    return Manifest.from_dict(response.json())


@pytest.mark.integration
def test_the_manifest_loads_and_parses(manifest: Manifest) -> None:
    assert manifest.base_url == DEFAULT_BASE_URL
    assert manifest.species_file
    assert any(r.slug == "us-ma" for r in manifest.regions)
    print(f"\nmanifest: catalog {manifest.catalog_version}, {len(manifest.regions)} regions, EOD {manifest.eod_version}")


@pytest.mark.integration
def test_random_media_files_are_served_with_open_cors(manifest: Manifest) -> None:
    species = SpeciesFile.from_dict(get(DEFAULT_BASE_URL + manifest.species_file).json())
    photos = [m.file for e in species.entries.values() for m in e.photo]
    audio = [m.file for e in species.entries.values() for m in e.audio]
    assert photos and audio, "the published catalog has no photos or no audio"
    for kind, files in (("photo", photos), ("audio", audio)):
        name = random.choice(files)
        with get(DEFAULT_BASE_URL + name, stream=True) as response:
            print(f"\n{kind}: {name} -> {response.status_code}, content-type {response.headers.get('content-type')}")
            assert response.status_code == 200, name
            assert response.headers.get("access-control-allow-origin") == "*", name


@pytest.mark.integration
def test_the_web_app_is_served() -> None:
    wanted = unescape(TITLE.search(INDEX_HTML.read_text(encoding="utf-8")).group(1).strip())  # type: ignore[union-attr]
    response = get(SITE)
    assert response.status_code == 200
    served = TITLE.search(response.text)
    assert served is not None, "the site root has no <title>"
    assert unescape(served.group(1).strip()) == wanted
