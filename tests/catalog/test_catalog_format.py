"""Tests for avianki.catalog.format: dataclasses, schemas, content addressing, write/load."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from avianki.catalog import format as fmt
from avianki.catalog.format import (
    MANIFEST_SCHEMA,
    PROVENANCE_SCHEMA,
    REGION_SCHEMA,
    SPECIES_SCHEMA,
    DatasetCredit,
    FormatError,
    Manifest,
    MediaRef,
    ProvenanceEntry,
    ProvenanceFile,
    RegionFile,
    RegionRef,
    SpeciesEntry,
    SpeciesFile,
    canonical_json,
    hashed_name,
    load_catalog,
    media_filename,
    validate_manifest,
    validate_provenance,
    validate_region,
    validate_species,
    write_catalog,
    write_media,
)
from avianki.core.licences import AssetRecord

MONTHLY = (180, 190, 230, 255, 255, 250, 240, 235, 230, 220, 200, 185)


def make_record(**overrides: Any) -> AssetRecord:
    base: dict[str, Any] = {
        "source": "wikimedia",
        "source_asset_id": "File:Robin.jpg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Robin.jpg",
        "file_url": "https://upload.wikimedia.org/robin.jpg",
        "licence_id": "CC-BY-SA-3.0",
        "licence_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "creator": "Mdf",
        "title": "Robin",
        "modifications": ("resized",),
        "retrieved_at": "2026-09-28",
    }
    base.update(overrides)
    return AssetRecord(**base)


def manifest_dict() -> dict[str, Any]:
    return {
        "format": 1,
        "catalog_version": "2026-11-01",
        "base_url": "https://example.org/catalog/",
        "gadm_version": "4.1",
        "species_file": "species.3f9a0c21.json",
        "regions": [
            {
                "slug": "us-ma",
                "name": "Massachusetts",
                "country": "US",
                "file": "regions/us-ma.8c1e44d0.json",
                "species_count": 2,
            }
        ],
        "dataset_credits": [
            {
                "text": "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF",
                "licence_id": "CC-BY-4.0",
                "url": "https://doi.org/10.15468/aomfnb",
                "modifications": "filtered and ranked by region",
            }
        ],
        "total_bytes": 312000,
    }


def species_dict() -> dict[str, Any]:
    return {
        "turdus-migratorius": {
            "name": "American Robin",
            "sci": "Turdus migratorius",
            "photo": [{"file": "media/1a2b3c4d5e6f7a8b.webp", "bytes": 45120, "credit": "Photo: x"}],
            "audio": [{"file": "media/9f8e7d6c5b4a3921.mp3", "bytes": 98211, "credit": "Recording: y"}],
        }
    }


def provenance_dict() -> dict[str, Any]:
    entry = ProvenanceEntry(make_record(), "turdus-migratorius", "photo", "File:Robin.jpg")
    return {"media/1a2b3c4d5e6f7a8b.webp": entry.to_dict()}


# --- dataclass round trips ---------------------------------------------------------------


def test_manifest_round_trip() -> None:
    d = manifest_dict()
    manifest = Manifest.from_dict(d)
    assert manifest.to_dict() == d
    assert manifest.regions[0] == RegionRef("us-ma", "Massachusetts", "US", "regions/us-ma.8c1e44d0.json", 2)
    assert manifest.dataset_credits[0].licence_id == "CC-BY-4.0"
    assert Manifest.from_dict(manifest.to_dict()) == manifest


def test_manifest_round_trip_with_provenance_file() -> None:
    d = manifest_dict() | {"provenance_file": "provenance.0a1b2c3d.json"}
    assert Manifest.from_dict(d).to_dict() == d


def test_manifest_eod_version_is_optional_and_round_trips() -> None:
    plain = Manifest.from_dict(manifest_dict())
    assert plain.eod_version is None and "eod_version" not in plain.to_dict()
    d = manifest_dict() | {"eod_version": "1.15"}
    assert Manifest.from_dict(d).eod_version == "1.15"
    assert Manifest.from_dict(d).to_dict() == d
    validate_manifest(d)
    with pytest.raises(FormatError):
        validate_manifest(manifest_dict() | {"eod_version": ""})


def test_dataset_credit_and_region_ref_round_trip() -> None:
    c = DatasetCredit("t", "CC-BY-4.0", "https://x.org/", "m")
    assert DatasetCredit.from_dict(c.to_dict()) == c
    r = RegionRef("us-ma", "MA", "US", "regions/us-ma.8c1e44d0.json", 3)
    assert RegionRef.from_dict(r.to_dict()) == r


def test_region_file_round_trip_uses_tuples_and_json_lists() -> None:
    region = RegionFile("us-ma", [("turdus-migratorius", MONTHLY), ("cyanocitta-cristata", MONTHLY)])
    d = region.to_dict()
    assert d == {
        "slug": "us-ma",
        "species": [["turdus-migratorius", list(MONTHLY)], ["cyanocitta-cristata", list(MONTHLY)]],
    }
    assert RegionFile.from_dict(json.loads(json.dumps(d))) == region


def test_species_file_round_trip_and_mapping_access() -> None:
    d = species_dict()
    species = SpeciesFile.from_dict(d)
    assert species.to_dict() == d
    assert "turdus-migratorius" in species and len(species) == 1
    entry = species["turdus-migratorius"]
    assert entry == SpeciesEntry(
        "American Robin",
        "Turdus migratorius",
        [MediaRef("media/1a2b3c4d5e6f7a8b.webp", 45120, "Photo: x")],
        [MediaRef("media/9f8e7d6c5b4a3921.mp3", 98211, "Recording: y")],
    )
    assert list(species) == ["turdus-migratorius"]
    assert dict(species.items()) == {"turdus-migratorius": entry}


def test_ioc_name_is_optional_and_omitted_when_empty() -> None:
    """ADR 0027: an old species file (no key) still loads, and an empty name writes no key."""
    d = species_dict()
    old = SpeciesFile.from_dict(d)["turdus-migratorius"]
    assert old.ioc_name == ""
    assert "ioc_name" not in old.to_dict()

    d["turdus-migratorius"]["ioc_name"] = "American Robin (IOC)"
    validate_species(d)
    entry = SpeciesFile.from_dict(d)["turdus-migratorius"]
    assert entry.ioc_name == "American Robin (IOC)"
    assert entry.to_dict()["ioc_name"] == "American Robin (IOC)"

    d["turdus-migratorius"]["ioc_name"] = ""
    with pytest.raises(FormatError):
        validate_species(d)


def test_provenance_round_trip_flat_json() -> None:
    entry = ProvenanceEntry(
        make_record(licence_version_assumed=True),
        "turdus-migratorius",
        "audio",
        "XC12345",
        verified="birdnet",
        birdnet_confidence=0.91,
    )
    d = entry.to_dict()
    assert d["species_id"] == "turdus-migratorius" and d["token"] == "XC12345"
    assert d["licence_id"] == "CC-BY-SA-3.0"  # the 5.1 record is flat, not nested
    assert d["modifications"] == ["resized"]
    assert ProvenanceEntry.from_dict(json.loads(json.dumps(d))) == entry
    file = ProvenanceFile({"media/9f8e7d6c5b4a3921.mp3": entry})
    assert ProvenanceFile.from_dict(file.to_dict()) == file


def test_provenance_optional_keys_omitted_when_none() -> None:
    d = ProvenanceEntry(make_record(), "x", "photo", "t").to_dict()
    assert "verified" not in d and "birdnet_confidence" not in d
    assert ProvenanceEntry.from_dict(d).verified is None


def test_readers_ignore_unknown_optional_keys() -> None:
    d = manifest_dict() | {"future": 1}
    d["regions"][0]["future"] = True
    assert Manifest.from_dict(d).regions[0].slug == "us-ma"
    entry = provenance_dict()["media/1a2b3c4d5e6f7a8b.webp"] | {"future_field": "x"}
    assert ProvenanceEntry.from_dict(entry).record.creator == "Mdf"


# --- schemas -------------------------------------------------------------------------------


@pytest.mark.parametrize("schema", [MANIFEST_SCHEMA, REGION_SCHEMA, SPECIES_SCHEMA, PROVENANCE_SCHEMA])
def test_schemas_are_valid_draft_2020_12(schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)


def test_valid_documents_pass() -> None:
    """The validators return None or raise FormatError (the tests below show they do), so no raise is the pass."""
    validate_manifest(manifest_dict())
    validate_species(species_dict())
    validate_provenance(provenance_dict())
    validate_region(RegionFile("us-ma", [("turdus-migratorius", MONTHLY)]).to_dict())


def test_manifest_wrong_format_int_is_rejected() -> None:
    for bad in (2, 0, "1", True, None):
        d = manifest_dict() | {"format": bad}
        with pytest.raises(FormatError, match=r"\$\.format"):
            validate_manifest(d)


def test_manifest_missing_format_is_rejected() -> None:
    d = manifest_dict()
    del d["format"]
    with pytest.raises(FormatError, match="format"):
        validate_manifest(d)


def test_manifest_bad_hashed_file_names() -> None:
    for key, value in (("species_file", "species.json"), ("species_file", "species.ABCDEF12.json")):
        with pytest.raises(FormatError, match=key):
            validate_manifest(manifest_dict() | {key: value})
    d = manifest_dict()
    d["regions"][0]["file"] = "regions/us-ma.json"
    with pytest.raises(FormatError, match=r"regions\[0\]\.file"):
        validate_manifest(d)


def test_manifest_bad_region_slug_and_count() -> None:
    d = manifest_dict()
    d["regions"][0]["slug"] = "US-MA"
    with pytest.raises(FormatError, match=r"regions\[0\]\.slug"):
        validate_manifest(d)
    d = manifest_dict()
    d["regions"][0]["species_count"] = -1
    with pytest.raises(FormatError, match="species_count"):
        validate_manifest(d)


@pytest.mark.parametrize(
    "bad",
    [
        "media/short.webp",
        "media/1A2B3C4D5E6F7A8B.webp",  # uppercase hex
        "media/1a2b3c4d5e6f7a8b.jpg",
        "media/1a2b3c4d5e6f7a8b.mp3",  # photos are webp
        "1a2b3c4d5e6f7a8b.webp",
        "../media/1a2b3c4d5e6f7a8b.webp",
        "media/1a2b3c4d5e6f7a8b0.webp",
    ],
)
def test_species_bad_photo_filename_is_rejected(bad: str) -> None:
    d = species_dict()
    d["turdus-migratorius"]["photo"][0]["file"] = bad
    with pytest.raises(FormatError, match=r"turdus-migratorius\]?\.?.*photo|photo"):
        validate_species(d)


def test_species_audio_must_be_mp3() -> None:
    d = species_dict()
    d["turdus-migratorius"]["audio"][0]["file"] = "media/9f8e7d6c5b4a3921.webp"
    with pytest.raises(FormatError, match="audio"):
        validate_species(d)


def test_species_missing_credit_or_bad_bytes_or_bad_id() -> None:
    d = species_dict()
    del d["turdus-migratorius"]["photo"][0]["credit"]
    with pytest.raises(FormatError, match="credit"):
        validate_species(d)
    d = species_dict()
    d["turdus-migratorius"]["photo"][0]["credit"] = None
    with pytest.raises(FormatError, match="credit"):
        validate_species(d)
    d = species_dict()
    d["turdus-migratorius"]["photo"][0]["credit"] = ""
    with pytest.raises(FormatError, match="credit"):
        validate_species(d)
    for bad in (0, -5, 1.5, "10"):
        d = species_dict()
        d["turdus-migratorius"]["audio"][0]["bytes"] = bad
        with pytest.raises(FormatError, match="bytes"):
            validate_species(d)
    d = {"Turdus Migratorius": species_dict()["turdus-migratorius"]}
    with pytest.raises(FormatError):
        validate_species(d)


def test_species_missing_lists_are_rejected_but_empty_lists_are_absence() -> None:
    d = species_dict()
    d["turdus-migratorius"]["photo"] = []
    validate_species(d)
    del d["turdus-migratorius"]["audio"]
    with pytest.raises(FormatError, match="audio"):
        validate_species(d)


def test_region_monthly_must_be_twelve_ints_0_to_255() -> None:
    ok = ["us-ma", "turdus-migratorius"]
    with pytest.raises(FormatError, match=r"species\[0\]"):
        validate_region({"slug": ok[0], "species": [[ok[1], list(MONTHLY[:11])]]})
    with pytest.raises(FormatError, match=r"species\[0\]"):
        validate_region({"slug": ok[0], "species": [[ok[1], [*MONTHLY, 1]]]})
    with pytest.raises(FormatError, match="256"):
        validate_region({"slug": ok[0], "species": [[ok[1], [*MONTHLY[:11], 256]]]})
    with pytest.raises(FormatError, match="-1"):
        validate_region({"slug": ok[0], "species": [[ok[1], [*MONTHLY[:11], -1]]]})
    with pytest.raises(FormatError):
        validate_region({"slug": ok[0], "species": [[ok[1], [*MONTHLY[:11], 1.5]]]})
    with pytest.raises(FormatError):
        validate_region({"slug": ok[0], "species": [["Bad Id", list(MONTHLY)]]})
    with pytest.raises(FormatError):
        validate_region({"slug": ok[0], "species": [[ok[1], list(MONTHLY), "extra"]]})


def test_provenance_requires_51_fields_and_valid_media_names() -> None:
    d = provenance_dict()
    del d["media/1a2b3c4d5e6f7a8b.webp"]["licence_id"]
    with pytest.raises(FormatError, match="licence_id"):
        validate_provenance(d)
    d = {"media/bad.webp": provenance_dict()["media/1a2b3c4d5e6f7a8b.webp"]}
    with pytest.raises(FormatError):
        validate_provenance(d)
    d = provenance_dict()
    d["media/1a2b3c4d5e6f7a8b.webp"]["kind"] = "video"
    with pytest.raises(FormatError, match="kind"):
        validate_provenance(d)


def test_schemas_accept_extra_optional_keys() -> None:
    """Forward compatibility: an unknown key anywhere is accepted (no FormatError), never rejected."""
    m = manifest_dict() | {"future_key": {"a": 1}}
    m["regions"][0]["future_key"] = "x"
    m["dataset_credits"][0]["future_key"] = 1
    validate_manifest(m)
    s = species_dict()
    s["turdus-migratorius"]["future_key"] = []
    s["turdus-migratorius"]["photo"][0]["future_key"] = 1
    validate_species(s)
    p = provenance_dict()
    p["media/1a2b3c4d5e6f7a8b.webp"]["future_key"] = "x"
    validate_provenance(p)
    validate_region({"slug": "us-ma", "species": [], "future_key": 1})


def test_format_error_is_a_value_error_with_readable_path() -> None:
    d = manifest_dict()
    d["regions"][0]["file"] = "nope"
    with pytest.raises(ValueError, match=r"manifest file invalid at \$\.regions\[0\]\.file"):
        validate_manifest(d)


def test_format_is_neutral_about_anki() -> None:
    text = json.dumps([MANIFEST_SCHEMA, REGION_SCHEMA, SPECIES_SCHEMA, PROVENANCE_SCHEMA])
    for word in ("guid", "[sound:", "notetype", "note_type", "model"):
        assert word not in text.lower()


# --- content addressing --------------------------------------------------------------------


def test_media_filename_matches_hand_computed_sha256() -> None:
    data = b"abc"
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert hashlib.sha256(data).hexdigest() == expected
    assert media_filename(data, "webp") == "media/ba7816bf8f01cfea.webp"
    assert media_filename(data, "mp3") == "media/ba7816bf8f01cfea.mp3"


def test_media_filename_rejects_other_extensions() -> None:
    for ext in ("jpg", "png", "MP3", ".mp3", ""):
        with pytest.raises(ValueError, match="media extension must be one of"):
            media_filename(b"abc", ext)


def test_canonical_json_sorted_compact_utf8() -> None:
    assert canonical_json({"b": 1, "a": [3, 1, 2], "c": "é"}) == '{"a":[3,1,2],"b":1,"c":"é"}'.encode()


def test_hashed_name_stable_across_key_order_and_changes_with_content() -> None:
    a = {"x": 1, "y": {"p": 1, "q": 2}}
    b = {"y": {"q": 2, "p": 1}, "x": 1}
    assert hashed_name("species", a) == hashed_name("species", b)
    name = hashed_name("species", a)
    expected = hashlib.sha256(b'{"x":1,"y":{"p":1,"q":2}}').hexdigest()[:8]
    assert name == f"species.{expected}.json"
    assert hashed_name("species", {"x": 2}) != name
    # list order is data (region files are in rank order)
    assert hashed_name("r", [1, 2]) != hashed_name("r", [2, 1])


def test_hashed_name_subdirs_and_stems() -> None:
    obj = {"slug": "us-ma"}
    h = hashed_name("provenance", obj)[len("provenance.") : -len(".json")]
    assert len(h) == 8
    assert hashed_name("us-ma", obj, "regions") == f"regions/us-ma.{h}.json"
    assert hashed_name("us-ma", obj, "regions/") == f"regions/us-ma.{h}.json"


def test_hashed_name_is_stable_across_processes() -> None:
    # A frozen golden value: if this changes, every published catalog would be renamed.
    assert hashed_name("species", {"a": 1}) == "species.015abd7f.json"


# --- write / load --------------------------------------------------------------------------


def build_tiny(out_dir: Path) -> tuple[Manifest, dict[str, bytes]]:
    """A 2-region, 3-species catalog with real (tiny) media files written to out_dir."""
    media = {
        "robin_photo": b"webp-robin",
        "robin_audio": b"mp3-robin",
        "jay_photo": b"webp-jay",
    }
    robin_photo = write_media(out_dir, media["robin_photo"], "webp")
    robin_audio = write_media(out_dir, media["robin_audio"], "mp3")
    jay_photo = write_media(out_dir, media["jay_photo"], "webp")
    species = SpeciesFile(
        {
            "turdus-migratorius": SpeciesEntry(
                "American Robin",
                "Turdus migratorius",
                [MediaRef(robin_photo, len(media["robin_photo"]), "Photo: r")],
                [MediaRef(robin_audio, len(media["robin_audio"]), "Recording: r")],
            ),
            "cyanocitta-cristata": SpeciesEntry(
                "Blue Jay",
                "Cyanocitta cristata",
                [MediaRef(jay_photo, len(media["jay_photo"]), "Photo: j")],
                [],
            ),
            "poecile-atricapillus": SpeciesEntry("Black-capped Chickadee", "Poecile atricapillus", [], []),
        }
    )
    provenance = ProvenanceFile(
        {
            robin_photo: ProvenanceEntry(make_record(), "turdus-migratorius", "photo", "File:Robin.jpg"),
            robin_audio: ProvenanceEntry(
                make_record(source="xenocanto", source_asset_id="XC1"),
                "turdus-migratorius",
                "audio",
                "XC1",
                verified="birdnet",
                birdnet_confidence=0.9,
            ),
            jay_photo: ProvenanceEntry(make_record(), "cyanocitta-cristata", "photo", "File:Jay.jpg"),
        }
    )
    regions = [
        RegionFile("us-ma", [("turdus-migratorius", MONTHLY), ("cyanocitta-cristata", MONTHLY)]),
        RegionFile("us-vt", [("poecile-atricapillus", MONTHLY), ("turdus-migratorius", MONTHLY)]),
    ]
    template = Manifest(
        catalog_version="2026-11-01",
        base_url="https://example.org/catalog/",
        gadm_version="4.1",
        species_file="",
        regions=[RegionRef("us-ma", "Massachusetts", "US", "", 0), RegionRef("us-vt", "Vermont", "US", "", 0)],
        dataset_credits=[DatasetCredit("eBird", "CC-BY-4.0", "https://doi.org/10.15468/aomfnb", "filtered")],
        total_bytes=0,
    )
    written = write_catalog(out_dir, template, regions, species, provenance)
    return written, media


def test_write_then_load_round_trips_a_tiny_catalog(tmp_path: Path) -> None:
    written, media = build_tiny(tmp_path)
    loaded = load_catalog(tmp_path)

    assert loaded.manifest == written
    assert [r.slug for r in loaded.manifest.regions] == ["us-ma", "us-vt"]
    assert [r.species_count for r in loaded.manifest.regions] == [2, 2]
    assert loaded.manifest.species_file.startswith("species.")
    assert loaded.manifest.regions[0].file.startswith("regions/us-ma.")
    assert set(loaded.regions) == {"us-ma", "us-vt"}
    assert loaded.regions["us-vt"].species[0] == ("poecile-atricapillus", MONTHLY)
    assert len(loaded.species) == 3
    assert loaded.species["cyanocitta-cristata"].audio == []
    assert loaded.provenance is not None and len(loaded.provenance) == 3
    robin_audio = loaded.species["turdus-migratorius"].audio[0].file
    assert loaded.provenance[robin_audio].verified == "birdnet"
    assert loaded.provenance[robin_audio].token == "XC1"
    assert loaded.media_problems() == []

    # total_bytes = distinct media + the hashed JSON files (not the manifest)
    json_files = [loaded.manifest.species_file, loaded.manifest.provenance_file] + [
        r.file for r in loaded.manifest.regions
    ]
    expected = sum(len(v) for v in media.values()) + sum((tmp_path / str(f)).stat().st_size for f in json_files)
    assert loaded.manifest.total_bytes == expected


def test_write_catalog_carries_eod_version_through(tmp_path: Path) -> None:
    out = tmp_path / "out"
    written, _ = build_tiny(out)
    assert written.eod_version is None
    template = replace(written, eod_version="1.15")
    loaded = load_catalog(out)
    rewritten = write_catalog(
        tmp_path / "again", template, list(loaded.regions.values()), loaded.species, loaded.provenance
    )
    assert rewritten.eod_version == "1.15"
    assert load_catalog(tmp_path / "again").manifest.eod_version == "1.15"


def test_write_catalog_is_deterministic(tmp_path: Path) -> None:
    a = build_tiny(tmp_path / "a")[0]
    b = build_tiny(tmp_path / "b")[0]
    assert a == b
    assert (tmp_path / "a" / "manifest.json").read_bytes() == (tmp_path / "b" / "manifest.json").read_bytes()


def test_write_media_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    name = write_media(tmp_path, b"hello", "mp3")
    assert name == media_filename(b"hello", "mp3")
    assert write_media(tmp_path, b"hello", "mp3") == name
    assert (tmp_path / name).read_bytes() == b"hello"


def test_load_detects_media_whose_bytes_do_not_match_its_name(tmp_path: Path) -> None:
    build_tiny(tmp_path)
    loaded = load_catalog(tmp_path)
    victim = loaded.species["cyanocitta-cristata"].photo[0]
    (tmp_path / victim.file).write_bytes(b"webp-jay")  # same length, same content: still fine
    assert loaded.media_problems() == []
    (tmp_path / victim.file).write_bytes(b"webp-JAY")  # same length, different content
    problems = loaded.media_problems()
    assert len(problems) == 1 and victim.file in problems[0] and "hash" in problems[0]
    (tmp_path / victim.file).write_bytes(b"short")
    assert "bytes" in (loaded.media_problem(victim.file, victim.bytes) or "")


def test_load_detects_a_missing_media_file(tmp_path: Path) -> None:
    build_tiny(tmp_path)
    loaded = load_catalog(tmp_path)
    victim = loaded.species["turdus-migratorius"].audio[0].file
    (tmp_path / victim).unlink()
    problems = loaded.media_problems()
    assert problems == [f"{victim}: missing"]


def test_media_path_rejects_traversal(tmp_path: Path) -> None:
    build_tiny(tmp_path)
    loaded = load_catalog(tmp_path)
    with pytest.raises(FormatError):
        loaded.media_path("media/../manifest.json")


def test_load_rejects_a_hashed_file_edited_after_writing(tmp_path: Path) -> None:
    written, _ = build_tiny(tmp_path)
    path = tmp_path / written.species_file
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["cyanocitta-cristata"]["name"] = "Tampered"
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(FormatError, match="hash in its name"):
        load_catalog(tmp_path)


def test_load_rejects_schema_violations_and_missing_files(tmp_path: Path) -> None:
    written, _ = build_tiny(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    good = json.loads(manifest_path.read_text(encoding="utf-8"))

    bad = copy.deepcopy(good) | {"format": 2}
    manifest_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(FormatError, match="format"):
        load_catalog(tmp_path)

    manifest_path.write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / written.regions[0].file).unlink()
    with pytest.raises(FormatError, match="missing catalog file"):
        load_catalog(tmp_path)

    manifest_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FormatError, match="unreadable"):
        load_catalog(tmp_path)

    with pytest.raises(FormatError, match="missing catalog file"):
        load_catalog(tmp_path / "nowhere")


def test_load_rejects_manifest_row_that_disagrees_with_region_file(tmp_path: Path) -> None:
    build_tiny(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    m["regions"][0]["species_count"] = 99
    manifest_path.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(FormatError, match="99"):
        load_catalog(tmp_path)


def test_write_catalog_refuses_invalid_input(tmp_path: Path) -> None:
    written, _ = build_tiny(tmp_path / "ok")
    species = SpeciesFile(
        {"turdus-migratorius": SpeciesEntry("Robin", "T m", [MediaRef("media/nothex.webp", 1, "c")], [])}
    )
    with pytest.raises(FormatError):
        write_catalog(tmp_path / "bad", written, [RegionFile("us-ma", []), RegionFile("us-vt", [])], species, ProvenanceFile({}))
    assert not (tmp_path / "bad" / "manifest.json").exists()


def test_write_catalog_requires_manifest_and_regions_to_agree(tmp_path: Path) -> None:
    written, _ = build_tiny(tmp_path / "ok")
    with pytest.raises(FormatError, match="us-vt"):
        write_catalog(
            tmp_path / "x",
            written,
            [RegionFile("us-ma", [])],
            SpeciesFile({}),
            ProvenanceFile({}),
        )


def test_catalog_init_stays_docstring_only() -> None:
    import ast

    init = Path(fmt.__file__).with_name("__init__.py")
    tree = ast.parse(init.read_text(encoding="utf-8"))
    assert all(isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) for n in tree.body)
