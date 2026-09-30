"""Tests for avianki.catalog.report: build-report.md, contact-sheet.html, credits.html."""

from __future__ import annotations

import html
from dataclasses import replace
import re
from pathlib import Path

import pytest

from avianki.catalog.format import (
    DatasetCredit,
    LoadedCatalog,
    MediaRef,
    ProvenanceFile,
    SpeciesFile,
)
from avianki.catalog.report import (
    BuildReport,
    PlausibilityFlag,
    Rejection,
    SourceFailure,
    render_build_report,
    render_contact_sheet,
    render_credits_page,
)
from avianki.catalog.pins import parse_pins
from avianki.catalog.validate import Problem, ValidationResult
from avianki.sources.gbif import DroppedMinority, ReResolved
from avianki.taxonomy.species import SpeciesRow, SpeciesTable
from catalog_fakes import Sp, build_catalog, mutated_copy, write_parts

EVIL = "<script>alert(1)</script>"


@pytest.fixture()
def cat(tmp_path: Path) -> LoadedCatalog:
    return build_catalog(
        tmp_path / "v1",
        {
            "wood-thrush": Sp("Wood Thrush", "Hylocichla mustelina"),
            "american-robin": Sp("American Robin", "Turdus migratorius"),
            "great-blue-heron": Sp("Great Blue Heron", "Ardea herodias", audios=0),
            "blue-jay": Sp("Blue Jay", "Cyanocitta cristata", photos=0),
        },
    )


def evil_catalog(cat: LoadedCatalog, tmp_path: Path) -> LoadedCatalog:
    """The robin's names, creator, title and pin token all carry a <script> payload."""
    assert cat.provenance is not None
    name = cat.species["american-robin"].photo[0].file
    prov = dict(cat.provenance.entries)
    entry = prov[name]
    prov[name] = replace(
        entry,
        token=EVIL,
        record=replace(entry.record, creator=EVIL, title=EVIL, source=EVIL),
    )
    species = dict(cat.species.entries)
    species["american-robin"] = replace(species["american-robin"], name=EVIL, sci=EVIL)
    return mutated_copy(
        cat, tmp_path / "evil", species=SpeciesFile(species), provenance=ProvenanceFile(prov)
    )


# ---------------------------------------------------------------------------------------
# credits.html
# ---------------------------------------------------------------------------------------


def test_credits_page_has_dataset_credit_and_modifications(cat: LoadedCatalog) -> None:
    page = render_credits_page(cat)
    assert "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF" in page
    assert '<a href="https://doi.org/10.15468/aomfnb">https://doi.org/10.15468/aomfnb</a>' in page
    assert '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>' in page
    assert "modified: filtered and ranked by region" in page
    assert "MIT-licensed" in page


def test_credits_page_lists_each_species_with_stored_credit_lines(cat: LoadedCatalog) -> None:
    page = render_credits_page(cat)
    robin = cat.species["american-robin"]
    assert f"<li>{robin.photo[0].credit}</li>" in page
    assert f"<li>{robin.audio[0].credit}</li>" in page
    assert "<i>Turdus migratorius</i>" in page


def test_credits_page_is_sorted_by_common_name(cat: LoadedCatalog) -> None:
    page = render_credits_page(cat)
    order = [page.index(n) for n in ("American Robin", "Blue Jay", "Great Blue Heron", "Wood Thrush")]
    assert order == sorted(order)


def test_credits_page_is_standalone_and_script_free(cat: LoadedCatalog) -> None:
    page = render_credits_page(cat)
    assert page.startswith("<!doctype html>")
    assert 'name="viewport"' in page
    for forbidden in ("<script", "<link", "<img", "src=", "@import", "url("):
        assert forbidden not in page


def test_credits_page_uses_only_safe_tags(cat: LoadedCatalog) -> None:
    page = render_credits_page(cat)
    tags = set(re.findall(r"<\s*/?\s*([a-zA-Z0-9]+)", page))
    assert tags <= {
        "html", "head", "meta", "title", "style", "body", "h1", "h2", "h3",
        "p", "ul", "li", "div", "a", "b", "i", "small",
    }  # fmt: skip


def test_credits_page_is_deterministic(cat: LoadedCatalog) -> None:
    assert render_credits_page(cat) == render_credits_page(cat)


def test_credits_page_omits_species_with_no_media(tmp_path: Path) -> None:
    empty = build_catalog(tmp_path / "e", {"a": Sp("Aardvark Bird", photos=0, audios=0)})
    assert "Aardvark Bird" not in render_credits_page(empty)


