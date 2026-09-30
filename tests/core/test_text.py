"""The one fold every name lookup uses (regions.csv, the catalog's regions, the CLI hint)."""

from __future__ import annotations

import pytest

from avianki.core.text import fold, strip_accents


@pytest.mark.parametrize(
    ("typed", "key"),
    [
        (" Québec", "quebec"),
        ("QUÉBEC", "quebec"),
        ("New   York\t", "new york"),
        ("Nuevo León", "nuevo leon"),
        ("us-ma", "us-ma"),
    ],
)
def test_fold_ignores_case_accents_and_spacing(typed: str, key: str) -> None:
    assert fold(typed) == key


def test_strip_accents_keeps_case_and_spacing() -> None:
    assert strip_accents("Québec  City") == "Quebec  City"
