"""Tests for avianki.catalog.select: the pure rules for sticky reuse, candidates and provenance."""

from __future__ import annotations

from dataclasses import replace

import pytest

from avianki.catalog.format import MediaRef, ProvenanceEntry, ProvenanceFile, SpeciesEntry, SpeciesFile
from avianki.catalog.pins import AssetRef, Pin
from avianki.catalog.select import (
    MAX_AUDIO_CANDIDATES,
    PHOTO_CANDIDATES,
    PreviousAsset,
    final_record,
    hard_problem,
    kind_name,
    media_ref,
    overall_order,
    previous_asset,
    provenance_entry,
    reused_media_ref,
    screen_candidates,
    slots_left,
    sticky_problem,
)
from avianki.core.licences import licence_url
from avianki.sources.contract import AssetKind, Candidate
from catalog_fakes import make_record

SID = "turdus-migratorius"
FILE = "media/0123456789abcdef.webp"
AUDIO_FILE = "media/fedcba9876543210.mp3"


def prov(kind="photo", *, token="M1", verified=None, confidence=None, **record) -> ProvenanceEntry:
    return ProvenanceEntry(make_record(**record), SID, kind, token, verified, confidence)


def asset(kind="photo", **kw) -> PreviousAsset:
    entry = prov(kind, **kw)
    ref = MediaRef(FILE if kind == "photo" else AUDIO_FILE, 1234, "old credit")
    return PreviousAsset(ref, entry)


def audio(**kw) -> PreviousAsset:
    kw.setdefault("verified", "birdnet")
    kw.setdefault("confidence", 0.8)
    return asset("audio", **kw)


def pin(**kw) -> Pin:
    return Pin(SID, "because", **kw)


def cand(token="M1", *, sid=SID, kind=AssetKind.PHOTO, width=None, height=None, **record) -> Candidate:
    return Candidate(sid, kind, token, make_record(**record), width, height)


def problem(a, *, p=None, media=None, kind=None):
    return sticky_problem(SID, kind or ("audio" if a.ref.file.endswith("mp3") else "photo"), a, p, media)


# -- sticky matrix ---------------------------------------------------------------------------------


def test_a_good_previous_photo_is_kept():
    assert problem(asset()) is None


def test_a_good_verified_audio_is_kept_and_a_pinned_one_too():
    assert problem(audio()) is None
    pinned = audio(verified="pinned", confidence=None)
    assert problem(pinned, p=pin(audio=AssetRef("commons", "M1"))) is None


def test_pinned_audio_whose_pin_was_withdrawn_is_invalidated():
    pinned = audio(verified="pinned", confidence=None)
    assert "no pin names it" in (problem(pinned) or "")
    assert "no pin names it" in (problem(pinned, p=pin(audio=AssetRef("commons", "M2"))) or "")


def test_no_provenance_record_invalidates():
    assert problem(PreviousAsset(MediaRef(FILE, 1, "c"), None)) == "no provenance record"


def test_provenance_for_another_species_or_kind_invalidates():
    other_species = PreviousAsset(MediaRef(FILE, 1, "c"), replace(prov(), species_id="blue-jay"))
    assert "blue-jay" in (problem(other_species) or "")
    other_kind = PreviousAsset(MediaRef(FILE, 1, "c"), prov("audio"))
    assert "audio" in (problem(other_kind, kind="photo") or "")


def test_an_excluded_token_invalidates_by_source_and_token():
    assert "excluded by a pin" in (problem(asset(), p=pin(exclude=(AssetRef("commons", "M1"),))) or "")
    # A different source or a different token does not match.
    assert problem(asset(), p=pin(exclude=(AssetRef("inaturalist", "M1"),))) is None
    assert problem(asset(), p=pin(exclude=(AssetRef("commons", "M2"),))) is None


def test_a_new_pin_naming_something_else_invalidates():
    assert problem(asset(), p=pin(photo=AssetRef("commons", "M99"))) == "a pin now names commons:M99"
    assert problem(audio(), p=pin(audio=AssetRef("inaturalist", "S1:2"))) == "a pin now names inaturalist:S1:2"


def test_a_pin_naming_the_kept_asset_keeps_it():
    assert problem(asset(), p=pin(photo=AssetRef("commons", "M1"))) is None


def test_a_pin_for_the_other_role_does_not_matter():
    assert problem(asset(), p=pin(audio=AssetRef("commons", "M5"))) is None


