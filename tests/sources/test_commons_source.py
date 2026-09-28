"""Tests for avianki.sources.commons: recorded live responses plus synthetic wikis, no network."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from commons_fakes import (
    COMMONS,
    WIKIDATA,
    WIKIPEDIA,
    CommonsSession,
    Pool,
    add_species,
    audio_page,
    entity,
    file_page,
    lead_page,
    make_client,
    table_of,
)

from avianki.core.http import HttpError, SourceError
from avianki.core.licences import AssetRecord
from avianki.sources.commons import CommonsSource
from avianki.sources.contract import AssetKind, AssetSource, Candidate, FetchedAsset

RECORDED = [
    ("Acanthis flammea", "Lesser Redpoll"),
    ("Accipiter striatus", "Sharp-shinned Hawk"),
    ("Aerodramus bartschi", "Mariana Swiftlet"),
    ("Aethia cristatella", "Crested Auklet"),
    ("Alauda arvensis", "Eurasian Skylark"),
    ("Acridotheres tristis", "Common Myna"),
    ("Actitis hypoleucos", "Common Sandpiper"),
    ("Agelaius phoeniceus", "Red-winged Blackbird"),
]


def source_for(pool: Pool, *rows: tuple[str, ...], override=None, now: datetime | None = None):
    session = CommonsSession(pool, override)
    kw = {"now": now} if now else {}
    src = CommonsSource(make_client(session, **kw), table_of(*rows))  # type: ignore[arg-type]
    return src, session


def recorded_source(**kw: Any):
    return source_for(Pool.recorded(), *RECORDED, **kw)


def fake_names(n: int) -> list[str]:
    """``n`` distinct, purely alphabetic binomials."""
    return [f"Genus {chr(97 + i // 26 // 26)}{chr(97 + i // 26 % 26)}{chr(97 + i % 26)}" for i in range(n)]


def ids_of(names: str) -> str:
    return names.lower().replace(" ", "-")


def one(cands: dict[str, list[Candidate]], sid: str) -> Candidate:
    assert len(cands[sid]) == 1
    return cands[sid][0]


# ── contract surface ─────────────────────────────────────────────────────────


def test_declared_capabilities():
    src, _ = recorded_source()
    assert isinstance(src, AssetSource)
    assert src.name == "commons"
    assert src.supplies == {AssetKind.PHOTO, AssetKind.AUDIO}
    assert src.republishable is True
    assert (src.limits.requests_per_second, src.limits.max_concurrency) == (1, 1)
    assert src.limits.daily_request_budget is None and src.limits.needs_secret is None


def test_unsupported_kind_is_a_programming_error():
    src, _ = recorded_source()
    with pytest.raises(ValueError):
        src.candidates(["alauda-arvensis"], AssetKind.DESCRIPTION, 1)


def test_nothing_asked_nothing_requested():
    src, session = recorded_source()
    assert src.candidates([], AssetKind.PHOTO, 1) == {}
    assert src.candidates(["alauda-arvensis"], AssetKind.PHOTO, 0) == {}
    assert session.calls == []


def test_unknown_species_id_is_the_callers_bug():
    src, _ = recorded_source()
    with pytest.raises(KeyError):
        src.candidates(["nope-nope"], AssetKind.PHOTO, 1)


# ── photos: recorded responses ───────────────────────────────────────────────

PHOTO_IDS = [
    "acanthis-flammea", "accipiter-striatus", "aerodramus-bartschi", "aethia-cristatella",
    "alauda-arvensis", "acridotheres-tristis",
]


def test_recorded_photos_yield_exactly_the_safe_lead_images():
    src, _ = recorded_source()
    got = src.candidates(PHOTO_IDS, AssetKind.PHOTO, 3)
    assert sorted(got) == ["accipiter-striatus", "acridotheres-tristis", "alauda-arvensis"]
    # Why the others are absent, by reason.
    assert src.stats["taxon-guard"] == 1  # Redpoll's item is the genus Acanthis
    assert src.stats["photo-small"] == 1  # Mariana swiftlet 667x501
    assert src.stats["photo-licence"] == 1  # Crested auklet: "pd" is not an allowed licence id
    assert set(src.guard_drops) == {"acanthis-flammea"}


def test_a_photo_candidate_carries_the_full_licence_record():
    src, _ = recorded_source()
    c = one(src.candidates(PHOTO_IDS, AssetKind.PHOTO, 1), "accipiter-striatus")
    assert (c.species_id, c.kind, c.token) == ("accipiter-striatus", AssetKind.PHOTO, "M49149910")
    assert (c.width, c.height) == (2178, 3132)  # the original's size, for the 800 px filter
    r = c.record
    assert isinstance(r, AssetRecord)
    assert r.source == "commons" and r.source_asset_id == "M49149910"
    assert r.licence_id == "CC0-1.0" and r.licence_url == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert r.creator == "ALAN SCHMIERER"
    assert r.creator_url == "https://www.flickr.com/people/8101022@N05"  # the Artist link, as the file gives it
    assert r.title == "Accipiter striatus, Canet Road, San Luis Obispo 1"
    assert r.source_url == "https://commons.wikimedia.org/wiki/File:Accipiter_striatus,_Canet_Road,_San_Luis_Obispo_1.jpg"
    assert r.file_url.startswith("https://") and "960px-" in r.file_url  # the 960 px rendition
    assert r.retrieved_at == "2026-09-28"
    assert r.source_terms_version is None
    assert r.restrictions is None and r.copyright_notice is None
    assert r.missing_required_fields() == []


def test_creator_comes_from_the_artist_not_the_uploader_and_user_prefix_is_dropped():
    src, _ = recorded_source()
    r = one(src.candidates(PHOTO_IDS, AssetKind.PHOTO, 1), "alauda-arvensis").record
    assert r.licence_id == "CC-BY-SA-3.0"
    assert r.creator == "Diliff"
    assert r.creator_url == "https://commons.wikimedia.org/wiki/User:Diliff"


def test_retrieved_at_is_the_injected_clocks_date():
    src, _ = recorded_source(now=datetime(2027, 1, 2, 0, 30, tzinfo=timezone.utc))
    c = one(src.candidates(["accipiter-striatus"], AssetKind.PHOTO, 1), "accipiter-striatus")
    assert c.record.retrieved_at == "2027-01-02"


def test_a_species_batch_costs_one_request_per_api_and_uses_etiquette_params():
    src, session = recorded_source()
    src.candidates(PHOTO_IDS, AssetKind.PHOTO, 1)
    assert [u for u, _ in session.calls] == [WIKIPEDIA, WIKIDATA, COMMONS]
    for _, params in session.calls:
        assert params["maxlag"] == 5 and params["format"] == "json" and params["formatversion"] == 2
    wiki = session.requests_to(WIKIPEDIA)[0]
    assert wiki["titles"].count("|") == 5 and wiki["redirects"] == 1
    assert wiki["prop"] == "pageimages|pageprops" and wiki["piprop"] == "name"
    ii = session.requests_to(COMMONS)[0]
    assert ii["iiurlwidth"] == 960 and ii["prop"] == "imageinfo"
    assert set(ii["iiprop"].split("|")) == {"url", "size", "mime", "extmetadata", "user", "mediatype"}
    assert "License" in ii["iiextmetadatafilter"]


def test_requests_carry_no_email_address():
    src, session = recorded_source()
    src.candidates(PHOTO_IDS, AssetKind.PHOTO, 1)
    assert "@" not in repr(session.calls)


def test_wikipedia_title_wins_over_the_scientific_name():
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Redpoll (bird)", "Redpoll 1.jpg", "Q1"))
    pool.entities["Q1"] = entity("Q1", "Acanthis flammea")
    pool.commons_pages.append(file_page(9, "Redpoll 1.jpg"))
    src, session = source_for(pool, ("Acanthis flammea", "Redpoll", "Redpoll (bird)"))
    assert sorted(src.candidates(["acanthis-flammea"], AssetKind.PHOTO, 1)) == ["acanthis-flammea"]
    assert session.requests_to(WIKIPEDIA)[0]["titles"] == "Redpoll (bird)"


def test_alias_ids_are_answered_under_the_id_that_was_asked():
    from avianki.taxonomy.species import SpeciesRow, SpeciesTable

    pool = Pool()
    add_species(pool, "Turdus migratorius", pageid=10)
    table = SpeciesTable([
        SpeciesRow("turdus-migratorius", "Turdus migratorius", "American Robin"),
        SpeciesRow("old-name", "Old name", "Old", alias_of="turdus-migratorius"),
    ])
    src = CommonsSource(make_client(CommonsSession(pool)), table)
    assert list(src.candidates(["old-name"], AssetKind.PHOTO, 1)) == ["old-name"]


def test_more_than_fifty_species_are_batched_serially():
    pool = Pool()
    names = fake_names(120)
    for i, name in enumerate(names):
        add_species(pool, name, pageid=100 + i)
    src, session = source_for(pool, *[(n, n) for n in names])
    got = src.candidates([ids_of(n) for n in names], AssetKind.PHOTO, 1)
    assert len(got) == 120
    assert [len(p["titles"].split("|")) for p in session.requests_to(WIKIPEDIA)] == [50, 50, 20]
    assert [len(p["ids"].split("|")) for p in session.requests_to(WIKIDATA)] == [50, 50, 20]
    assert [len(p["titles"].split("|")) for p in session.requests_to(COMMONS)] == [50, 50, 20]


def test_a_photo_candidate_per_species_even_when_more_are_asked_for():
    src, _ = recorded_source()
    got = src.candidates(PHOTO_IDS, AssetKind.PHOTO, 5)
    assert all(len(v) == 1 for v in got.values())


# ── photos: absence ──────────────────────────────────────────────────────────


def photo_world(**kw: Any) -> tuple[CommonsSource, CommonsSession]:
    pool = Pool()
    add_species(pool, "Turdus migratorius", pageid=10, **kw)
    return source_for(pool, ("Turdus migratorius", "American Robin"))


def test_a_well_formed_synthetic_species_gets_a_candidate():
    src, _ = photo_world()
    c = one(src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1), "turdus-migratorius")
    assert c.record.creator == "Jane Doe" and c.record.licence_id == "CC-BY-SA-4.0"


def test_no_article_is_absence():
    pool = Pool()
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert src.stats["no-article"] == 1


def test_disambiguation_page_is_absence():
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Turdus migratorius", "X.jpg", "Q1", disambiguation=True))
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert src.stats["disambiguation"] == 1


def test_article_without_a_lead_image_is_absence():
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Turdus migratorius", None, "Q1"))
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert src.stats["no-lead-image"] == 1


def test_article_without_a_wikidata_item_cannot_pass_the_guard():
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Turdus migratorius", "X.jpg", None))
    src, session = source_for(pool, ("Turdus migratorius", "American Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert src.stats["no-wikidata-item"] == 1
    assert session.requests_to(WIKIDATA) == []  # nothing to ask


def test_lead_image_that_is_not_on_commons_is_absence():
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Turdus migratorius", "Local only.jpg", "Q1"))
    pool.entities["Q1"] = entity("Q1", "Turdus migratorius")
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert src.stats["not-on-commons"] == 1


@pytest.mark.parametrize(
    "names",
    [
        ("Acanthis",),  # a genus article, like Redpoll
        ("Turdus merula",),  # another species
        (),  # an item with no taxon name at all
    ],
)
def test_taxon_guard_rejects_an_article_about_something_else(names: tuple[str, ...]):
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Redpoll", "X.jpg", "Q1"))
    pool.entities["Q1"] = entity("Q1", *names)
    pool.commons_pages.append(file_page(9, "X.jpg"))
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin", "Redpoll"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert "turdus-migratorius" in src.guard_drops


def test_taxon_guard_ignores_case_and_whitespace_and_deprecated_names():
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Robin", "X.jpg", "Q1"))
    pool.entities["Q1"] = entity("Q1", "  turdus   MIGRATORIUS ")
    pool.commons_pages.append(file_page(9, "X.jpg"))
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin", "Robin"))
    assert list(src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1)) == ["turdus-migratorius"]

    pool.entities["Q1"] = entity("Q1", "Turdus migratorius", rank="deprecated")
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin", "Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}


def test_a_missing_wikidata_item_is_a_guard_failure():
    pool = Pool()
    pool.wikipedia_pages.append(lead_page(1, "Turdus migratorius", "X.jpg", "Q404"))
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert "no such item" in src.guard_drops["turdus-migratorius"]


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"mime": "image/svg+xml"}, "photo-mime"),
        ({"mime": "image/gif"}, "photo-mime"),
        ({"mime": "application/pdf", "mediatype": "OFFICE"}, "photo-mime"),
        ({"mime": "image/tiff"}, "photo-mime"),
        ({"width": 799, "height": 500}, "photo-small"),
        ({"width": 500, "height": 799}, "photo-small"),
        ({"restrictions": "trademarked"}, "photo-restrictions"),
        ({"licence": "cc-by-nc-4.0", "short": "CC BY-NC 4.0"}, "photo-licence"),
        ({"licence": "cc-by-nd-4.0", "short": "CC BY-ND 4.0"}, "photo-licence"),
        ({"licence": "cc-by-sa-3.0-de", "short": "CC BY-SA 3.0 DE"}, "photo-licence"),
        ({"licence": "gfdl", "short": "GFDL"}, "photo-licence"),
        ({"licence": "pd", "short": "Public domain"}, "photo-licence"),
        ({"licence": None, "short": None}, "photo-licence"),
        ({"licence": "cc-by-4.0", "short": "CC BY-SA 4.0"}, "photo-licence"),  # fields disagree
        ({"artist": None, "credit": "Flickr", "user": "Uploader"}, "photo-credit"),
        ({"artist": "", "credit": None, "user": None}, "photo-credit"),
        ({"artist": "Unknown", "credit": "Flickr"}, "photo-credit"),
        ({"categories": "Birds|Bird illustrations"}, "photo-not-photo"),
        ({"categories": "Birds|Paintings of birds"}, "photo-not-photo"),
        ({"categories": "Turdus migratorius|Taxidermy specimens"}, "photo-not-photo"),
        ({"categories": "Turdus migratorius eggs"}, "photo-not-photo"),
    ],
)
def test_photo_gates_reject_with_a_reason(kw: dict[str, Any], reason: str):
    src, _ = photo_world(**kw)
    assert src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1) == {}
    assert src.stats[reason] == 1


def test_exactly_800_px_long_side_passes():
    src, _ = photo_world(width=800, height=100)
    assert "turdus-migratorius" in src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1)


def test_allowlisted_licences_all_pass():
    for licence, short, expected in [
        ("cc0", "CC0", "CC0-1.0"),
        ("cc-by-2.0", "CC BY 2.0", "CC-BY-2.0"),
        ("cc-by-2.5", "CC BY 2.5", "CC-BY-2.5"),
        ("cc-by-sa-2.5", "CC BY-SA 2.5", "CC-BY-SA-2.5"),
        ("cc-by-4.0", "CC BY 4.0", "CC-BY-4.0"),
    ]:
        src, _ = photo_world(licence=licence, short=short)
        c = one(src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1), "turdus-migratorius")
        assert c.record.licence_id == expected


# ── credit chain ─────────────────────────────────────────────────────────────


def creator_of(**kw: Any) -> AssetRecord | None:
    src, _ = photo_world(**kw)
    got = src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1)
    return got["turdus-migratorius"][0].record if got else None


def test_creator_falls_back_to_plain_text_artist():
    r = creator_of(artist="John Smith", credit="Flickr")
    assert r is not None and (r.creator, r.creator_url) == ("John Smith", None)


def test_mediawikis_assumed_author_boilerplate_is_not_a_name():
    r = creator_of(artist="No machine-readable author provided. <a href=\"//commons.wikimedia.org/wiki/User:Mdf\">Mdf</a> assumed (based on copyright claims).")
    assert r is not None and r.creator == "Mdf"
    r = creator_of(artist="No machine-readable author provided. Own work assumed (based on copyright claims).", credit="Flickr")
    assert r is None


def test_attribution_field_is_the_next_fallback():
    r = creator_of(artist=None, attribution="Photo: A. Photographer / Somewhere", credit="Flickr")
    assert r is not None and r.creator == "Photo: A. Photographer / Somewhere"
    assert r.attribution_text == "Photo: A. Photographer / Somewhere"


def test_uploader_is_credited_only_for_own_work():
    r = creator_of(artist=None, credit="Own work", user="Uploader Name")
    assert r is not None and r.creator == "Uploader Name"
    assert r.creator_url == "https://commons.wikimedia.org/wiki/User:Uploader_Name"
    assert creator_of(artist=None, credit="From Flickr", user="Uploader Name") is None


def test_creator_text_is_data_never_markup():
    hostile = (
        '<script>alert(1)</script><a href="javascript:alert(2)">Eve <b>Bold</b>&nbsp;&amp;\x00 Co</a>'
        '<img src=x onerror="alert(3)">'
    )
    r = creator_of(artist=hostile)
    assert r is not None
    assert r.creator == "Eve Bold & Co"
    assert r.creator_url is None  # javascript: links are not stored
    assert "<" not in (r.creator or "") and "\x00" not in (r.creator or "")


def test_protocol_relative_and_absolute_artist_links_become_https_urls():
    r = creator_of(artist='<a href="https://www.flickr.com/people/abc/">A B</a>')
    assert r is not None and r.creator_url == "https://www.flickr.com/people/abc/"
    r = creator_of(artist='<a href="mailto:a@b.c">A B</a>')
    assert r is not None and r.creator_url is None


def test_title_falls_back_to_the_file_name_and_is_present_for_pre_4_0_licences():
    r = creator_of(licence="cc-by-sa-3.0", short="CC BY-SA 3.0", object_name=None)
    assert r is not None and r.title == "Turdus migratorius 1"
    r = creator_of(licence="cc-by-sa-3.0", short="CC BY-SA 3.0", object_name="  A <i>fine</i> robin ")
    assert r is not None and r.title == "A fine robin"


# ── failure is never absence ─────────────────────────────────────────────────


def _boom(url_part: str, answer: Any):
    def override(url: str, params: Any) -> Any:
        return answer if url_part in url else None

    return override


@pytest.mark.parametrize("host", ["en.wikipedia.org", "wikidata.org", "commons.wikimedia.org"])
@pytest.mark.parametrize("status", [429, 500, 503, 404])
def test_http_errors_on_any_api_are_source_errors(host: str, status: int):
    pool = Pool()
    add_species(pool, "Turdus migratorius", pageid=10)
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"), override=_boom(host, (status, {"x": 1})))
    with pytest.raises(HttpError):
        src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1)


@pytest.mark.parametrize("host", ["en.wikipedia.org", "wikidata.org", "commons.wikimedia.org"])
def test_maxlag_and_api_errors_are_source_errors(host: str):
    pool = Pool()
    add_species(pool, "Turdus migratorius", pageid=10)
    lag = {"error": {"code": "maxlag", "info": "Waiting for a database server: 6.4 seconds lagged."}}
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"), override=_boom(host, lag))
    with pytest.raises(SourceError, match="maxlag"):
        src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1)


@pytest.mark.parametrize(
    ("host", "body"),
    [
        ("en.wikipedia.org", {"batchcomplete": True}),  # no query
        ("en.wikipedia.org", {"query": {"pages": "nope"}}),
        ("en.wikipedia.org", ["not", "an", "object"]),
        ("wikidata.org", {"success": 1}),  # no entities
        ("wikidata.org", {"entities": {}}),  # drops the requested item
        ("commons.wikimedia.org", {"query": {}}),
        ("commons.wikimedia.org", {"query": {"pages": []}}),  # drops the requested file
    ],
)
def test_missing_expected_structure_is_a_source_error(host: str, body: Any):
    pool = Pool()
    add_species(pool, "Turdus migratorius", pageid=10)
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"), override=_boom(host, body))
    with pytest.raises(SourceError):
        src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1)


def test_a_malformed_json_body_is_a_source_error():
    pool = Pool()
    add_species(pool, "Turdus migratorius", pageid=10)
    src, _ = source_for(pool, ("Turdus migratorius", "American Robin"), override=_boom("wikipedia", (200, b"<html>")))
    with pytest.raises(SourceError):
        src.candidates(["turdus-migratorius"], AssetKind.PHOTO, 1)


def test_one_failed_batch_fails_the_whole_call():
    pool = Pool()
    names = fake_names(60)
    for i, name in enumerate(names):
        add_species(pool, name, pageid=100 + i)
    seen = {"n": 0}

    def override(url: str, params: Any) -> Any:
        if url == WIKIPEDIA:
            seen["n"] += 1
            if seen["n"] == 2:
                return (500, {})
        return None

    src, _ = source_for(pool, *[(n, n) for n in names], override=override)
    with pytest.raises(SourceError):
        src.candidates([ids_of(n) for n in names], AssetKind.PHOTO, 1)


# ── audio ────────────────────────────────────────────────────────────────────


def audio_world(files: list[dict[str, Any]] | list[list[dict[str, Any]]], sci: str = "Turdus migratorius") -> tuple[CommonsSource, CommonsSession]:
    pool = Pool()
    pool.categoryinfo.append({"pageid": 1, "ns": 14, "title": f"Category:Audio files of {sci}",
                              "categoryinfo": {"size": 9, "pages": 0, "files": 9, "subcats": 0, "hidden": False}})
    batches = files if files and isinstance(files[0], list) else [files]
    pool.members[f"Category:Audio files of {sci}"] = batches  # type: ignore[assignment]
    for batch in batches:
        pool.commons_pages += batch  # type: ignore[arg-type]
    return source_for(pool, (sci, "Robin"))


def recordings(src: CommonsSource, limit: int = 10) -> list[Candidate]:
    return src.candidates(["turdus-migratorius"], AssetKind.AUDIO, limit).get("turdus-migratorius", [])


def test_recorded_audio_candidates_are_gated_ranked_and_capped():
    src, _ = recorded_source()
    got = src.candidates(["alauda-arvensis", "acridotheres-tristis", "actitis-hypoleucos", "agelaius-phoeniceus",
                          "accipiter-striatus"], AssetKind.AUDIO, 2)
    assert "accipiter-striatus" not in got  # no audio category: absence, not an error
    assert src.stats["no-audio-category"] == 1
    assert all(1 <= len(v) <= 2 for v in got.values())
    for cands in got.values():
        for c in cands:
            assert c.kind is AssetKind.AUDIO and c.token == c.record.source_asset_id
            assert c.record.licence_id in {"CC-BY-SA-3.0", "CC-BY-SA-4.0", "CC-BY-4.0", "CC-BY-3.0", "CC0-1.0"}
            assert c.record.creator and c.record.missing_required_fields() == []
            assert c.record.file_url.startswith("https://upload.wikimedia.org/")
            assert (c.width, c.height) == (None, None)
    # Rejections seen in the recorded data.
    assert src.stats["audio-licence"] >= 3  # "pd" files (Red-winged blackbird)
    assert src.stats["audio-duration"] >= 1  # 2.9 s and 2169 s myna files
    assert src.stats["audio-credit"] >= 1  # W1CDR files with no creator


def test_audio_needs_the_exact_species_category():
    good = audio_page(11, "Robin A.ogg", "Turdus migratorius")
    other = audio_page(12, "Not a robin.ogg", "Turdus migratorius", categories="Audio files of Turdus merula")
    none = audio_page(13, "Uncategorised.ogg", "Turdus migratorius", categories="Birds of Ontario")
    mixed = audio_page(14, "Two species.ogg", "Turdus migratorius",
                       categories="Audio files of Turdus migratorius|Audio files of Turdus merula")
    src, _ = audio_world([good, other, none, mixed])
    assert [c.token for c in recordings(src)] == ["M11"]
    assert src.stats["audio-category"] == 2 and src.stats["audio-mixed-species"] == 1


def test_audio_species_absent_when_no_category_or_nothing_usable():
    src, _ = audio_world([audio_page(11, "Bad.ogg", "Turdus migratorius", licence="cc-by-nc-4.0", short="CC BY-NC 4.0")])
    assert src.candidates(["turdus-migratorius"], AssetKind.AUDIO, 3) == {}
    assert src.stats["no-usable-audio"] == 1

    pool = Pool()
    src, _ = source_for(pool, ("Turdus migratorius", "Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.AUDIO, 3) == {}
    assert src.stats["no-audio-category"] == 1


def test_empty_category_is_absence():
    pool = Pool()
    pool.categoryinfo.append({"pageid": 1, "ns": 14, "title": "Category:Audio files of Turdus migratorius",
                              "categoryinfo": {"size": 0, "pages": 0, "files": 0, "subcats": 0, "hidden": False}})
    src, session = source_for(pool, ("Turdus migratorius", "Robin"))
    assert src.candidates(["turdus-migratorius"], AssetKind.AUDIO, 3) == {}
    assert len(session.calls) == 1  # no member listing for an empty category


@pytest.mark.parametrize(
    ("kw", "accepted"),
    [
        ({"mime": "application/ogg"}, True),
        ({"mime": "audio/ogg"}, True),
        ({"mime": "audio/opus"}, True),
        ({"mime": "audio/wav"}, True),
        ({"mime": "audio/x-wav"}, True),
        ({"mime": "audio/mpeg"}, True),
        ({"mime": "audio/flac"}, True),
        ({"mime": "video/ogg", "mediatype": "AUDIO"}, True),
        ({"mime": "video/ogg", "mediatype": "VIDEO"}, False),
        ({"mime": "audio/midi"}, False),
        ({"mime": "audio/webm"}, False),
        ({"mime": "application/pdf", "mediatype": "OFFICE"}, False),
        ({"mime": "audio/ogg", "mediatype": "BITMAP"}, False),
        ({"duration": 2.9}, False),
        ({"duration": 3.0}, True),
        ({"duration": 600.0}, True),
        ({"duration": 600.5}, False),
        ({"restrictions": "x"}, False),
        ({"artist": None, "credit": "Xeno-canto", "user": "Fae"}, False),
    ],
)
def test_audio_gates(kw: dict[str, Any], accepted: bool):
    src, _ = audio_world([audio_page(11, "Robin.ogg", "Turdus migratorius", **kw)])
    assert bool(recordings(src)) is accepted


def test_speech_and_pronunciations_are_not_recordings():
    ll = audio_page(11, "LL-Q1860 (eng)-Someone-robin.wav", "Turdus migratorius", mime="audio/wav")
    cat = audio_page(12, "Say it.wav", "Turdus migratorius", mime="audio/wav",
                     categories="Audio files of Turdus migratorius|Lingua Libre pronunciation")
    ok = audio_page(13, "Song.ogg", "Turdus migratorius")
    src, _ = audio_world([ll, cat, ok])
    assert [c.token for c in recordings(src)] == ["M13"]
    assert src.stats["audio-not-recording"] == 2


def test_audio_ranking_rule():
    files = [
        audio_page(1, "long.ogg", "Turdus migratorius", duration=400.0, licence="cc-by-4.0", short="CC BY 4.0"),
        audio_page(2, "tiny.ogg", "Turdus migratorius", duration=5.0, licence="cc0", short="CC0"),
        audio_page(3, "sa-good.ogg", "Turdus migratorius", duration=60.0),
        audio_page(4, "by-good.ogg", "Turdus migratorius", duration=30.0, licence="cc-by-4.0", short="CC BY 4.0"),
        audio_page(5, "cc0-good.ogg", "Turdus migratorius", duration=15.0, licence="cc0", short="CC0"),
        audio_page(6, "sa-good-2.ogg", "Turdus migratorius", duration=100.0),
        audio_page(7, "mid.ogg", "Turdus migratorius", duration=200.0, licence="cc-by-4.0", short="CC BY 4.0"),
    ]
    src, _ = audio_world(files)
    # bucket (10-120 s) first: CC0, then BY, then BY-SA (longer first); then 120-300 s, <10 s, >300 s.
    assert [c.token for c in recordings(src)] == ["M5", "M4", "M6", "M3", "M7", "M2", "M1"]
    assert [c.token for c in recordings(src, limit=2)] == ["M5", "M4"]


def test_the_same_xeno_canto_recording_is_offered_once():
    files = [
        audio_page(1, "Turdus migratorius - American Robin - XC123456.ogg", "Turdus migratorius"),
        audio_page(2, "Turdus migratorius - American Robin - XC123456.mp3", "Turdus migratorius", mime="audio/mpeg"),
        audio_page(3, "Turdus migratorius - American Robin - XC777.ogg", "Turdus migratorius"),
    ]
    src, _ = audio_world(files)
    assert [c.token for c in recordings(src)] == ["M1", "M3"]
    assert src.stats["audio-duplicate"] == 1


def test_category_listing_follows_continuation_and_ignores_repeats():
    page1 = [audio_page(1, "a.ogg", "Turdus migratorius", duration=20.0)]
    page2 = [audio_page(1, "a.ogg", "Turdus migratorius", duration=20.0), audio_page(2, "b.ogg", "Turdus migratorius", duration=30.0)]
    src, session = audio_world([page1, page2])
    assert sorted(c.token for c in recordings(src)) == ["M1", "M2"]
    member_calls = [p for p in session.requests_to(COMMONS) if "generator" in p]
    assert len(member_calls) == 2 and "gcmcontinue" in member_calls[1]


def test_category_listing_stops_after_three_pages():
    batches = [[audio_page(10 * i + 1, f"f{i}.ogg", "Turdus migratorius")] for i in range(1, 6)]
    src, session = audio_world(batches)
    assert len(recordings(src)) == 3
    assert len([p for p in session.requests_to(COMMONS) if "generator" in p]) == 3


def test_audio_categories_are_checked_in_one_batched_request():
    pool = Pool()
    names = fake_names(70)
    src, session = source_for(pool, *[(n, n) for n in names])
    src.candidates([ids_of(n) for n in names], AssetKind.AUDIO, 1)
    sizes = [len(p["titles"].split("|")) for p in session.requests_to(COMMONS)]
    assert sizes == [50, 20]
    assert all(p["prop"] == "categoryinfo" and p["maxlag"] == 5 for p in session.requests_to(COMMONS))


@pytest.mark.parametrize("status", [500, 429])
@pytest.mark.parametrize("stage", ["categoryinfo", "members"])
def test_audio_http_errors_are_source_errors(status: int, stage: str):
    src, session = audio_world([audio_page(1, "a.ogg", "Turdus migratorius")])
    assert recordings(src)  # control: the same world works

    def override(url: str, params: Any) -> Any:
        hit = params.get("prop") == "categoryinfo" if stage == "categoryinfo" else "generator" in params
        return (status, {}) if hit else None

    session.override = override
    with pytest.raises(HttpError):
        recordings(src)


def test_audio_response_without_pages_is_a_source_error():
    files = [audio_page(1, "a.ogg", "Turdus migratorius")]
    pool_src, session = audio_world(files)
    session.override = lambda url, params: {"query": {"nope": 1}} if "generator" in params else None
    with pytest.raises(SourceError):
        recordings(pool_src)


def test_audio_api_error_body_is_a_source_error():
    src, session = audio_world([audio_page(1, "a.ogg", "Turdus migratorius")])
    session.override = lambda url, params: {"error": {"code": "maxlag", "info": "lagged"}} if "generator" in params else None
    with pytest.raises(SourceError, match="maxlag"):
        recordings(src)


# ── fetch ────────────────────────────────────────────────────────────────────


def fetchable(kind: AssetKind, content_type: str, body: bytes = b"\xff\xd8\xff data", status: int = 200):
    if kind is AssetKind.PHOTO:
        src, session = photo_world()
        cand = one(src.candidates(["turdus-migratorius"], kind, 1), "turdus-migratorius")
    else:
        src, session = audio_world([audio_page(11, "Robin.ogg", "Turdus migratorius")])
        cand = recordings(src)[0]
    session.pool.downloads[cand.record.file_url] = (status, body, content_type)
    return src, session, cand


def test_fetch_returns_the_bytes_and_the_same_record():
    src, session, cand = fetchable(AssetKind.PHOTO, "image/jpeg; charset=binary")
    got = src.fetch(cand)
    assert isinstance(got, FetchedAsset)
    assert got.data == b"\xff\xd8\xff data" and got.content_type == "image/jpeg"
    assert got.record == cand.record and got.candidate is cand
    assert session.calls[-1][0] == cand.record.file_url


def test_fetching_audio_accepts_ogg_and_rejects_html():
    src, _, cand = fetchable(AssetKind.AUDIO, "application/ogg", b"OggS....")
    assert src.fetch(cand).content_type == "application/ogg"
    src, _, cand = fetchable(AssetKind.AUDIO, "text/html", b"<html>")
    with pytest.raises(SourceError, match="not audio"):
        src.fetch(cand)


@pytest.mark.parametrize("content_type", ["text/html; charset=utf-8", "", "application/json", "image/svg+xml", "audio/ogg"])
def test_fetching_a_photo_that_is_not_an_image_fails(content_type: str):
    src, _, cand = fetchable(AssetKind.PHOTO, content_type, b"<html>error</html>")
    with pytest.raises(SourceError):
        src.fetch(cand)


def test_fetching_an_empty_body_fails():
    src, _, cand = fetchable(AssetKind.PHOTO, "image/jpeg", b"")
    with pytest.raises(SourceError, match="empty"):
        src.fetch(cand)


@pytest.mark.parametrize("status", [404, 429, 500])
def test_download_http_errors_are_source_errors(status: int):
    src, _, cand = fetchable(AssetKind.PHOTO, "image/jpeg", b"x", status=status)
    with pytest.raises(HttpError):
        src.fetch(cand)


# ── pins ─────────────────────────────────────────────────────────────────────


def pin_source(*pages: dict[str, Any], rows: tuple[tuple[str, str], ...] = (("Turdus migratorius", "American Robin"),)):
    pool = Pool()
    pool.commons_pages += list(pages)
    return source_for(pool, *rows)


def test_pinning_a_photo_rebuilds_the_candidate_and_infers_the_species():
    page = file_page(4242, "Robin pinned.jpg", categories="Birds of Ontario|Turdus migratorius|Photographs by Jane")
    src, session = pin_source(page)
    c = src.resolve_pin("M4242")
    assert (c.species_id, c.kind, c.token) == ("turdus-migratorius", AssetKind.PHOTO, "M4242")
    assert (c.width, c.height) == (1600, 1200)
    assert c.record.source_asset_id == "M4242" and c.record.retrieved_at == "2026-09-28"
    assert session.requests_to(COMMONS)[0]["pageids"] == 4242


def test_pinning_audio_infers_the_species_from_its_audio_category():
    src, _ = pin_source(audio_page(77, "Pinned song.ogg", "Turdus migratorius"))
    c = src.resolve_pin("M77")
    assert (c.species_id, c.kind) == ("turdus-migratorius", AssetKind.AUDIO)


def test_a_pin_skips_the_heuristics_but_not_the_gates():
    small = file_page(1, "Small.jpg", width=300, height=200, categories="Turdus migratorius|Bird illustrations")
    src, _ = pin_source(small)
    assert src.resolve_pin("M1").width == 300  # curators may choose small or unusual images

    short = audio_page(2, "Short.ogg", "Turdus migratorius", duration=1.0)
    src, _ = pin_source(short)
    assert src.resolve_pin("M2").kind is AssetKind.AUDIO

    for page in (
        file_page(3, "NC.jpg", licence="cc-by-nc-4.0", short="CC BY-NC 4.0", categories="Turdus migratorius"),
        file_page(4, "Restricted.jpg", restrictions="personality", categories="Turdus migratorius"),
        file_page(5, "Uncredited.jpg", artist=None, credit="Flickr", categories="Turdus migratorius"),
        file_page(6, "Svg.svg", mime="image/svg+xml", categories="Turdus migratorius"),
        audio_page(7, "NC.ogg", "Turdus migratorius", licence="cc-by-nc-4.0", short="CC BY-NC 4.0"),
    ):
        src, _ = pin_source(page)
        with pytest.raises(SourceError, match="not usable"):
            src.resolve_pin(f"M{page['pageid']}")


def test_a_pin_that_no_longer_resolves_is_a_source_error():
    src, _ = pin_source()
    with pytest.raises(SourceError, match="no longer exists"):
        src.resolve_pin("M999")
    gone = {"pageid": 5, "ns": 6, "title": "File:Gone.jpg", "imagerepository": ""}  # deleted: no imageinfo
    src, _ = pin_source(gone)
    with pytest.raises(SourceError, match="no longer exists"):
        src.resolve_pin("M5")


@pytest.mark.parametrize("token", ["", "12345", "M", "M0", "M-3", "Mabc", "M12 34", "m123", "File:Foo.jpg", "M1|M2"])
def test_malformed_pin_tokens_are_refused_without_a_request(token: str):
    src, session = pin_source()
    with pytest.raises(SourceError, match="not a Commons pin token"):
        src.resolve_pin(token)
    assert session.calls == []


def test_pin_species_must_be_known_or_given_and_must_not_conflict():
    page = file_page(8, "Unlabelled.jpg", categories="Birds of Ontario")
    src, _ = pin_source(page, rows=(("Turdus migratorius", "American Robin"), ("Turdus merula", "Blackbird")))
    with pytest.raises(SourceError, match="pass species_id"):
        src.resolve_pin("M8")
    assert src.resolve_pin("M8", species_id="turdus-merula").species_id == "turdus-merula"

    labelled = file_page(9, "Labelled.jpg", categories="Turdus migratorius")
    src, _ = pin_source(labelled, rows=(("Turdus migratorius", "American Robin"), ("Turdus merula", "Blackbird")))
    with pytest.raises(SourceError, match="not 'turdus-merula'"):
        src.resolve_pin("M9", species_id="turdus-merula")
    assert src.resolve_pin("M9", species_id="turdus-migratorius").species_id == "turdus-migratorius"


def test_pin_response_errors_are_source_errors():
    src, session = pin_source(file_page(1, "A.jpg", categories="Turdus migratorius"))
    session.override = lambda url, params: (500, {})
    with pytest.raises(HttpError):
        src.resolve_pin("M1")
    session.override = lambda url, params: {"query": {"pages": []}}
    with pytest.raises(SourceError):
        src.resolve_pin("M1")