def test_credits_page_shows_an_unsafe_stored_credit_as_text(cat: LoadedCatalog, tmp_path: Path) -> None:
    ref = cat.species["american-robin"].photo[0]
    bad = MediaRef(ref.file, ref.bytes, ref.credit + EVIL)
    species = dict(cat.species.entries)
    species["american-robin"] = replace(species["american-robin"], photo=[bad])
    alt = mutated_copy(cat, tmp_path / "alt", species=SpeciesFile(species))
    page = render_credits_page(alt)
    assert "<script" not in page
    assert "&lt;script&gt;" in page


def test_credits_page_escapes_hostile_data(cat: LoadedCatalog, tmp_path: Path) -> None:
    page = render_credits_page(evil_catalog(cat, tmp_path))
    assert "<script" not in page
    assert "&lt;script&gt;" in page


def test_credits_page_escapes_hostile_dataset_credit(cat: LoadedCatalog, tmp_path: Path) -> None:
    assert cat.provenance is not None
    alt = write_parts(
        tmp_path / "ds",
        cat.species,
        cat.provenance,
        {"us-ma": list(cat.species)},
        media_from=cat.root,
        dataset_credits=[DatasetCredit(EVIL, "Not-A-Licence", "https://x.test/?a=\"><b>", EVIL)],
    )
    page = render_credits_page(alt)
    assert "<script" not in page
    assert '"><b>' not in page


# ---------------------------------------------------------------------------------------
# contact-sheet.html
# ---------------------------------------------------------------------------------------


def test_contact_sheet_has_a_card_per_species_with_media_elements(cat: LoadedCatalog) -> None:
    sheet = render_contact_sheet(cat, media_prefix="catalog/")
    robin = cat.species["american-robin"]
    assert f'<img loading="lazy" src="catalog/{robin.photo[0].file}" alt="American Robin">' in sheet
    assert f'<audio controls preload="none" src="catalog/{robin.audio[0].file}"></audio>' in sheet
    assert "Turdus migratorius" in sheet
    for name in ("Wood Thrush", "Great Blue Heron", "Blue Jay"):
        assert name in sheet


def test_contact_sheet_shows_source_licence_verification_and_pin_token(cat: LoadedCatalog) -> None:
    sheet = render_contact_sheet(cat)
    assert "photo from commons" in sheet
    assert "audio from inaturalist" in sheet
    assert "CC-BY-SA-3.0" in sheet
    assert "verified: birdnet" in sheet
    assert "BirdNET 0.90" in sheet
    assert "[american-robin]\nphoto = &quot;commons:american-robin-photo-0&quot;" in sheet
    assert "[american-robin]\naudio = &quot;inaturalist:american-robin-audio-0&quot;" in sheet


def test_contact_sheet_pin_lines_paste_into_pins_toml(cat: LoadedCatalog) -> None:
    snippets = [html.unescape(m) for m in re.findall(r"<pre>(.*?)</pre>", render_contact_sheet(cat), re.S)]
    assert snippets
    table = SpeciesTable([SpeciesRow(sid, e.sci, e.name) for sid, e in cat.species.items()])
    for snippet in snippets:
        assert parse_pins(snippet, table), snippet


def test_contact_sheet_lists_species_without_a_photo_first(cat: LoadedCatalog) -> None:
    sheet = render_contact_sheet(cat)
    no_photo_at = sheet.index("No photo (1)")
    all_at = sheet.index("All species with a photo")
    assert no_photo_at < sheet.index('id="sp-blue-jay"') < all_at
    assert sheet.index('id="sp-american-robin"') > all_at
    assert 'class="card nophoto"' in sheet
    assert ">no photo<" in sheet


def test_contact_sheet_lists_species_without_audio(cat: LoadedCatalog) -> None:
    sheet = render_contact_sheet(cat)
    assert "No audio (1)" in sheet
    assert '<a href="#sp-great-blue-heron">Great Blue Heron</a>' in sheet
    assert "no audio" in sheet


def test_contact_sheet_says_none_when_nothing_is_missing(tmp_path: Path) -> None:
    full = build_catalog(tmp_path / "f", {"a": Sp("A Bird")})
    sheet = render_contact_sheet(full)
    assert "No photo (0)" in sheet and "No audio (0)" in sheet
    assert sheet.count("<p>none</p>") == 2


def test_contact_sheet_is_deterministic_and_script_free(cat: LoadedCatalog) -> None:
    assert render_contact_sheet(cat) == render_contact_sheet(cat)
    assert "<script" not in render_contact_sheet(cat)


def test_contact_sheet_marks_a_missing_provenance_record(cat: LoadedCatalog) -> None:
    no_prov = LoadedCatalog(cat.root, cat.manifest, cat.regions, cat.species, None)
    assert "no provenance record" in render_contact_sheet(no_prov)


