"""Tests for the pure parsing and gating helpers in avianki.sources.commons.parse."""

from __future__ import annotations

from typing import Any

import pytest
from commons_fakes import audio_page, entity, file_page

from avianki.core.http import SourceError
from avianki.sources.commons import parse


def info_of(page: dict[str, Any]) -> parse.FileInfo:
    info = parse._file_info(page)
    assert info is not None
    return info


# ── HTML reduced to text ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("html", "text"),
    [
        (None, ""),
        ("", ""),
        ("plain", "plain"),
        ("a <b>bold</b>  <i>move</i>", "a bold move"),
        ("Tom &amp; Jerry &#169;", "Tom & Jerry ©"),
        ("line<br>break", "line break"),
        ("<script>alert(1)</script>ok<style>p{}</style>", "ok"),
        ("zero​width \x07bell", "zerowidth bell"),
        ("<a href='x'>unclosed", "unclosed"),
    ],
)
def test_plain_text(html: str | None, text: str):
    assert parse.plain_text(html) == text


@pytest.mark.parametrize(
    ("artist", "expected"),
    [
        ('<a href="//commons.wikimedia.org/wiki/User:Mdf" title="User:Mdf">Mdf</a>',
         ("Mdf", "https://commons.wikimedia.org/wiki/User:Mdf")),
        ('<a href="/wiki/User:Foo">User:Foo</a>', ("Foo", "https://commons.wikimedia.org/wiki/User:Foo")),
        ('<a href="https://example.org/">Site</a> and <a href="//commons.wikimedia.org/wiki/User:Bar">Bar</a>',
         ("Bar", "https://commons.wikimedia.org/wiki/User:Bar")),  # a user-page link wins
        ('<a href="https://example.org/">Site</a>', ("Site", "https://example.org/")),
        ('<a href="javascript:x()">Eve</a>', ("Eve", None)),
        ("Plain Name", ("Plain Name", None)),
        ("Unknown", (None, None)),
        ("  ", (None, None)),
        (None, (None, None)),
        ("Own work", (None, None)),
        ("No machine-readable author provided. Own work assumed (based on copyright claims).", (None, None)),
        ("No machine-readable author provided. Ann assumed (based on copyright claims).", ("Ann", None)),
    ],
)
def test_parse_artist(artist: str | None, expected: tuple[str | None, str | None]):
    assert parse.parse_artist(artist) == expected


def test_user_page_url_quotes_the_name():
    assert parse.user_page_url("A B/C?") == "https://commons.wikimedia.org/wiki/User:A_B%2FC%3F"


# ── licence ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ({"License": "cc-by-sa-4.0", "LicenseShortName": "CC BY-SA 4.0"}, "CC-BY-SA-4.0"),
        ({"License": "cc-by-2.0"}, "CC-BY-2.0"),  # one field is enough
        ({"LicenseShortName": "CC BY 3.0"}, "CC-BY-3.0"),
        ({"License": "cc0", "LicenseShortName": "CC0"}, "CC0-1.0"),
        ({"License": "cc-by-4.0", "LicenseShortName": "CC BY-SA 4.0"}, None),  # disagree
        ({"License": "cc-by-sa-4.0", "LicenseShortName": "CC BY-NC 4.0"}, None),
        ({"License": "cc-by-sa-4.0", "LicenseShortName": ""}, "CC-BY-SA-4.0"),
        ({"License": "cc-by", "LicenseShortName": "CC BY"}, None),  # no version
        ({"License": "cc-by-sa-3.0-de"}, None),
        ({"License": "cc-by-nc-sa-4.0"}, None),
        ({"License": "gfdl"}, None),
        ({"License": "pd"}, None),
        ({"License": "fal"}, None),
        ({}, None),
    ],
)
def test_resolve_file_licence(meta: dict[str, str], expected: str | None):
    got = parse.resolve_file_licence(meta)
    assert (got.licence_id if got else None) == expected
    assert got is None or got.version_assumed is False


