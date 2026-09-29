"""Tests for avianki.catalog.validate: the ADR 0014 publish gate."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from avianki.catalog.format import (
    LoadedCatalog,
    MediaRef,
    ProvenanceFile,
    SpeciesEntry,
    SpeciesFile,
    load_catalog,
    write_media,
)
from avianki.catalog.validate import (
    Problem,
    ValidationResult,
    check_audio_verified,
    check_credits,
    check_licences,
    check_media_files,
    check_pins,
    check_provenance_coverage,
    check_shrink,
    check_size,
    check_structure,
    format_result,
    validate_catalog,
)
from catalog_fakes import Sp, build_catalog, mutated_copy


def codes(problems: list[Problem]) -> list[str]:
    return [p.code for p in problems]


@pytest.fixture()
def cat(tmp_path: Path) -> LoadedCatalog:
    return build_catalog(
        tmp_path / "v1",
        {
            "american-robin": Sp("American Robin", "Turdus migratorius"),
            "blue-jay": Sp("Blue Jay", "Cyanocitta cristata"),
        },
    )


def only_photo(cat: LoadedCatalog, sid: str) -> str:
    return cat.species[sid].photo[0].file


def only_audio(cat: LoadedCatalog, sid: str) -> str:
    return cat.species[sid].audio[0].file


def with_prov(cat: LoadedCatalog, name: str, **changes: object) -> ProvenanceFile:
    assert cat.provenance is not None
    entries = dict(cat.provenance.entries)
    entries[name] = replace(entries[name], **changes)  # type: ignore[arg-type]
    return ProvenanceFile(entries)


def with_record(cat: LoadedCatalog, name: str, **changes: object) -> ProvenanceFile:
    assert cat.provenance is not None
    entry = cat.provenance.entries[name]
    return with_prov(cat, name, record=replace(entry.record, **changes))  # type: ignore[arg-type]


def with_species(cat: LoadedCatalog, sid: str, **changes: object) -> SpeciesFile:
    entries = dict(cat.species.entries)
    entries[sid] = replace(entries[sid], **changes)  # type: ignore[arg-type]
    return SpeciesFile(entries)


# ---------------------------------------------------------------------------------------
# The whole gate
# ---------------------------------------------------------------------------------------


def test_clean_catalog_passes_with_no_findings(cat: LoadedCatalog) -> None:
    result = validate_catalog(cat)
    assert result.errors == []
    assert result.warnings == []
    assert result.ok


def test_accepts_a_directory(cat: LoadedCatalog) -> None:
    assert validate_catalog(cat.root).ok


def test_unloadable_directory_is_one_format_error(tmp_path: Path) -> None:
    result = validate_catalog(tmp_path / "nothing-here")
    assert not result.ok
    assert codes(result.errors) == ["format.invalid"]


def test_schema_violation_is_a_format_error(cat: LoadedCatalog) -> None:
    manifest = cat.root / "manifest.json"
    obj = json.loads(manifest.read_text(encoding="utf-8"))
    obj["format"] = 99
    manifest.write_text(json.dumps(obj), encoding="utf-8")
    assert codes(validate_catalog(cat.root).errors) == ["format.invalid"]


def test_gate_aggregates_every_finding(cat: LoadedCatalog, tmp_path: Path) -> None:
    bad = mutated_copy(
        cat,
        tmp_path / "bad",
        provenance=with_prov(cat, only_audio(cat, "blue-jay"), verified=None),
    )
    bad.media_path(only_photo(bad, "american-robin")).unlink()
    found = set(codes(validate_catalog(bad).errors))
    assert {"media.missing", "audio.unverified"} <= found


# ---------------------------------------------------------------------------------------
# 1. Schema and file hashes
# ---------------------------------------------------------------------------------------


def test_missing_media_file(cat: LoadedCatalog) -> None:
    name = only_photo(cat, "american-robin")
    cat.media_path(name).unlink()
    res = check_media_files(cat)
    assert codes(res.errors) == ["media.missing"]
    assert res.errors[0].subject == name


def test_media_with_wrong_bytes_same_size(cat: LoadedCatalog) -> None:
    name = only_photo(cat, "american-robin")
    path = cat.media_path(name)
    path.write_bytes(b"x" * path.stat().st_size)
    assert codes(check_media_files(cat).errors) == ["media.hash"]


def test_media_with_wrong_size(cat: LoadedCatalog) -> None:
    name = only_photo(cat, "american-robin")
    cat.media_path(name).write_bytes(b"short")
    assert codes(check_media_files(cat).errors) == ["media.size"]


# ---------------------------------------------------------------------------------------
# 2. Licences, provenance coverage, credits
# ---------------------------------------------------------------------------------------


def test_licence_not_on_allowlist(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_photo(cat, "blue-jay")
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_record(cat, name, licence_id="CC-BY-NC-4.0"))
    res = check_licences(bad)
    assert codes(res.errors) == ["licence.not_allowed"]
    assert res.errors[0].subject == name


@pytest.mark.parametrize("raw", ["cc-by-4.0", "CC-BY-4", "CC BY 4.0", "CC-BY-ND-4.0", "CC-BY"])
def test_licence_match_is_exact(cat: LoadedCatalog, tmp_path: Path, raw: str) -> None:
    name = only_photo(cat, "blue-jay")
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_record(cat, name, licence_id=raw))
    assert "licence.not_allowed" in codes(check_licences(bad).errors)


def test_incomplete_record(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_photo(cat, "blue-jay")
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_record(cat, name, creator=None))
    res = check_licences(bad)
    assert codes(res.errors) == ["licence.incomplete"]
    assert "creator" in res.errors[0].message


def test_missing_title_where_the_licence_requires_it(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_photo(cat, "blue-jay")  # CC-BY-SA-3.0: title required
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_record(cat, name, title=None))
    assert "title" in check_licences(bad).errors[0].message


def test_orphan_provenance_entry(cat: LoadedCatalog, tmp_path: Path) -> None:
    assert cat.provenance is not None
    donor = cat.provenance.entries[only_photo(cat, "blue-jay")]
    entries = dict(cat.provenance.entries)
    entries["media/0123456789abcdef.webp"] = donor
    bad = mutated_copy(cat, tmp_path / "b", provenance=ProvenanceFile(entries))
    res = check_provenance_coverage(bad)
    assert codes(res.errors) == ["provenance.orphan"]
    assert res.errors[0].subject == "media/0123456789abcdef.webp"


def test_referenced_media_without_provenance(cat: LoadedCatalog, tmp_path: Path) -> None:
    assert cat.provenance is not None
    name = only_audio(cat, "blue-jay")
    entries = {k: v for k, v in cat.provenance.entries.items() if k != name}
    bad = mutated_copy(cat, tmp_path / "b", provenance=ProvenanceFile(entries))
    res = check_provenance_coverage(bad)
    assert codes(res.errors) == ["provenance.missing_entry"]
    assert res.errors[0].subject == name


def test_provenance_species_and_kind_must_agree(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_photo(cat, "blue-jay")
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_prov(cat, name, species_id="american-robin"))
    assert codes(check_provenance_coverage(bad).errors) == ["provenance.species_mismatch"]
    bad2 = mutated_copy(cat, tmp_path / "b2", provenance=with_prov(cat, name, kind="audio"))
    assert codes(check_provenance_coverage(bad2).errors) == ["provenance.kind_mismatch"]


def test_orphan_media_file_on_disk_is_a_warning(cat: LoadedCatalog) -> None:
    orphan = write_media(cat.root, b"nobody uses me", "webp")
    res = validate_catalog(cat)
    assert res.ok
    assert codes(res.warnings) == ["media.orphan_file"]
    assert res.warnings[0].subject == orphan


def test_missing_provenance_file_is_an_error(cat: LoadedCatalog) -> None:
    no_prov = LoadedCatalog(cat.root, cat.manifest, cat.regions, cat.species, None)
    assert codes(check_provenance_coverage(no_prov).errors) == ["provenance.absent"]


def test_unsafe_credit_is_rejected(cat: LoadedCatalog, tmp_path: Path) -> None:
    ref = cat.species["blue-jay"].photo[0]
    evil = MediaRef(ref.file, ref.bytes, ref.credit + "<script>alert(1)</script>")
    bad = mutated_copy(cat, tmp_path / "b", species=with_species(cat, "blue-jay", photo=[evil]))
    assert "credit.unsafe" in codes(check_credits(bad).errors)


def test_stale_or_blank_credit_is_rejected(cat: LoadedCatalog, tmp_path: Path) -> None:
    ref = cat.species["blue-jay"].photo[0]
    blank = MediaRef(ref.file, ref.bytes, "Photo")
    bad = mutated_copy(cat, tmp_path / "b", species=with_species(cat, "blue-jay", photo=[blank]))
    res = check_credits(bad)
    assert codes(res.errors) == ["credit.stale"]
    assert "licence label" in res.errors[0].message and "creator" in res.errors[0].message


def test_credit_stale_after_the_creator_changes(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_photo(cat, "blue-jay")
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_record(cat, name, creator="Someone Else"))
    assert codes(check_credits(bad).errors) == ["credit.stale"]


def test_credit_stale_after_the_licence_changes(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_photo(cat, "blue-jay")
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_record(cat, name, licence_id="CC-BY-4.0"))
    assert codes(check_credits(bad).errors) == ["credit.stale"]


# ---------------------------------------------------------------------------------------
# 3. Audio verification
# ---------------------------------------------------------------------------------------


def test_unverified_audio_is_an_error(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_audio(cat, "blue-jay")
    bad = mutated_copy(cat, tmp_path / "b", provenance=with_prov(cat, name, verified=None))
    res = check_audio_verified(bad)
    assert codes(res.errors) == ["audio.unverified"]
    assert res.errors[0].subject == name


def test_birdnet_audio_needs_confidence_of_half_or_more(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_audio(cat, "blue-jay")
    for n, (conf, expect) in enumerate([(0.49, ["audio.low_confidence"]), (None, ["audio.low_confidence"]), (0.5, [])]):
        alt = mutated_copy(
            cat, tmp_path / f"c{n}", provenance=with_prov(cat, name, verified="birdnet", birdnet_confidence=conf)
        )
        assert codes(check_audio_verified(alt).errors) == expect


def test_pinned_audio_needs_no_confidence(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_audio(cat, "blue-jay")
    alt = mutated_copy(
        cat, tmp_path / "b", provenance=with_prov(cat, name, verified="pinned", birdnet_confidence=None)
    )
    assert check_audio_verified(alt).errors == []


def test_photo_verification_is_not_required(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_photo(cat, "blue-jay")
    alt = mutated_copy(cat, tmp_path / "b", provenance=with_prov(cat, name, verified=None))
    assert check_audio_verified(alt).errors == []


# ---------------------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------------------


def test_excluded_token_still_present_is_an_error(cat: LoadedCatalog) -> None:
    res = check_pins(cat, {"blue-jay": {"exclude": ["blue-jay-photo-0"], "note": "removal request"}})
    assert codes(res.errors) == ["pins.excluded_present"]


@dataclass
class PinObj:
    photo: str | None = None
    audio: str | None = None
    exclude: tuple[str, ...] = ()


def test_pins_may_be_objects(cat: LoadedCatalog) -> None:
    res = check_pins(cat, {"blue-jay": PinObj(exclude=("blue-jay-audio-0",))})
    assert codes(res.errors) == ["pins.excluded_present"]


def test_pinned_audio_without_a_pin_is_a_warning(cat: LoadedCatalog, tmp_path: Path) -> None:
    name = only_audio(cat, "blue-jay")
    alt = mutated_copy(cat, tmp_path / "b", provenance=with_prov(cat, name, verified="pinned"))
    assert codes(check_pins(alt, {}).warnings) == ["pins.unbacked"]
    assert check_pins(alt, {"blue-jay": {"audio": "blue-jay-audio-0"}}).warnings == []
    assert check_pins(alt, None).warnings == []


# ---------------------------------------------------------------------------------------
# 4. Size
# ---------------------------------------------------------------------------------------


def test_oversized_site_is_an_error(cat: LoadedCatalog) -> None:
    assert codes(check_size(cat, max_site_bytes=10).errors) == ["size.total"]
    assert not validate_catalog(cat, max_site_bytes=10).ok


def test_size_limit_counts_disk_not_the_manifest(cat: LoadedCatalog) -> None:
    (cat.root / "media" / "stray.bin").write_bytes(b"z" * 5000)
    on_disk = sum(p.stat().st_size for p in cat.root.rglob("*") if p.is_file())
    assert check_size(cat, max_site_bytes=on_disk).errors == []
    assert codes(check_size(cat, max_site_bytes=on_disk - 1).errors) == ["size.total"]


def test_manifest_total_bytes_off_is_a_warning(cat: LoadedCatalog) -> None:
    assert check_size(cat).warnings == []
    manifest = cat.root / "manifest.json"
    obj = json.loads(manifest.read_text(encoding="utf-8"))
    obj["total_bytes"] += 100_000
    manifest.write_text(json.dumps(obj), encoding="utf-8")
    res = check_size(load_catalog(cat.root))
    assert res.errors == []
    assert codes(res.warnings) == ["size.manifest_mismatch"]


# ---------------------------------------------------------------------------------------
# 5. Shrink
# ---------------------------------------------------------------------------------------


def big(tmp_path: Path, name: str, ids: list[str], photos: int = 0) -> LoadedCatalog:
    return build_catalog(tmp_path / name, {i: Sp(i, photos=photos, audios=0) for i in ids})


@pytest.fixture()
def hundred() -> list[str]:
    return [f"sp{i:03d}" for i in range(100)]


def test_region_losing_eleven_percent_is_an_error(tmp_path: Path, hundred: list[str]) -> None:
    prev = big(tmp_path, "prev", hundred)
    new = big(tmp_path, "new", hundred[:89])
    res = check_shrink(new, prev)
    assert codes(res.errors) == ["shrink.region"]
    assert "11 of 100" in res.errors[0].message and "us-ma" in res.errors[0].message


def test_region_losing_exactly_ten_percent_is_fine(tmp_path: Path, hundred: list[str]) -> None:
    prev = big(tmp_path, "prev", hundred)
    new = big(tmp_path, "new", hundred[:90])
    assert check_shrink(new, prev).errors == []


def test_new_species_do_not_mask_lost_ones(tmp_path: Path, hundred: list[str]) -> None:
    prev = big(tmp_path, "prev", hundred)
    new = big(tmp_path, "new", [*hundred[:80], *(f"new{i}" for i in range(20))])
    assert codes(check_shrink(new, prev).errors) == ["shrink.region"]


def test_a_removed_region_is_a_shrink(tmp_path: Path) -> None:
    prev = build_catalog(tmp_path / "prev", {"a": Sp("A"), "b": Sp("B")}, {"us-ma": ["a"], "us-ny": ["b"]})
    new = build_catalog(tmp_path / "new", {"a": Sp("A"), "b": Sp("B")}, {"us-ma": ["a"]})
    res = check_shrink(new, prev)
    assert codes(res.errors) == ["shrink.region"]
    assert res.errors[0].subject == "us-ny"


def _asset_catalogs(tmp_path: Path, lost: int) -> tuple[LoadedCatalog, LoadedCatalog]:
    ids = [f"sp{i:03d}" for i in range(100)]
    prev = big(tmp_path, "prev", ids, photos=1)
    entries = dict(prev.species.entries)
    for sid in ids[:lost]:
        entries[sid] = SpeciesEntry(entries[sid].name, entries[sid].sci, [], [])
    assert prev.provenance is not None
    new = mutated_copy(prev, tmp_path / "new", species=SpeciesFile(entries), provenance=prev.provenance)
    return new, prev


def test_asset_loss_of_six_percent_is_an_error(tmp_path: Path) -> None:
    new, prev = _asset_catalogs(tmp_path, 6)
    res = check_shrink(new, prev)
    assert codes(res.errors) == ["shrink.assets"]
    assert "6 of 100" in res.errors[0].message


def test_asset_loss_of_five_percent_is_fine(tmp_path: Path) -> None:
    new, prev = _asset_catalogs(tmp_path, 5)
    assert check_shrink(new, prev).errors == []


def test_allow_shrink_downgrades_to_warnings(tmp_path: Path, hundred: list[str]) -> None:
    prev = big(tmp_path, "prev", hundred, photos=1)
    new = big(tmp_path, "new", hundred[:50], photos=1)
    strict = check_shrink(new, prev)
    assert set(codes(strict.errors)) == {"shrink.region", "shrink.assets"}
    relaxed = check_shrink(new, prev, allow_shrink=True)
    assert relaxed.errors == []
    assert set(codes(relaxed.warnings)) == {"shrink.region", "shrink.assets"}


def test_validate_catalog_only_checks_shrink_with_a_previous(tmp_path: Path, hundred: list[str]) -> None:
    prev = big(tmp_path, "prev", hundred)
    new = big(tmp_path, "new", hundred[:50])
    assert validate_catalog(new).ok
    assert codes(validate_catalog(new, prev).errors) == ["shrink.region"]
    res = validate_catalog(new, prev, allow_shrink=True)
    assert res.ok and codes(res.warnings) == ["shrink.region"]


def test_no_previous_assets_no_division_by_zero(tmp_path: Path) -> None:
    prev = build_catalog(tmp_path / "prev", {"a": Sp("A", photos=0, audios=0)})
    assert check_shrink(prev, prev).errors == []


# ---------------------------------------------------------------------------------------
# 6. Structure
# ---------------------------------------------------------------------------------------


def test_region_species_absent_from_species_json(cat: LoadedCatalog, tmp_path: Path) -> None:
    bad = mutated_copy(cat, tmp_path / "b", regions={"us-ma": ["american-robin", "ghost-bird"]})
    res = check_structure(bad)
    assert codes(res.errors) == ["region.unknown_species"]
    assert res.errors[0].subject == "ghost-bird"


def test_region_lists_a_species_twice(cat: LoadedCatalog, tmp_path: Path) -> None:
    bad = mutated_copy(cat, tmp_path / "b", regions={"us-ma": ["blue-jay", "blue-jay"]})
    assert codes(check_structure(bad).errors) == ["region.duplicate_species"]


def test_blank_names_are_errors(cat: LoadedCatalog, tmp_path: Path) -> None:
    bad = mutated_copy(cat, tmp_path / "b", species=with_species(cat, "blue-jay", name="  ", sci=" "))
    assert set(codes(check_structure(bad).errors)) == {"species.name_missing", "species.sci_missing"}


def test_a_title_containing_the_species_name_is_fine(cat: LoadedCatalog, tmp_path: Path) -> None:
    # Credits appear on the answer side only, so leakage in a title is not this gate's job.
    name = only_photo(cat, "blue-jay")
    ok = mutated_copy(cat, tmp_path / "b", provenance=with_record(cat, name, title="Blue Jay"))
    assert check_structure(ok).errors == []


# ---------------------------------------------------------------------------------------
# Result type and formatting
# ---------------------------------------------------------------------------------------


def test_result_ok_follows_errors_only() -> None:
    assert ValidationResult().ok
    assert ValidationResult(warnings=[Problem("a.b", "w")]).ok
    assert not ValidationResult(errors=[Problem("a.b", "e")]).ok


def test_format_result_lists_codes_subjects_and_a_verdict() -> None:
    res = ValidationResult(
        errors=[Problem("media.missing", "file is missing", "media/x.webp")],
        warnings=[Problem("media.orphan_file", "unused", "media/y.webp")],
    )
    text = format_result(res)
    assert text.splitlines()[0] == "validation FAILED: 1 error(s), 1 warning(s)"
    assert "ERROR [media.missing] media/x.webp: file is missing" in text
    assert "WARN  [media.orphan_file] media/y.webp: unused" in text
    assert format_result(ValidationResult()).startswith("validation PASSED")


def test_validation_is_deterministic(cat: LoadedCatalog) -> None:
    cat.media_path(only_photo(cat, "blue-jay")).unlink()
    cat.media_path(only_photo(cat, "american-robin")).unlink()
    assert validate_catalog(cat) == validate_catalog(cat)



def test_swapping_an_asset_is_not_a_loss(tmp_path: Path) -> None:
    ids = [f"sp{i:03d}" for i in range(100)]
    prev = big(tmp_path, "prev", ids, photos=1)
    assert prev.provenance is not None
    entries = dict(prev.species.entries)
    for sid in ids[:20]:
        old = entries[sid]
        swapped = MediaRef("media/" + "f" * 16 + Path(old.photo[0].file).suffix, old.photo[0].bytes, old.photo[0].credit)
        entries[sid] = SpeciesEntry(old.name, old.sci, [swapped], old.audio)
    new = mutated_copy(prev, tmp_path / "new", species=SpeciesFile(entries), provenance=prev.provenance)
    assert check_shrink(new, prev).errors == []
