from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avianki import allaboutbirds

FIXTURES = Path(__file__).parent / "fixtures"


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _fixture_response(name: str) -> MagicMock:
    return _mock_response((FIXTURES / name).read_text(encoding="utf-8"))


# ── species_slug ──────────────────────────────────────────────────────────────

def test_species_slug_replaces_spaces():
    assert allaboutbirds.species_slug("Black-capped Chickadee") == "Black-capped_Chickadee"


def test_species_slug_no_change_when_no_spaces():
    assert allaboutbirds.species_slug("Robin") == "Robin"


# ── fetch_browse_species (unit) ───────────────────────────────────────────────

BROWSE_HTML = """
<a href="/guide/Black-capped_Chickadee/overview">Chickadee</a>
<a href="/guide/American_Robin/overview">Robin</a>
<a href="/guide/Song_Sparrow/overview">Sparrow</a>
"""


def test_fetch_browse_species_parses_slugs():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(BROWSE_HTML)):
        result = allaboutbirds.fetch_browse_species("https://www.allaboutbirds.org/guide/browse/...")
    assert result == ["Black-capped_Chickadee", "American_Robin", "Song_Sparrow"]


def test_fetch_browse_species_deduplicates():
    html = BROWSE_HTML + '<a href="/guide/American_Robin/overview">Robin again</a>'
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(html)):
        result = allaboutbirds.fetch_browse_species("https://example.com")
    assert result.count("American_Robin") == 1


def test_fetch_browse_species_respects_limit():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(BROWSE_HTML)):
        result = allaboutbirds.fetch_browse_species("https://example.com", limit=2)
    assert len(result) == 2


def test_fetch_browse_species_constructs_url_from_place_id():
    place_id = "ChIJGzE9DS1l44kRoOhiASS_fHg"
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(BROWSE_HTML)) as mock_get:
        allaboutbirds.fetch_browse_species(place_id)
    called_url = mock_get.call_args[0][0]
    assert place_id in called_url
    assert called_url.startswith("https://")


def test_fetch_browse_species_returns_empty_on_error():
    with patch("avianki.allaboutbirds.requests.get", side_effect=ConnectionError("down")):
        result = allaboutbirds.fetch_browse_species("https://example.com")
    assert result == []


# ── fetch_browse_species (fixture) ────────────────────────────────────────────

@pytest.mark.skipif(not (FIXTURES / "chickadee_browse.html").exists(), reason="fixture missing")
def test_fetch_browse_species_real_page_has_many_species():
    with patch("avianki.allaboutbirds.requests.get", return_value=_fixture_response("chickadee_browse.html")):
        result = allaboutbirds.fetch_browse_species("https://example.com")
    assert "Black-capped_Chickadee" in result
    assert result[0] == "Black-capped_Chickadee"  # most likely species first
    assert len(result) > 10


# ── slug_to_names (unit) ──────────────────────────────────────────────────────

NAMES_HTML = """
<div class="species-info">
  <span class="species-name">Black-capped Chickadee</span>
  <em>Poecile atricapillus</em>
</div>
<title>Black-capped Chickadee Overview, All About Birds…</title>
"""


def test_slug_to_names_parses_common_and_sci_name():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(NAMES_HTML)):
        result = allaboutbirds.slug_to_names("Black-capped_Chickadee")
    assert result["comName"] == "Black-capped Chickadee"
    assert result["sciName"] == "Poecile atricapillus"


def test_slug_to_names_falls_back_to_title_for_com_name():
    html = "<title>American Robin Overview, All About Birds…</title>"
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(html)):
        result = allaboutbirds.slug_to_names("American_Robin")
    assert result["comName"] == "American Robin"
    assert result["sciName"] == ""


def test_slug_to_names_fallback_on_request_error():
    with patch("avianki.allaboutbirds.requests.get", side_effect=ConnectionError("down")):
        result = allaboutbirds.slug_to_names("American_Robin")
    assert result["comName"] == "American Robin"
    assert result["sciName"] == ""


# ── slug_to_names (fixture) ───────────────────────────────────────────────────

@pytest.mark.skipif(not (FIXTURES / "chickadee_overview.html").exists(), reason="fixture missing")
def test_slug_to_names_real_page():
    with patch("avianki.allaboutbirds.requests.get", return_value=_fixture_response("chickadee_overview.html")):
        result = allaboutbirds.slug_to_names("Black-capped_Chickadee")
    assert result["comName"] == "Black-capped Chickadee"
    assert result["sciName"] == "Poecile atricapillus"


# ── fetch_overview (unit) ─────────────────────────────────────────────────────

