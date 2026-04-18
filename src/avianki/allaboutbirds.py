"""Scrape species data from allaboutbirds.org.

fetch_browse_species() accepts either a full browse URL or a Google Place ID:
    https://www.allaboutbirds.org/guide/browse/filter/loc/{placeId}/
        date/all/behavior/all/size/all/colors/all/sort/score/view/list-view
"""

import html as html_mod
import logging
import re

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("bird_deck")

AAB_BASE = "https://www.allaboutbirds.org/guide"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _get(url: str, timeout: int = 15) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _extract_sci_name(soup: BeautifulSoup, slug: str, caller: str) -> str:
    info_div = soup.find("div", class_="species-info")
    if info_div:
        em = info_div.find("em")
        if em:
            sci = em.get_text(strip=True)
            log.debug("%s [%s]: sci-name from species-info>em: %r", caller, slug, sci)
            return sci
    log.debug("%s [%s]: species-info>em not found — sciName will be empty", caller, slug)
    return ""


def fetch_browse_species(url_or_place_id: str, limit: int | None = None) -> list[str]:
    """
    Scrape an allaboutbirds.org browse page and return species slugs in
    likelihood-score order (most commonly seen first).

    Accepts either the full browse URL or just the Google Place ID.
    """
    if url_or_place_id.startswith("http"):
        url = url_or_place_id
    else:
        place_id = url_or_place_id
        url = (
            f"{AAB_BASE}/browse/filter/loc/{place_id}"
            "/date/all/behavior/all/size/all/colors/all/sort/score/view/list-view"
        )

    log.info("Fetching species list from allaboutbirds.org…")
    log.debug("Browse URL: %s", url)
    try:
        soup = _get(url, timeout=20)
        slugs = list(dict.fromkeys(
            m.group(1)
            for a in soup.find_all("a", href=re.compile(r"/guide/[A-Za-z][A-Za-z_-]+/overview"))
            for m in [re.search(r"/guide/([A-Za-z][A-Za-z_\-]+)/overview", a["href"])]
            if m
        ))
        if limit:
            slugs = slugs[:limit]
        log.info("  %d species found (sorted by likelihood)", len(slugs))
        return slugs
    except Exception as e:
        log.error("Browse fetch failed: %s", e)
        return []


def slug_to_names(slug: str) -> dict:
    """
    Return {comName, sciName} by scraping the overview page.
    Used when building from an allaboutbirds URL (no eBird lookup needed).
    """
    try:
        soup = _get(f"{AAB_BASE}/{slug}/overview")

        span = soup.find("span", class_="species-name")
        if span:
            com_name = span.get_text(strip=True)
        else:
            title = soup.find("title")
            m = re.search(r"^(.+?) Overview,", title.get_text() if title else "")
            com_name = m.group(1).strip() if m else slug.replace("_", " ")

        sci_name = _extract_sci_name(soup, slug, "slug_to_names")
        log.debug("slug_to_names [%s]: comName=%r sciName=%r", slug, com_name, sci_name)
        return {"comName": com_name, "sciName": sci_name}
    except Exception as e:
        log.warning("slug_to_names failed (%s): %s", slug, e)
        return {"comName": slug.replace("_", " "), "sciName": ""}


def species_slug(com_name: str) -> str:
    """'Black-capped Chickadee' → 'Black-capped_Chickadee'"""
    return com_name.replace(" ", "_")


def fetch_overview(slug: str) -> dict:
    """
    Scrape the overview page for a species.
    Returns {desc, sciName, images} — images are up to 2 720px JPG URLs.
    """
    url = f"{AAB_BASE}/{slug}/overview"
    log.debug("AAB overview: %s", url)
    try:
        soup = _get(url)

        meta = soup.find("meta", attrs={"name": "description"})
        desc = html_mod.unescape(meta["content"]).strip() if meta else ""
        desc = re.sub(r"^<p>|</p>$", "", desc).strip()

        sci_name = _extract_sci_name(soup, slug, "fetch_overview")

        # Photos: only from photo-gallery links (excludes range map and other assets)
        photo_ids = list(dict.fromkeys(
            m.group(1)
            for a in soup.find_all("a", href=re.compile(r"/photo-gallery/"))
            for img in [a.find("img", attrs={"data-interchange": True})]
            if img
            for m in [re.search(r"/photo/(\d+)-\d+px\.jpg", img["data-interchange"])]
            if m
        ))
        images = [f"{AAB_BASE}/assets/photo/{pid}-720px.jpg" for pid in photo_ids[:2]]
        log.debug("fetch_overview [%s]: sciName=%r desc_len=%d images=%d", slug, sci_name, len(desc), len(photo_ids))

        return {"desc": desc, "sciName": sci_name, "images": images}
    except Exception as e:
        log.warning("AAB overview failed (%s): %s", slug, e)
        return {"desc": "", "images": []}


def fetch_sounds(slug: str) -> dict:
    """
    Scrape the sounds page for a species.
    Returns {calls: [url, …], songs: [url, …]} — direct MP3 URLs from allaboutbirds.
    """
    url = f"{AAB_BASE}/{slug}/sounds"
    log.debug("AAB sounds: %s", url)
    try:
        soup = _get(url)

        # jp-jplayer divs hold the MP3 URL in their `name` attr;
        # jp-flat-audio divs hold the type label in `aria-label`.
        # They are paired 1:1 by document order (index 0, 1, 2, …).
        players = soup.find_all("div", class_="jp-jplayer")
        containers = soup.find_all("div", class_="jp-flat-audio")

        calls, songs = [], []
        for player, container in zip(players, containers):
            mp3_url = player.get("name", "")
            label = container.get("aria-label", "")
            if not mp3_url:
                continue
            if "Call" in label:
                calls.append(mp3_url)
            elif "Song" in label:
                songs.append(mp3_url)

        return {"calls": calls, "songs": songs}
    except Exception as e:
        log.warning("AAB sounds failed (%s): %s", slug, e)
        return {"calls": [], "songs": []}
