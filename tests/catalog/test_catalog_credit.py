"""Tests for avianki.catalog.credit: the escaped answer-side credit line (ADR 0012)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from avianki.catalog.credit import (
    credit_is_safe,
    is_http_url,
    licence_label,
    render_credit,
)
from avianki.core.licences import AssetRecord, licence_url


def make_record(**overrides: object) -> AssetRecord:
    base: dict[str, object] = {
        "source": "wikimedia",
        "source_asset_id": "File:Turdus-migratorius-002.jpg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Turdus-migratorius-002.jpg",
        "file_url": "https://upload.wikimedia.org/x.jpg",
        "licence_id": "CC-BY-SA-3.0",
        "licence_url": licence_url("CC-BY-SA-3.0"),
        "creator": "Mdf",
        "title": "Turdus-migratorius-002",
        "modifications": ("resized",),
        "retrieved_at": "2026-09-28",
    }
    base.update(overrides)
    return AssetRecord(**base)  # type: ignore[arg-type]


def test_golden_cc_by_sa_3_photo() -> None:
    assert render_credit("photo", make_record()) == (
        "Photo: <i>Turdus-migratorius-002</i> by <b>Mdf</b> · "
        '<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a> · '
        '<a href="https://commons.wikimedia.org/wiki/File:Turdus-migratorius-002.jpg">source</a>'
        " · resized"
    )


def test_golden_cc_by_4_audio_with_two_modifications() -> None:
    record = make_record(
        source="inaturalist",
        source_url="https://www.inaturalist.org/observations/123",
        licence_id="CC-BY-4.0",
        licence_url=licence_url("CC-BY-4.0"),
        creator="Jane Roe",
        title=None,
        modifications=("Trimmed to 10s", "transcoded to mp3"),
    )
    assert render_credit("audio", record) == (
        "Recording by <b>Jane Roe</b> · "
        '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a> · '
        '<a href="https://www.inaturalist.org/observations/123">source</a>'
        " · trimmed to 10s, transcoded to mp3"
    )


def test_cc0_renders_creator_and_optional_title_when_known() -> None:
    record = make_record(
        licence_id="CC0-1.0",
        licence_url=licence_url("CC0-1.0"),
        title=None,
        modifications=(),
    )
    out = render_credit("photo", record)
    assert out == (
        "Photo by <b>Mdf</b> · "
        '<a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0</a> · '
        '<a href="https://commons.wikimedia.org/wiki/File:Turdus-migratorius-002.jpg">source</a>'
    )
    with_title = render_credit("photo", replace(record, title="A Robin"))
    assert with_title.startswith("Photo: <i>A Robin</i> by <b>Mdf</b> · ")


def test_public_domain_mark_label() -> None:
    record = make_record(licence_id="PDM-1.0", licence_url=licence_url("PDM-1.0"))
    assert ">Public Domain Mark 1.0</a>" in render_credit("photo", record)


def test_title_included_for_version_assumed_inat_record() -> None:
    record = make_record(
        source="inaturalist",
        licence_id="CC-BY-4.0",
        licence_url=licence_url("CC-BY-4.0"),
        licence_version_assumed=True,
        title="Robin on a lawn",
    )
    assert render_credit("photo", record).startswith("Photo: <i>Robin on a lawn</i> by <b>Mdf</b>")


def test_version_assumed_without_title_is_incomplete() -> None:
    record = make_record(
        licence_id="CC-BY-4.0",
        licence_url=licence_url("CC-BY-4.0"),
        licence_version_assumed=True,
        title=None,
    )
    with pytest.raises(ValueError, match="title"):
        render_credit("photo", record)


@pytest.mark.parametrize(
    ("field", "value"),
    [("creator", None), ("creator", "  "), ("source_url", None), ("licence_url", None), ("title", "")],
)
def test_incomplete_record_raises_naming_the_field(field: str, value: str | None) -> None:
    with pytest.raises(ValueError, match=field):
        render_credit("photo", make_record(**{field: value}))


def test_several_missing_fields_are_all_named() -> None:
    with pytest.raises(ValueError, match="creator.*source_url|source_url.*creator"):
        render_credit("photo", make_record(creator=None, source_url=None))


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="kind"):
        render_credit("video", make_record())


def test_injection_in_creator_title_and_modifications_is_escaped() -> None:
    record = make_record(
        creator='<script>alert(1)</script> & "Bob"',
        title="<img src=x onerror=alert(1)> 'quoted'",
        modifications=("<b>bold</b>",),
    )
    out = render_credit("photo", record)
    assert "<script" not in out and "<img" not in out
    assert "&lt;script&gt;" in out and "&amp;" in out and "&quot;Bob&quot;" in out
    assert "&lt;img src=x onerror=alert(1)&gt;" in out
    assert "&lt;b&gt;bold&lt;/b&gt;" in out
    assert credit_is_safe(out)


def test_url_with_quote_cannot_break_out_of_href() -> None:
    record = make_record(source_url='https://example.org/a"onmouseover="alert(1)')
    out = render_credit("photo", record)
    assert 'onmouseover="' not in out
    assert "a&quot;onmouseover=&quot;alert(1)" in out
    assert credit_is_safe(out)


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        "data:text/html,<script>",
        "ftp://example.org/x",
        "//example.org/x",
        "https://",
        "https://exa mple.org/",
        "",
    ],
)
def test_non_http_urls_are_rejected(bad: str) -> None:
    assert not is_http_url(bad)
    with pytest.raises(ValueError, match="source_url"):
        render_credit("photo", make_record(source_url=bad))
    with pytest.raises(ValueError, match="licence_url"):
        render_credit("photo", make_record(licence_url=bad))


def test_licence_label_derivation() -> None:
    assert licence_label("CC-BY-SA-3.0") == "CC BY-SA 3.0"
    assert licence_label("CC-BY-2.5") == "CC BY 2.5"
    assert licence_label("CC0-1.0") == "CC0 1.0"
    assert licence_label("PDM-1.0") == "Public Domain Mark 1.0"
    with pytest.raises(ValueError):
        licence_label("CC-BY-NC-4.0")


def test_rendered_credits_are_safe() -> None:
    assert credit_is_safe(render_credit("photo", make_record()))
    assert credit_is_safe(render_credit("audio", make_record(modifications=())))


@pytest.mark.parametrize(
    "markup",
    [
        "<script>alert(1)</script>",
        '<img src="x">',
        '<img src=x onerror="alert(1)">',
        '<b onclick="alert(1)">x</b>',
        '<i style="x">x</i>',
        '<a href="javascript:alert(1)">x</a>',
        '<a href="jav&#x61;script:alert(1)">x</a>',
        '<a href="/relative">x</a>',
        '<a href="https://example.org/" onclick="x">x</a>',
        '<a href="https://example.org/" target="_blank">x</a>',
        "<a>x</a>",
        '<a href="https://example.org/">x',
        "<b>x</i>",
        "<b><i>x</i></b>",
        "<br/>",
        "<b/>",
        "<!-- c -->",
        "<!DOCTYPE html>",
        "<?php ?>",
        "x < y",
        "a & b",
        "<div>x</div>",
    ],
)
def test_credit_is_safe_rejects(markup: str) -> None:
    assert not credit_is_safe(markup)


@pytest.mark.parametrize(
    "markup",
    [
        "",
        "plain text",
        "a &amp; b &lt;c&gt; &#x27;d&#x27;",
        "<b>x</b> · <i>y</i>",
        '<a href="https://example.org/a?b=1&amp;c=2">x</a>',
    ],
)
def test_credit_is_safe_accepts(markup: str) -> None:
    assert credit_is_safe(markup)