# ── API payload shapes ───────────────────────────────────────────────────────


def test_check_api_turns_error_bodies_into_source_errors():
    with pytest.raises(SourceError, match="maxlag"):
        parse.check_api({"error": {"code": "maxlag", "info": "x"}}, "t")
    with pytest.raises(SourceError, match="API error"):
        parse.check_api({"error": "plain string"}, "t")
    with pytest.raises(SourceError):
        parse.check_api([], "t")
    assert parse.check_api({"query": {}}, "t") == {"query": {}}


def test_lead_pages_follow_normalisation_and_redirects():
    payload = {
        "query": {
            "normalized": [{"from": "a_b", "to": "A b"}],
            "redirects": [{"from": "A b", "to": "Target"}, {"from": "c", "to": "Gone"}],
            "pages": [
                {"pageid": 1, "title": "Target", "pageimage": "F.jpg", "pageprops": {"wikibase_item": "Q9"}},
                {"title": "Gone", "missing": True},
                {"pageid": 3, "title": "D", "pageprops": {"disambiguation": ""}},
            ],
        }
    }
    got = parse.parse_lead_pages(payload, ["a_b", "c", "D"])
    assert got["a_b"] == parse.LeadPage(1, "Target", "F.jpg", "Q9", False)
    assert got["c"] is None
    lead = got["D"]
    assert lead is not None and lead.disambiguation and lead.image is None and lead.wikidata_id is None


def test_lead_pages_reject_a_response_that_loses_a_title():
    with pytest.raises(SourceError):
        parse.parse_lead_pages({"query": {"pages": []}}, ["x"])
    with pytest.raises(SourceError):
        parse.parse_lead_pages({"query": {"pages": [{"title": "X", "missing": False}]}}, ["X"])  # no pageid


def test_entities_ignore_non_string_and_non_value_claims():
    payload = {"entities": {"Q1": entity("Q1", "Aus bus", "Cus dus"), "Q2": {"id": "Q2", "missing": ""},
                            "Q3": {"id": "Q3", "claims": []}}}
    payload["entities"]["Q1"]["claims"]["P225"].append({"mainsnak": {"snaktype": "novalue"}, "rank": "normal"})
    payload["entities"]["Q1"]["claims"]["P225"].append(
        {"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": "Q5"}}}, "rank": "normal"})
    got = parse.parse_entities(payload, ["Q1", "Q2", "Q3"])
    assert got["Q1"] == parse.TaxonNames(frozenset({"aus bus", "cus dus"}))
    assert got["Q2"] is None
    assert got["Q3"] == parse.TaxonNames(frozenset())
    with pytest.raises(SourceError):
        parse.parse_entities(payload, ["Q404"])
    with pytest.raises(SourceError):
        parse.parse_entities({"entities": {"Q1": {"id": "Q1"}}}, ["Q1"])  # no claims member


def test_taxon_match_is_exact_apart_from_case_and_whitespace():
    names = parse.TaxonNames(frozenset({"turdus migratorius"}))
    assert parse.taxon_match("Turdus  migratorius", names)
    assert not parse.taxon_match("Turdus", names)
    assert not parse.taxon_match("Turdus migratorius", None)


def test_files_by_title_reports_gone_files_as_none():
    payload = {"query": {"normalized": [{"from": "File:a_b.jpg", "to": "File:a b.jpg"}],
                         "pages": [file_page(1, "a b.jpg"), {"ns": 6, "title": "File:Gone.jpg", "missing": True},
                                   {"pageid": 3, "ns": 6, "title": "File:Ghost.jpg", "imagerepository": ""}]}}
    got = parse.parse_files_by_title(payload, ["File:a_b.jpg", "File:Gone.jpg", "File:Ghost.jpg"])
    assert got["File:a_b.jpg"] is not None and got["File:Gone.jpg"] is None and got["File:Ghost.jpg"] is None


