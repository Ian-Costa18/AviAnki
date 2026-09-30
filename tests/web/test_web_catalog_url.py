"""``?catalog=`` is a local-development hook only: on the public site a crafted link must not make
the page build an AviAnki deck from someone else's catalog.
"""

from __future__ import annotations

import pytest

LIVE = "https://ian-costa18.github.io/AviAnki/catalog/manifest.json"
EVIL = "https://evil.example/catalog/manifest.json"


def manifest_url(page, href: str) -> str:
    return page.evaluate(
        "async (href) => (await import('/js/catalog.js')).manifestUrl(href)", href
    )


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:5000", "[::1]:8080"])
def test_local_pages_honour_the_override(page, host: str) -> None:
    assert manifest_url(page, f"http://{host}/?catalog={LIVE}") == LIVE


def test_the_public_site_ignores_the_override(page) -> None:
    got = manifest_url(page, f"https://ian-costa18.github.io/AviAnki/?catalog={EVIL}")
    assert got == "https://ian-costa18.github.io/AviAnki/catalog/manifest.json"


def test_without_an_override_the_catalog_sits_next_to_the_page(page) -> None:
    assert manifest_url(page, "http://localhost:8000/app/") == "http://localhost:8000/app/catalog/manifest.json"
