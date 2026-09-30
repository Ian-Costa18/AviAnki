"""Offline fakes for the ``--ebird`` path: an eBird API session, fake asset sources and a scripted
BirdNET, plus the helper that plugs them into `avianki.catalog.adhoc`. Nothing here touches
the network. Images go through real Pillow and audio through real ffmpeg.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pipeline_fakes import (
    AUDIO,
    PHOTO,
    FakeSource,
    FakeSourceNoSpecies,
    ScriptedAnalyzer,
    make_fake_registry,
)

from cli_fakes import FIXTURE_CATALOG, deck_info, note_fields, read_apkg  # noqa: F401  (re-exported)

from avianki.catalog import adhoc
from avianki.core.http import HttpClient

SPPLIST = "https://api.ebird.org/v2/product/spplist/US-MA-017"
TAXONOMY = "https://api.ebird.org/v2/ref/taxonomy/ebird"

# In the fixture catalog (with names, photo and audio):
ROBIN_CODE, ROBIN_ID = "amerob", "turdus-migratorius"
JAY_CODE, JAY_ID = "blujay", "cyanocitta-cristata"
# In species.csv but not in the fixture catalog: built live.
WREN_CODE, WREN_ID = "houwre", "troglodytes-aedon"
# Not in species.csv at all: a transient id, built live.
NEW_CODE, NEW_ID = "zzyzx1", "zzyzxus-fakebirdus"

TAXA = [
    {"speciesCode": ROBIN_CODE, "comName": "American Robin", "sciName": "Turdus migratorius", "category": "species"},
    {"speciesCode": WREN_CODE, "comName": "House Wren", "sciName": "Troglodytes aedon", "category": "species"},
    {"speciesCode": "y00001", "comName": "Robin x Wren (hybrid)", "sciName": "Turdus x Troglodytes", "category": "hybrid"},
    {"speciesCode": NEW_CODE, "comName": "Zzyzx Fakebird", "sciName": "Zzyzxus fakebirdus", "category": "species"},
    {"speciesCode": JAY_CODE, "comName": "Blue Jay", "sciName": "Cyanocitta cristata", "category": "species"},
]
ORDER = [ROBIN_CODE, WREN_CODE, "y00001", NEW_CODE, JAY_CODE]

LABELS = [
    "Turdus migratorius_American Robin",
    "Troglodytes aedon_House Wren",
    "Zzyzxus fakebirdus_Zzyzx Fakebird",
    "Cyanocitta cristata_Blue Jay",
]


class _Reply:
    def __init__(self, body: Any, status: int = 200) -> None:
        self.status_code = status
        self.content = json.dumps(body).encode()
        self.headers = {"Content-Type": "application/json"}


class EbirdSession:
    """Answers the two eBird calls; records (url, params, headers) of each."""

    def __init__(self, order: list[str] | None = None, taxa: list[dict] | None = None, status: int = 200) -> None:
        self.order = ORDER if order is None else order
        self.taxa = TAXA if taxa is None else taxa
        self.status = status
        self.calls: list[tuple[str, dict | None, dict]] = []

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: float | None = None):
        self.calls.append((url, params, headers or {}))
        if self.status != 200:
            return _Reply({"error": "nope"}, self.status)
        if "spplist" in url:
            return _Reply(self.order)
        wanted = set((params or {})["species"].split(","))
        return _Reply([t for t in self.taxa if t["speciesCode"] in wanted])


def live_sources() -> tuple[FakeSource, FakeSourceNoSpecies]:
    """Commons has a photo and a recording for the wren and the made-up bird; iNaturalist nothing."""
    commons, inat = FakeSource("commons"), FakeSourceNoSpecies("inaturalist")
    for sid in (WREN_ID, NEW_ID):
        commons.add(sid, PHOTO, f"{sid}-photo")
        commons.add(sid, AUDIO, f"{sid}-audio")
    return commons, inat


def install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: EbirdSession | None = None,
    sources: tuple[FakeSource, FakeSourceNoSpecies] | None = None,
    analyzer: ScriptedAnalyzer | None = None,
) -> tuple[EbirdSession, tuple[FakeSource, FakeSourceNoSpecies], ScriptedAnalyzer]:
    """Point `avianki.catalog.adhoc` at fakes. Returns what it installed, to inspect afterwards."""
    session = session or EbirdSession()
    sources = sources or live_sources()
    analyzer = analyzer or ScriptedAnalyzer([0.9], labels=LABELS)
    monkeypatch.setattr(
        adhoc, "new_client", lambda cache_dir: HttpClient(cache_dir=None, session=session, sleep=lambda _s: None, max_retries=0)
    )
    monkeypatch.setattr(adhoc, "new_registry", lambda client, table: make_fake_registry(*sources))
    monkeypatch.setattr(adhoc, "new_analyzer", lambda: analyzer)
    return session, sources, analyzer