def test_a_licence_off_the_allowlist_invalidates():
    assert "not allowed" in (problem(asset(licence_id="CC-BY-NC-4.0")) or "")


def test_missing_credit_fields_invalidate():
    assert "missing credit fields: creator" in (problem(asset(creator=None)) or "")


@pytest.mark.parametrize("kind", ["photo", "audio"])
def test_a_missing_or_corrupt_media_file_invalidates(kind):
    a = audio() if kind == "audio" else asset()
    assert problem(a, media="media/x: missing") == "media: media/x: missing"


def test_unverified_audio_invalidates_but_unverified_photos_are_fine():
    assert problem(asset("audio", verified=None)) == "audio was never verified"
    assert problem(asset()) is None


def test_birdnet_audio_below_the_threshold_or_without_confidence_invalidates():
    assert "below" in (problem(audio(confidence=0.49)) or "")
    assert "below" in (problem(audio(confidence=None)) or "")
    assert problem(audio(confidence=0.5)) is None


def test_hard_problem_ignores_a_pin_that_merely_replaces_the_asset():
    a = asset()
    p = pin(photo=AssetRef("commons", "M99"))
    assert sticky_problem(SID, "photo", a, p, None) is not None
    assert hard_problem(SID, "photo", a, p, None) is None  # still publishable as a fallback
    excluded = pin(exclude=(AssetRef("commons", "M1"),))
    assert hard_problem(SID, "photo", a, excluded, None) is not None


# -- previous_asset ---------------------------------------------------------------------------------


def _previous():
    species = SpeciesFile({SID: SpeciesEntry("Robin", "Turdus", [MediaRef(FILE, 5, "c")], [])})
    provenance = ProvenanceFile({FILE: prov()})
    return species, provenance


def test_previous_asset_finds_the_role_and_its_provenance():
    species, provenance = _previous()
    got = previous_asset(species, provenance, SID, "photo")
    assert got is not None and got.ref.file == FILE and got.provenance == prov()
    assert previous_asset(species, provenance, SID, "audio") is None  # role was absent
    assert previous_asset(species, provenance, "blue-jay", "photo") is None
    assert previous_asset(None, None, SID, "photo") is None


def test_previous_asset_without_a_provenance_file_has_no_record():
    species, _ = _previous()
    got = previous_asset(species, None, SID, "photo")
    assert got is not None and got.provenance is None


# -- candidates ---------------------------------------------------------------------------------------


def screen(cands, kind=AssetKind.PHOTO, p=None):
    return screen_candidates(cands, species_id=SID, kind=kind, source="commons", pin=p)


def test_screening_keeps_source_order():
    kept, rej = screen([cand("M3"), cand("M1"), cand("M2")])
    assert [c.token for c in kept] == ["M3", "M1", "M2"] and rej == []


def test_screening_drops_excluded_wrong_species_wrong_kind_and_bad_licences():
    cands = [
        cand("M1"),
        cand("M2", sid="blue-jay"),
        cand("M3", kind=AssetKind.AUDIO),
        cand("M4", licence_id="CC-BY-NC-4.0"),
        cand("M5", creator=None),
        cand("M6"),
    ]
    kept, rej = screen(cands, p=pin(exclude=(AssetRef("commons", "M1"),)))
    assert [c.token for c in kept] == ["M6"]
    reasons = {r.token: r.reason for r in rej}
    assert reasons["M1"] == "excluded by pin"
    assert reasons["M2"].startswith("wrong target")
    assert reasons["M3"].startswith("wrong target")
    assert reasons["M4"] == "licence: CC-BY-NC-4.0"
    assert reasons["M5"].startswith("incomplete credit")
    assert all(r.species_id == SID and r.kind == "photo" and r.source == "commons" for r in rej)


def test_an_exclusion_in_another_source_does_not_apply():
    kept, rej = screen([cand("M1")], p=pin(exclude=(AssetRef("inaturalist", "M1"),)))
    assert len(kept) == 1 and rej == []


def test_small_photos_are_dropped_on_advertised_size_only():
    kept, rej = screen([cand("M1", width=799, height=500), cand("M2", width=800, height=100), cand("M3")])
    assert [c.token for c in kept] == ["M2", "M3"]
    assert rej[0].reason == "too small: 799x500"


def test_the_size_filter_is_for_photos_only():
    kept, _ = screen([cand("S1", kind=AssetKind.AUDIO, width=10, height=10)], kind=AssetKind.AUDIO)
    assert len(kept) == 1