OVERVIEW_HTML = """
<meta name="description" content="The Black-capped Chickadee is a small bird.">
<div class="species-info">
  <span class="species-name">Black-capped Chickadee</span>
  <em>Poecile atricapillus</em>
</div>
<a href="/guide/photo-gallery/12345">
  <img data-interchange="[https://www.allaboutbirds.org/guide/assets/photo/12345-240px.jpg, small]">
</a>
<a href="/guide/photo-gallery/67890">
  <img data-interchange="[https://www.allaboutbirds.org/guide/assets/photo/67890-240px.jpg, small]">
</a>
"""


def test_fetch_overview_parses_description():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(OVERVIEW_HTML)):
        result = allaboutbirds.fetch_overview("Black-capped_Chickadee")
    assert "Black-capped Chickadee" in result["desc"]


def test_fetch_overview_parses_sci_name():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(OVERVIEW_HTML)):
        result = allaboutbirds.fetch_overview("Black-capped_Chickadee")
    assert result["sciName"] == "Poecile atricapillus"


def test_fetch_overview_constructs_720px_image_urls():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(OVERVIEW_HTML)):
        result = allaboutbirds.fetch_overview("Black-capped_Chickadee")
    assert len(result["images"]) == 2
    assert all("720px" in url for url in result["images"])


def test_fetch_overview_excludes_non_gallery_images():
    html = """
<meta name="description" content="A bird.">
<div class="species-info"><span class="species-name">X</span><em>X x</em></div>
<a href="/guide/maps-range">
  <img data-interchange="[https://www.allaboutbirds.org/guide/assets/photo/99999-720px.jpg, small]">
</a>
"""
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(html)):
        result = allaboutbirds.fetch_overview("Some_Bird")
    assert result["images"] == []


def test_fetch_overview_returns_empty_on_error():
    with patch("avianki.allaboutbirds.requests.get", side_effect=ConnectionError("down")):
        result = allaboutbirds.fetch_overview("Black-capped_Chickadee")
    assert result["desc"] == ""
    assert result["images"] == []


# ── fetch_overview (fixture) ──────────────────────────────────────────────────

@pytest.mark.skipif(not (FIXTURES / "chickadee_overview.html").exists(), reason="fixture missing")
def test_fetch_overview_real_page():
    with patch("avianki.allaboutbirds.requests.get", return_value=_fixture_response("chickadee_overview.html")):
        result = allaboutbirds.fetch_overview("Black-capped_Chickadee")
    assert result["sciName"] == "Poecile atricapillus"
    assert len(result["desc"]) > 50
    assert len(result["images"]) == 2
    assert all("720px" in url for url in result["images"])
    assert all("photo-gallery" not in url for url in result["images"])


# ── fetch_sounds (unit) ───────────────────────────────────────────────────────

SOUNDS_HTML = """
<div class="jp-jplayer player-audio" name="https://www.allaboutbirds.org/guide/assets/sound/111.mp3"></div>
<div class="jp-flat-audio" aria-label="Calls"></div>
<div class="jp-jplayer player-audio" name="https://www.allaboutbirds.org/guide/assets/sound/222.mp3"></div>
<div class="jp-flat-audio" aria-label="Song"></div>
"""


def test_fetch_sounds_separates_calls_and_songs():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response(SOUNDS_HTML)):
        result = allaboutbirds.fetch_sounds("Black-capped_Chickadee")
    assert len(result["calls"]) == 1
    assert len(result["songs"]) == 1
    assert "111.mp3" in result["calls"][0]
    assert "222.mp3" in result["songs"][0]


def test_fetch_sounds_empty_on_no_matches():
    with patch("avianki.allaboutbirds.requests.get", return_value=_mock_response("<html></html>")):
        result = allaboutbirds.fetch_sounds("Black-capped_Chickadee")
    assert result == {"calls": [], "songs": []}


def test_fetch_sounds_returns_empty_on_error():
    with patch("avianki.allaboutbirds.requests.get", side_effect=ConnectionError("down")):
        result = allaboutbirds.fetch_sounds("Black-capped_Chickadee")
    assert result == {"calls": [], "songs": []}


# ── fetch_sounds (fixture) ────────────────────────────────────────────────────

@pytest.mark.skipif(not (FIXTURES / "chickadee_sounds.html").exists(), reason="fixture missing")
def test_fetch_sounds_real_page():
    with patch("avianki.allaboutbirds.requests.get", return_value=_fixture_response("chickadee_sounds.html")):
        result = allaboutbirds.fetch_sounds("Black-capped_Chickadee")
    assert len(result["songs"]) > 0
    assert len(result["calls"]) > 0
    assert all(url.endswith(".mp3") for url in result["songs"] + result["calls"])
