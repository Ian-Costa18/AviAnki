"""Tests for avianki.core.licences: the exact allowlist and the per-asset record."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, fields

import pytest

from avianki.core.licences import (
    ALLOWED_LICENCES,
    AssetRecord,
    is_allowed,
    licence_url,
    normalise_licence,
    resolve_licence,
    title_required,
)

SECTION_5_1_FIELDS = [
    "source",
    "source_asset_id",
    "source_url",
    "file_url",
    "licence_id",
    "licence_url",
    "creator",
    "creator_url",
    "attribution_text",
    "title",
    "copyright_notice",
    "modifications",
    "prior_modifications",
    "restrictions",
    "retrieved_at",
    "source_terms_version",
]


def test_allowlist_is_exact():
    assert ALLOWED_LICENCES == frozenset(
        {
            "CC0-1.0",
            "PDM-1.0",
            "CC-BY-2.0",
            "CC-BY-2.5",
            "CC-BY-3.0",
            "CC-BY-4.0",
            "CC-BY-SA-2.0",
            "CC-BY-SA-2.5",
            "CC-BY-SA-3.0",
            "CC-BY-SA-4.0",
        }
    )


@pytest.mark.parametrize(
    "licence_id, expected",
    [("CC-BY-4.0", True), ("CC0-1.0", True), ("cc-by-4.0", False), ("CC-BY", False), ("CC-BY-NC-4.0", False), ("", False)],
)
def test_is_allowed_is_exact_membership(licence_id, expected):
    assert is_allowed(licence_id) is expected


INAT = "inaturalist"
COMMONS = "commons"


@pytest.mark.parametrize(
    "raw, source, expected",
    [
        # iNaturalist codes
        ("cc0", INAT, "CC0-1.0"),
        ("CC0", INAT, "CC0-1.0"),
        ("cc-by", INAT, "CC-BY-4.0"),
        ("cc-by-sa", INAT, "CC-BY-SA-4.0"),
        (" CC-BY-SA ", INAT, "CC-BY-SA-4.0"),
        ("cc-by-nc", INAT, None),
        ("cc-by-nd", INAT, None),
        ("cc-by-nc-nd", INAT, None),
        ("cc-by-nc-sa", INAT, None),
        ("pd", INAT, None),
        ("", INAT, None),
        (None, INAT, None),
        # Commons LicenseShortName / License
        ("CC BY-SA 3.0", COMMONS, "CC-BY-SA-3.0"),
        ("CC BY-SA 4.0", COMMONS, "CC-BY-SA-4.0"),
        ("CC BY 2.0", COMMONS, "CC-BY-2.0"),
        ("CC BY 2.5", COMMONS, "CC-BY-2.5"),
        ("cc-by-sa-4.0", COMMONS, "CC-BY-SA-4.0"),
        ("cc-by-3.0", COMMONS, "CC-BY-3.0"),
        ("CC0", COMMONS, "CC0-1.0"),
        ("CC0 1.0", COMMONS, "CC0-1.0"),
        ("cc0-1.0", COMMONS, "CC0-1.0"),
        ("Public Domain Mark 1.0", COMMONS, "PDM-1.0"),
        ("pdm-1.0", COMMONS, "PDM-1.0"),
        ("Public domain", COMMONS, None),
        ("pd", COMMONS, None),
        ("CC BY-SA", COMMONS, None),  # unversioned outside iNat: unresolvable
        ("cc-by", COMMONS, None),
        ("CC BY-SA 3.0 de", COMMONS, None),  # ported licence is a different licence
        ("cc-by-sa-3.0-de", COMMONS, None),
        ("cc-by-sa-3.0-migrated", COMMONS, None),
        ("CC BY-SA 2.5,2.0,1.0", COMMONS, None),  # multi-licence: the source must choose one
        ("CC BY-NC-SA 2.0", COMMONS, None),
        ("CC BY-ND 4.0", COMMONS, None),
        ("CC BY 1.0", COMMONS, None),
        ("GFDL", COMMONS, None),
        ("Attribution", COMMONS, None),
        # exact ids pass through for any source
        ("CC-BY-4.0", "wikimedia", "CC-BY-4.0"),
        ("CC-BY-SA-2.0", "something-else", "CC-BY-SA-2.0"),
        ("cc-by", "something-else", None),
    ],
)
def test_normalise_licence(raw, source, expected):
    assert normalise_licence(raw, source) == expected


def test_resolve_licence_marks_inat_unversioned_as_assumed():
    assert resolve_licence("cc-by", INAT) == ("CC-BY-4.0", True)
    assert resolve_licence("cc-by-sa", INAT) == ("CC-BY-SA-4.0", True)
    assert resolve_licence("cc0", INAT) == ("CC0-1.0", False)
    assert resolve_licence("CC BY-SA 4.0", COMMONS) == ("CC-BY-SA-4.0", False)
    assert resolve_licence("cc-by-nc", INAT) is None


@pytest.mark.parametrize(
    "licence_id, url",
    [
        ("CC0-1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
        ("PDM-1.0", "https://creativecommons.org/publicdomain/mark/1.0/"),
        ("CC-BY-2.0", "https://creativecommons.org/licenses/by/2.0/"),
        ("CC-BY-4.0", "https://creativecommons.org/licenses/by/4.0/"),
        ("CC-BY-SA-2.5", "https://creativecommons.org/licenses/by-sa/2.5/"),
        ("CC-BY-SA-3.0", "https://creativecommons.org/licenses/by-sa/3.0/"),
    ],
)
def test_licence_url(licence_id, url):
    assert licence_url(licence_id) == url


def test_licence_url_rejects_unknown():
    with pytest.raises(ValueError, match="not an allowed licence id"):
        licence_url("CC-BY-NC-4.0")


def make_record(**overrides) -> AssetRecord:
    base = dict(
        source="commons",
        source_asset_id="File:Turdus-migratorius-002.jpg",
        source_url="https://commons.wikimedia.org/wiki/File:Turdus-migratorius-002.jpg",
        file_url="https://upload.wikimedia.org/wikipedia/commons/b/b8/Turdus-migratorius-002.jpg",
        licence_id="CC-BY-SA-3.0",
        licence_url="https://creativecommons.org/licenses/by-sa/3.0/",
        creator="Mdf",
        creator_url="https://commons.wikimedia.org/wiki/User:Mdf",
        attribution_text=None,
        title="Turdus-migratorius-002",
        copyright_notice=None,
        modifications=(),
        prior_modifications=None,
        restrictions=None,
        retrieved_at="2026-09-28",
        source_terms_version="2026-09-28",
    )
    base.update(overrides)
    return AssetRecord(**base)


def test_asset_record_has_exactly_the_5_1_fields_plus_the_version_flag():
    names = [f.name for f in fields(AssetRecord)]
    assert names == SECTION_5_1_FIELDS + ["licence_version_assumed"]


def test_asset_record_is_frozen():
    rec = make_record()
    with pytest.raises(FrozenInstanceError):
        rec.creator = "x"  # type: ignore[misc]


def test_with_modification_appends_and_returns_copy():
    rec = make_record()
    rec2 = rec.with_modification("resized").with_modification("transcoded to WebP")
    assert rec.modifications == ()
    assert rec2.modifications == ("resized", "transcoded to WebP")
    assert rec2.creator == rec.creator


@pytest.mark.parametrize(
    "licence_id, assumed, expected",
    [
        ("CC-BY-2.0", False, True),
        ("CC-BY-2.5", False, True),
        ("CC-BY-3.0", False, True),
        ("CC-BY-SA-3.0", False, True),
        ("CC-BY-4.0", False, False),
        ("CC-BY-SA-4.0", False, False),
        ("CC-BY-4.0", True, True),  # iNat unversioned: follow the 3.0 rule (ADR 0012)
        ("CC-BY-SA-4.0", True, True),
        ("CC0-1.0", False, False),
        ("PDM-1.0", False, False),
        ("CC-BY-NC-4.0", False, True),  # outside the allowlist: strict
    ],
)
def test_title_required(licence_id, assumed, expected):
    rec = make_record(licence_id=licence_id, licence_version_assumed=assumed)
    assert title_required(rec) is expected


def test_missing_required_fields_complete_record():
    assert make_record().missing_required_fields() == []


def test_missing_required_fields_reports_each_gap():
    rec = make_record(creator=None, licence_url="", source_url="  ", title=None)
    assert rec.missing_required_fields() == ["creator", "licence_url", "source_url", "title"]


def test_missing_title_ok_for_4_0_but_not_when_version_assumed():
    assert make_record(licence_id="CC-BY-4.0", title=None).missing_required_fields() == []
    assumed = make_record(licence_id="CC-BY-4.0", title=None, licence_version_assumed=True)
    assert assumed.missing_required_fields() == ["title"]


def test_missing_licence_id():
    assert make_record(licence_id="").missing_required_fields() == ["licence_id"]


def test_json_round_trip():
    rec = make_record(modifications=("resized",), licence_version_assumed=True)
    d = rec.to_dict()
    assert d["modifications"] == ["resized"]
    assert json.loads(json.dumps(d)) == d
    assert AssetRecord.from_dict(json.loads(json.dumps(d))) == rec


def test_from_dict_rejects_unknown_keys():
    d = make_record().to_dict()
    d["surprise"] = 1
    with pytest.raises(ValueError, match="unknown AssetRecord fields"):
        AssetRecord.from_dict(d)


def test_from_dict_defaults_missing_optional_fields():
    d = make_record().to_dict()
    for k in ("creator_url", "attribution_text", "copyright_notice", "prior_modifications", "restrictions",
              "source_terms_version", "modifications", "licence_version_assumed"):
        d.pop(k)
    rec = AssetRecord.from_dict(d)
    assert rec.modifications == ()
    assert rec.licence_version_assumed is False