def test_contact_sheet_escapes_hostile_data(cat: LoadedCatalog, tmp_path: Path) -> None:
    sheet = render_contact_sheet(evil_catalog(cat, tmp_path), media_prefix='"><script>x</script>')
    assert "<script" not in sheet
    assert "&lt;script&gt;" in sheet


# ---------------------------------------------------------------------------------------
# BuildReport / build-report.md
# ---------------------------------------------------------------------------------------


def test_empty_report_says_none_everywhere() -> None:
    md = BuildReport(catalog_version="2026-10-01").to_markdown()
    assert md.startswith("# Build report 2026-10-01")
    for heading in (
        "## Source failures\n\nnone",
        "## Rejections (0)\n\nnone",
        "## Species without a photo (0)\n\nnone",
        "## Species without audio (0)\n\nnone",
        "## Plausibility flags (0)\n\nnone",
        "## Unmapped species (0)\n\nnone",
        "(0); eBird's own name, not the IOC entry for the key (ADR 0024)\n\nnone",
        "## Split GBIF keys that dropped over 10% of a region's records (0)\n\nnone",
    ):
        assert heading in md
    assert "SOURCE FAILURES" not in md


def full_report() -> BuildReport:
    return BuildReport(
        catalog_version="2026-10-01",
        source_failures=[
            SourceFailure("inaturalist", "blue-jay", "timeout after 3 retries"),
            SourceFailure("commons", None, "budget exhausted"),
        ],
        unfinished_species=["zebra-finch", "aardvark-bird"],
        budget_exhausted=True,
        rejections=[
            Rejection("blue-jay", "audio", "inaturalist", "123", "birdnet: best 0.31 < 0.5"),
            Rejection("blue-jay", "audio", "inaturalist", "124", "birdnet: best 0.31 < 0.5"),
            Rejection("blue-jay", "photo", "commons", "File:X.jpg", "licence: CC-BY-NC-4.0"),
        ],
        species_without_photo=["blue-jay"],
        species_without_audio=["wood-thrush", "american-robin"],
        plausibility_flags=[PlausibilityFlag("whimbrel", "inaturalist", "24 records vs 27517 expected")],
        unmapped_species={"rare-bird": ["birdnet_label", "inat_taxon_id"]},
        new_ids_discovered={"wood-thrush": {"wikipedia_title": "Wood thrush", "inat_taxon_id": "12716"}},
        reused=3,
        built=1,
        pinned_used=2,
        species_total=4,
        photos=3,
        audio=2,
        photos_by_source={"commons": 2, "inaturalist": 1},
        audio_by_source={"inaturalist": 2},
        requests_made=42,
        elapsed_s=12.34,
        notes=["dataset version unchanged"],
    )


def test_source_failures_come_first_and_are_prominent() -> None:
    md = full_report().to_markdown()
    assert "## SOURCE FAILURES" in md
    assert "**2 source call(s) FAILED.**" in md
    assert "These are not absences" in md
    assert md.index("## SOURCE FAILURES") < md.index("## Summary") < md.index("## Rejections")
    assert "- **commons** (whole run): budget exhausted" in md
    assert "- **inaturalist** blue-jay: timeout after 3 retries" in md


def test_pin_errors_are_prominent_and_absent_when_there_are_none() -> None:
    md = BuildReport(pin_errors=["blue-jay: audio pin commons:M1 no longer exists", EVIL]).to_markdown()
    assert "## PIN ERRORS" in md
    assert "**2 pin(s) could not be honoured.**" in md
    assert "- blue-jay: audio pin commons:M1 no longer exists" in md
    assert EVIL not in md  # escaped like every other untrusted string
    assert md.index("## PIN ERRORS") < md.index("## Summary")
    assert "PIN ERRORS" not in BuildReport().to_markdown()


def test_report_lists_everything_sorted() -> None:
    md = full_report().to_markdown()
    assert "Unfinished species (2): aardvark-bird, zebra-finch" in md
    assert "2 x audio / inaturalist: birdnet: best 0.31 &lt; 0.5" in md
    assert "blue-jay photo commons File:X.jpg: licence: CC-BY-NC-4.0" in md
    assert "Species without audio (2)\n\namerican-robin, wood-thrush" in md
    assert "- whimbrel (inaturalist): 24 records vs 27517 expected" in md
    assert "- rare-bird: no birdnet_label, inat_taxon_id" in md
    assert "- wood-thrush: inat_taxon_id=12716, wikipedia_title=Wood thrush" in md
    assert "- Species: 4 (1 built this run, 3 reused)" in md
    assert "- Photos: 3 (commons 2, inaturalist 1)" in md
    assert "Pinned assets used: 2" in md
    assert "elapsed: 12.3 s" in md
    assert "dataset version unchanged" in md


