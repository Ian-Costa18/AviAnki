"""The Credits field and the deck description (ADR 0012, ADR 0016)."""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlsplit

from deck_fakes import ROBIN_AUDIO, ROBIN_PHOTO, manifest

from avianki.catalog.format import DatasetCredit
from avianki.deck.credits import credits_field, deck_description

LICENCE_NOTICE = (
    "This deck is a compilation. AviAnki's templates and selection are MIT-licensed. "
    "Each photo and recording keeps its own licence, credited on its card, "
    "and no further terms are imposed on it."
)
EBIRD_LINE = (
    "Built from eBird data for personal use. eBird's terms don't allow redistributing this deck."
)


def test_credits_field_joins_the_assets_used_without_escaping() -> None:
    both = credits_field(ROBIN_PHOTO, ROBIN_AUDIO)
    assert both.startswith('<div class="credits">') and both.endswith("</div>")
    assert ROBIN_PHOTO.credit in both and ROBIN_AUDIO.credit in both  # verbatim, not re-escaped
    assert both.index(ROBIN_PHOTO.credit) < both.index(ROBIN_AUDIO.credit)
    assert "&lt;" not in both and "&amp;lt;" not in both


def test_credits_field_only_lists_assets_actually_used() -> None:
    photo_only = credits_field(ROBIN_PHOTO, None)
    assert ROBIN_PHOTO.credit in photo_only and ROBIN_AUDIO.credit not in photo_only
    audio_only = credits_field(None, ROBIN_AUDIO)
    assert ROBIN_AUDIO.credit in audio_only and ROBIN_PHOTO.credit not in audio_only


def test_credits_field_is_empty_when_nothing_is_used() -> None:
    assert credits_field(None, None) == ""


def test_description_has_guidance_then_dataset_credit_then_notice() -> None:
    d = deck_description(manifest(), ebird=False)
    assert "Show Answer" in d and "20 new cards a day" in d
    assert d.count("<br>") == 2  # three guidance lines
    credit = "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF"
    assert credit in d and "CC-BY-4.0" in d
    assert 'href="https://doi.org/10.15468/aomfnb"' in d
    assert "modified: filtered and ranked by region" in d
    assert d.index("Show Answer") < d.index(credit) < d.index(LICENCE_NOTICE)
    assert LICENCE_NOTICE in d


def test_description_ebird_line_only_when_asked() -> None:
    assert EBIRD_LINE not in deck_description(manifest(), ebird=False)
    d = deck_description(manifest(), ebird=True)
    assert EBIRD_LINE in d
    assert d.index(LICENCE_NOTICE) < d.index(EBIRD_LINE)


def test_description_includes_the_ioc_credit_when_present() -> None:
    d = deck_description(manifest(ioc=True), ebird=False)
    hosts = {urlsplit(href).hostname for href in re.findall(r'href="([^"]+)"', d)}
    assert "IOC World Bird List" in d and {"www.worldbirdnames.org"} <= hosts
    assert "IOC World Bird List" not in deck_description(manifest(), ebird=False)


def test_manifest_values_are_escaped() -> None:
    m = manifest()
    evil = DatasetCredit(
        'Data <script>alert(1)</script> & "co"', "CC-BY-4.0<b>", 'https://x.org/?a=1&b="2"', "<i>mod</i>"
    )
    m = replace(m, dataset_credits=[evil])
    d = deck_description(m, ebird=False)
    assert "<script>" not in d and "<b>" not in d and "<i>mod</i>" not in d
    assert "&lt;script&gt;" in d and "&amp;" in d
    assert 'href="https://x.org/?a=1&amp;b=&quot;2&quot;"' in d