def test_audio_rejections_say_audio():
    _, rej = screen([cand("S1", kind=AssetKind.AUDIO, licence_id="CC-BY-NC-4.0")], kind=AssetKind.AUDIO)
    assert rej[0].kind == "audio"


def test_the_audio_cap_is_five_and_counts_down():
    assert (PHOTO_CANDIDATES, MAX_AUDIO_CANDIDATES) == (5, 5)
    assert [slots_left(n) for n in (0, 2, 5, 9)] == [5, 3, 0, 0]
    assert slots_left(1, cap=3) == 2


# -- provenance and media refs ------------------------------------------------------------------------


def test_kind_name():
    assert kind_name(AssetKind.PHOTO) == "photo" and kind_name(AssetKind.AUDIO) == "audio"
    with pytest.raises(ValueError, match="not a catalog media kind"):
        kind_name(AssetKind.DESCRIPTION)


def test_final_record_appends_the_processing_steps_after_the_sources_own():
    rec = final_record(make_record(modifications=("cropped by author",)), ["resized", "converted to WebP"])
    assert rec.modifications == ("cropped by author", "resized", "converted to WebP")
    assert final_record(make_record(), []).modifications == make_record().modifications


def test_media_ref_renders_the_credit_with_the_modifications():
    ref = media_ref("photo", FILE, 999, final_record(make_record(modifications=()), ["resized"]))
    assert (ref.file, ref.bytes) == (FILE, 999)
    assert "Mdf" in ref.credit and ref.credit.endswith("resized") and "Photo:" in ref.credit
    assert media_ref("audio", AUDIO_FILE, 1, make_record()).credit.startswith("Recording:")


def test_media_ref_refuses_an_uncreditable_record():
    with pytest.raises(ValueError, match="missing required fields: creator"):
        media_ref("photo", FILE, 1, make_record(creator=None))


def test_provenance_entry_carries_verification():
    rec = make_record()
    birdnet = provenance_entry(rec, species_id=SID, kind="audio", token="M1", verified="birdnet", birdnet_confidence=0.7)
    assert (birdnet.verified, birdnet.birdnet_confidence) == ("birdnet", 0.7)
    pinned = provenance_entry(rec, species_id=SID, kind="audio", token="M1", verified="pinned")
    assert (pinned.verified, pinned.birdnet_confidence) == ("pinned", None)
    photo = provenance_entry(rec, species_id=SID, kind="photo", token="M1", verified=None)
    assert photo.verified is None
    as_dict = photo.to_dict()
    assert "verified" not in as_dict and as_dict["token"] == "M1" and as_dict["species_id"] == SID


def test_provenance_entry_rejects_inconsistent_verification():
    rec = make_record()
    with pytest.raises(ValueError, match="needs its confidence"):
        provenance_entry(rec, species_id=SID, kind="audio", token="t", verified="birdnet")
    with pytest.raises(ValueError, match="only birdnet-verified assets carry a confidence"):
        provenance_entry(rec, species_id=SID, kind="audio", token="t", verified="pinned", birdnet_confidence=0.9)


def test_reused_media_ref_rerenders_the_credit_from_provenance_and_keeps_the_file():
    a = asset(licence_id="CC-BY-4.0", licence_url=licence_url("CC-BY-4.0"), modifications=("resized",))
    ref = reused_media_ref("photo", a)
    assert (ref.file, ref.bytes) == (FILE, 1234)
    assert ref.credit != "old credit" and "CC BY 4.0" in ref.credit and "resized" in ref.credit


# -- species order ------------------------------------------------------------------------------------


def test_overall_order_is_best_rank_then_breadth_then_id():
    # a and b are both rank 1 somewhere and in two regions, so the id decides; d beats c on rank.
    assert overall_order({"us-ri": ["a", "b", "c"], "us-dc": ["b", "d", "a"]}) == ["a", "b", "d", "c"]


def test_overall_order_prefers_the_widespread_species_on_equal_rank():
    assert overall_order({"r1": ["z", "b"], "r2": ["z"], "r3": ["a"]}) == ["z", "a", "b"]


def test_overall_order_is_independent_of_region_insertion_order():
    one = {"x": ["a", "b", "c"], "y": ["c", "d"]}
    two = dict(reversed(list(one.items())))
    assert overall_order(one) == overall_order(two)


def test_overall_order_of_nothing_is_empty():
    assert overall_order({}) == [] and overall_order({"us-ri": []}) == []
