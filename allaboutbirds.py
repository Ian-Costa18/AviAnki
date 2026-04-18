"""Scrape species data from allaboutbirds.org.

fetch_browse_species() accepts either a full browse URL or a Google Place ID:
    https://www.allaboutbirds.org/guide/browse/filter/loc/{placeId}/
        date/all/behavior/all/size/all/colors/all/sort/score/view/list-view
"""

import html
import logging
import re

import requests

log = logging.getLogger("bird_deck")

AAB_BASE = "https://www.allaboutbirds.org/guide"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


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
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        slugs = list(dict.fromkeys(
            re.findall(r"/guide/([A-Za-z][A-Za-z_\-]+)/overview", resp.text)
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
    Return {comName, sciName} by scraping the overview page title/meta.
    Used when building from an allaboutbirds URL (no eBird lookup needed).
    """
    try:
        resp = requests.get(f"{AAB_BASE}/{slug}/overview", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html_text = resp.text
        # <title>Black-capped Chickadee Overview, All About Birds…</title>
        m_title = re.search(r"<title>([^<]+) Overview,", html_text)
        com_name = m_title.group(1).strip() if m_title else slug.replace("_", " ")
        # Scientific name appears in a consistent italics span
        m_sci = re.search(r'<em class="sci-name">([^<]+)</em>', html_text)
        if not m_sci:
            m_sci = re.search(r'<i[^>]*itemprop="name"[^>]*>([^<]+)</i>', html_text)
        sci_name = m_sci.group(1).strip() if m_sci else ""
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
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html_text = resp.text

        m = re.search(r'<meta name="description" content="([^"]+)"', html_text)
        desc = html.unescape(m.group(1)).strip() if m else ""
        desc = re.sub(r"^<p>|</p>$", "", desc).strip()

        m_sci = re.search(r'<em class="sci-name">([^<]+)</em>', html_text)
        if not m_sci:
            m_sci = re.search(r'<i[^>]*itemprop="name"[^>]*>([^<]+)</i>', html_text)
        sci_name = m_sci.group(1).strip() if m_sci else ""

        photo_ids = list(dict.fromkeys(
            re.findall(r'/guide/assets/photo/(\d+)-\d+px\.jpg', html_text)
        ))
        images = [f"{AAB_BASE}/assets/photo/{pid}-720px.jpg" for pid in photo_ids[:2]]

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
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html_text = resp.text

        # Each entry: jp-jplayer name="URL" ... jp-flat-audio aria-label="Song|Calls|..."
        entries = re.findall(
            r'name="(https://www\.allaboutbirds\.org/guide/assets/sound/\d+\.mp3)"'
            r'.*?aria-label="([^"]+)"',
            html_text,
            re.DOTALL,
        )
        calls = [u for u, label in entries if "Call" in label]
        songs = [u for u, label in entries if "Song" in label]
        return {"calls": calls, "songs": songs}
    except Exception as e:
        log.warning("AAB sounds failed (%s): %s", slug, e)
        return {"calls": [], "songs": []}