def test_report_is_deterministic_regardless_of_insertion_order() -> None:
    a = full_report()
    b = full_report()
    b.source_failures.reverse()
    b.rejections.reverse()
    b.species_without_audio.reverse()
    assert a.to_markdown() == b.to_markdown()


def test_render_build_report_combines_validation() -> None:
    failed = ValidationResult(
        errors=[Problem("media.missing", "file is missing", "media/abc.webp")],
        warnings=[Problem("media.orphan_file", "unused", "media/def.webp")],
    )
    md = render_build_report(full_report(), failed)
    assert "**Validation gate: FAILED: nothing is published** (1 error(s), 1 warning(s))" in md
    assert "- **media.missing** media/abc.webp: file is missing" in md
    assert "- **media.orphan_file** media/def.webp: unused" in md
    assert md.index("## SOURCE FAILURES") < md.index("## Validation errors")
    ok = render_build_report(BuildReport(), ValidationResult())
    assert "**Validation gate: PASSED**" in ok
    assert "## Validation errors\n\nnone" in ok
    assert "Validation gate" not in render_build_report(BuildReport(), None)


def test_render_build_report_without_validation_matches_to_markdown() -> None:
    assert render_build_report(full_report(), None) == full_report().to_markdown()


def test_long_lists_are_cut_with_a_count() -> None:
    r = BuildReport(rejections=[Rejection(f"sp{i:04d}", "photo", "commons", str(i), "no") for i in range(250)])
    md = r.to_markdown()
    assert "- ... and 50 more" in md
    assert "sp0199" in md and "sp0200" not in md


def test_build_report_escapes_hostile_strings() -> None:
    r = BuildReport(
        catalog_version=EVIL,
        source_failures=[SourceFailure(EVIL, EVIL, EVIL)],
        unfinished_species=[EVIL],
        rejections=[Rejection(EVIL, EVIL, EVIL, EVIL, EVIL)],
        species_without_photo=[EVIL],
        species_without_audio=[EVIL],
        plausibility_flags=[PlausibilityFlag(EVIL, EVIL, EVIL)],
        unmapped_species={EVIL: [EVIL]},
        new_ids_discovered={EVIL: {EVIL: EVIL}},
        photos_by_source={EVIL: 1},
        notes=[EVIL],
    )
    validation = ValidationResult(errors=[Problem(EVIL, EVIL, EVIL)], warnings=[Problem(EVIL, EVIL, EVIL)])
    md = render_build_report(r, validation)
    assert "<script" not in md
    assert "&lt;script&gt;" in md



def test_the_build_report_lists_re_resolved_keys_by_key_and_new_name() -> None:
    moved = ReResolved("2480487", "us-ma", "Circus cyaneus", "Hen Harrier", "Circus hudsonius", "Northern Harrier", 0.96)
    moved_ri = ReResolved("2480487", "us-ri", "Circus cyaneus", "Hen Harrier", "Circus hudsonius", "Northern Harrier",
                          0.6)
    md = BuildReport(re_resolved=[moved_ri, moved]).to_markdown()
    assert "## Re-resolved GBIF keys (1); eBird's own name, not the IOC entry for the key (ADR 0024)" in md
    assert (
        "- key 2480487: Hen Harrier (Circus cyaneus) -> Northern Harrier (Circus hudsonius); 60-96% of its "
        "records; 2 region(s): us-ma, us-ri"
    ) in md


def test_the_build_report_lists_split_keys_that_dropped_over_a_tenth() -> None:
    dropped = DroppedMinority("2474416", "us-az", "Porphyrio porphyrio", "Western Swamphen", 0.7,
                              ("Porphyrio poliocephalus",))
    md = BuildReport(dropped_minorities=[dropped]).to_markdown()
    assert "## Split GBIF keys that dropped over 10% of a region's records (1)" in md
    assert (
        "- key 2474416 in us-az: kept Western Swamphen (Porphyrio porphyrio), 70% of the key's records; "
        "dropped Porphyrio poliocephalus"
    ) in md


def test_the_build_report_escapes_hostile_re_resolved_names() -> None:
    moved = ReResolved("1", EVIL, EVIL, EVIL, EVIL, EVIL, 1.0)
    dropped = DroppedMinority("1", EVIL, EVIL, EVIL, 0.5, (EVIL,))
    md = BuildReport(re_resolved=[moved], dropped_minorities=[dropped]).to_markdown()
    assert EVIL not in md
