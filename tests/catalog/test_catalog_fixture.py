"""The fixture catalog in tests/fixtures/catalog is a valid, tiny, published catalog.

It's used by the client, CLI and deck tests now and by the web (Playwright) tests later, so
these tests pin what it is meant to contain. Regenerate it with make_fixture.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from avianki.catalog.credit import credit_is_safe
from avianki.catalog.format import load_catalog

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "catalog"
MAX_BYTES = 200_000


def test_fixture_is_valid_and_hashes_check_out() -> None:
    pytest.importorskip("jsonschema")
    cat = load_catalog(FIXTURE)  # schema + name hashes + region/manifest agreement
    assert cat.media_problems() == []  # every referenced file exists, right size, right hash


def test_fixture_is_small() -> None:
    total = sum(p.stat().st_size for p in FIXTURE.rglob("*") if p.is_file())
    assert total < MAX_BYTES


def test_fixture_has_no_unreferenced_media() -> None:
    pytest.importorskip("jsonschema")
    cat = load_catalog(FIXTURE)
    on_disk = {p.relative_to(FIXTURE).as_posix() for p in (FIXTURE / "media").iterdir()}
    assert on_disk == set(cat.referenced_media())


def test_fixture_content_covers_the_cases_the_tests_rely_on() -> None:
    pytest.importorskip("jsonschema")
    cat = load_catalog(FIXTURE)
    assert [r.slug for r in cat.manifest.regions] == ["us-ma", "ca-qc", "us-az"]
    assert len(cat.species) == 12
    assert len(cat.regions["us-ma"].species) == 12
    assert any(r.name == "Québec" for r in cat.manifest.regions)
    assert [s for s, e in cat.species.items() if not e.audio]
    assert [s for s, e in cat.species.items() if not e.photo]
    assert cat.manifest.base_url == "https://fixture.invalid/catalog/"  # placeholder tests override

    # A month filter matters: some species are absent in January, others in July.
    monthly = dict(cat.regions["us-ma"].species)
    assert monthly["archilochus-colubris"][0] == 0 and monthly["archilochus-colubris"][6] > 0
    assert monthly["junco-hyemalis"][6] == 0 and monthly["junco-hyemalis"][0] > 0

    for entry in cat.species.entries.values():
        for ref in (*entry.photo, *entry.audio):
            assert credit_is_safe(ref.credit)