def test_file_info_rejects_malformed_imageinfo():
    page = file_page(1, "a.jpg")
    del page["imageinfo"][0]["mime"]
    with pytest.raises(SourceError, match="malformed"):
        parse._file_info(page)
    with pytest.raises(SourceError):
        parse._file_info({"pageid": 1, "title": "File:x", "imageinfo": "nope"})


def test_members_response_with_no_query_is_empty_only_when_the_api_says_complete():
    assert parse.parse_files({"batchcomplete": True}) == []
    with pytest.raises(SourceError):
        parse.parse_files({"warnings": {}})


def test_category_sizes_skip_missing_and_empty_categories():
    payload = {"query": {"pages": [
        {"title": "Category:A", "categoryinfo": {"files": 3}},
        {"title": "Category:B", "missing": True},
        {"title": "Category:C", "categoryinfo": {"files": 0}},
        {"title": "Category:D"},
    ]}}
    assert parse.parse_category_sizes(payload) == {"Category:A": 3}
    with pytest.raises(SourceError):
        parse.parse_category_sizes({"query": {"pages": [{"title": "Category:A", "categoryinfo": {"files": "x"}}]}})


# ── gates ────────────────────────────────────────────────────────────────────


def test_photo_gate_returns_a_record_or_a_reason():
    ok = parse.photo_record(info_of(file_page(5, "Bird.jpg")), "2026-09-28")
    assert not isinstance(ok, parse.Reject) and ok.source_asset_id == "M5"
    bad = parse.photo_record(info_of(file_page(5, "Bird.jpg", width=100, height=100)), "2026-09-28")
    assert isinstance(bad, parse.Reject) and bad.reason == "small" and "100x100" in str(bad)


def test_the_not_a_photo_keyword_list_matches_whole_words_only():
    assert parse.NOT_A_PHOTO.search("Paintings of birds")
    assert parse.NOT_A_PHOTO.search("Bird eggs")
    assert not parse.NOT_A_PHOTO.search("Nesting birds")  # "nest" as a whole word only
    assert not parse.NOT_A_PHOTO.search("Stampede")
    assert not parse.NOT_A_PHOTO.search("Turdus migratorius")


def test_audio_gate_requires_the_species_category_only_for_searches():
    page = audio_page(9, "x.ogg", "Turdus merula")
    info = info_of(page)
    assert isinstance(parse.audio_record(info, "d", species_name="Turdus migratorius"), parse.Reject)
    assert not isinstance(parse.audio_record(info, "d", strict=False), parse.Reject)


# ── ranking helpers ──────────────────────────────────────────────────────────


def test_rank_key_orders_bucket_then_licence_then_length():
    keys = {
        "best": parse.audio_rank_key(100.0, "CC0-1.0", 9),
        "by": parse.audio_rank_key(100.0, "CC-BY-4.0", 1),
        "sa-long": parse.audio_rank_key(90.0, "CC-BY-SA-4.0", 1),
        "sa-longer": parse.audio_rank_key(100.0, "CC-BY-SA-4.0", 2),
        "mid": parse.audio_rank_key(200.0, "CC0-1.0", 1),
        "short": parse.audio_rank_key(5.0, "CC0-1.0", 1),
        "huge": parse.audio_rank_key(500.0, "CC0-1.0", 1),
        "unknown": parse.audio_rank_key(None, "CC0-1.0", 1),
    }
    assert sorted(keys, key=keys.__getitem__) == ["best", "by", "sa-longer", "sa-long", "mid", "short", "huge", "unknown"]


def test_recording_key_reads_the_xeno_canto_number():
    assert parse.recording_key("File:Turdus - American Robin - XC123456.ogg") == "123456"
    assert parse.recording_key("File:Robin XC 77.mp3") == "77"
    assert parse.recording_key("File:Robin.ogg") is None
    assert parse.recording_key("File:AXC1.ogg") is None
