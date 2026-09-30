"""Driving the app's page from a test: open it, make choices, build, collect the downloads.

Everything goes through the page's own controls (labels, buttons), as a person would.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from web_support import CATALOG_DIR

# The Pick screen's region select is enabled once the manifest has loaded.
READY = "#region:not([disabled])"
DONE = "#screen-done:not([hidden])"
ERROR = "#error:not([hidden])"

NETWORK_MESSAGE = "We couldn't reach the bird catalog. Check your connection and try again."
UPDATED_MESSAGE = "AviAnki has been updated. Please reload."


def open_app(context: Any, base_url: str, query: str = "", *, ready: bool = True) -> Any:
    """A new page on the app. Uncaught page errors are collected in ``page.errors``."""
    page = context.new_page()
    page.errors = []
    page.on("pageerror", lambda exc: page.errors.append(str(exc)))
    page.goto(f"{base_url}/{query}")
    if ready:
        page.wait_for_selector(READY)
    return page


def choose(
    page: Any,
    region: str | None = None,
    *,
    tier: str | None = None,
    month: int | None = None,
    cards: tuple[str, ...] | None = None,
    subdeck: bool | None = None,
) -> None:
    """Set the picker and, when any advanced option is given, the Advanced section."""
    if region is not None:
        page.select_option("#region", label=region)
    advanced = tier is not None or month is not None or cards is not None or subdeck is not None
    if advanced and not page.locator("#advanced").evaluate("el => el.open"):
        page.click("#advanced > summary")
    if tier is not None:
        page.check(f'input[name="tier"][value="{tier}"]')
    if month is not None:
        page.select_option("#month", str(month))
    if cards is not None:
        for value in ("photo", "audio", "photo_audio"):
            page.set_checked(f'input[name="cards"][value="{value}"]', value in cards)
    if subdeck is not None:
        page.set_checked("#subdeck", subdeck)


def build(page: Any, tmp_path: Path, *, timeout: float = 90_000, **choices: Any) -> list[Path]:
    """Make the choices, press Build my deck, wait for the Done screen, return the saved downloads."""
    choose(page, **choices)
    downloads: list[Any] = []
    page.on("download", lambda download: downloads.append(download))  # noqa: PLW0108 - Playwright needs a function object
    page.click("#build")
    page.wait_for_selector(DONE, timeout=timeout)
    saved = []
    for download in downloads:
        path = tmp_path / download.suggested_filename
        download.save_as(path)
        saved.append(path)
    return saved


def visible_text(page: Any, selector: str) -> str:
    return " ".join(page.inner_text(selector).split())


# ---------------------------------------------------------------------------------------
# What the deck should contain, and Anki's verdict on it
# ---------------------------------------------------------------------------------------

DEFAULT_CARDS = ("photo", "audio")  # ADR 0010: the ticked boxes
ALL_CARDS = ("photo", "audio", "photo_audio")

# Records every text the progress line and the parts announcement show, in order.
RECORD_TEXT = """
window.__texts = [];
addEventListener('DOMContentLoaded', () => {
  for (const id of ['progress', 'parts-announce']) {
    const el = document.getElementById(id);
    new MutationObserver(() => window.__texts.push(el.textContent))
      .observe(el, { childList: true, characterData: true, subtree: true });
  }
});
"""

# Peak JS heap while building, sampled on a timer and on every progress update (Chromium only).
HEAP_SAMPLER = """
window.__peak = 0;
(() => {
  const sample = () => { if (performance.memory) window.__peak = Math.max(window.__peak, performance.memory.usedJSHeapSize); };
  setInterval(sample, 20);
  addEventListener('DOMContentLoaded', () => {
    new MutationObserver(sample).observe(document.getElementById('progress'),
      { childList: true, characterData: true, subtree: true });
  });
})();
"""

# A device that reports 4 GB of memory, which counts as constrained (ADR 0006).
CONSTRAINED = "Object.defineProperty(navigator, 'deviceMemory', { value: 4, configurable: true });"


def apkg_guids(apkg: Path, workdir: Path) -> set[str]:
    """The note GUIDs in a package, read from its SQLite collection."""
    import sqlite3
    import zipfile

    db = workdir / f"{apkg.stem}.anki2"
    with zipfile.ZipFile(apkg) as zf:
        db.write_bytes(zf.read("collection.anki2"))
    con = sqlite3.connect(db)
    try:
        return {row[0] for row in con.execute("select guid from notes")}
    finally:
        con.close()


def expected_guids(
    region: str,
    *,
    tier: str = "standard",
    month: int | None = None,
    cards: tuple[str, ...] = DEFAULT_CARDS,
    catalog_dir: Path = CATALOG_DIR,
) -> set[str]:
    """The note GUIDs the Python side (the reference) would write for this selection."""
    from avianki.catalog.format import load_catalog
    from avianki.deck.build import note_guid, plan_notes, select_species

    catalog = load_catalog(catalog_dir)
    ids = select_species(catalog.regions[region], tier=tier, month=month)
    return {note_guid(n.species_id, n.card_type) for n in plan_notes(ids, catalog.species, cards)}


def import_and_check(
    workdir: Path, apkgs: list[Path], *, catalog_dir: Path = CATALOG_DIR, species: Any = None
) -> dict[str, Any]:
    """Import ``apkgs`` into one fresh collection with Anki's backend and run the acceptance checks.

    ``species`` is the species file the credits are checked against (default: ``catalog_dir``'s).
    Media check clean (nothing missing or unused), no front gives the name away, every answer has
    its credits, one card per note. Returns what was imported, for the caller's own assertions.
    """
    pytest.importorskip("anki.collection")
    from acceptance_support import (
        assert_clean_media,
        assert_credits_on_answers,
        assert_no_name_leak,
        card_count,
        guids,
        import_apkg,
        note_count,
        open_collection,
        rendered_cards,
    )

    from avianki.catalog.format import load_catalog

    if species is None:
        species = load_catalog(catalog_dir).species
    col = open_collection(workdir / "anki-collection")
    try:
        new = 0
        for apkg in apkgs:
            new += len(import_apkg(col, apkg).log.new)
        assert note_count(col) == card_count(col) == new > 0  # one card per note, and none twice
        assert_clean_media(col)
        cards = rendered_cards(col)
        assert_no_name_leak(col, cards)
        assert_credits_on_answers(cards, species)
        return {
            "notes": note_count(col),
            "guids": guids(col),
            "decks": {d.name for d in col.decks.all_names_and_ids()},
            "cards": cards,
        }
    finally:
        col.close()
