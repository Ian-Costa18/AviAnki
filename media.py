"""Media download, caching, and ffmpeg trimming."""

import logging
import os
import subprocess

import requests

log = logging.getLogger("bird_deck")

AUDIO_MAX_SECONDS = 10
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def find_cached(media_dir: str, base: str, exts: list[str]) -> str | None:
    """Return 'base.ext' if a file with any of the given extensions exists, else None."""
    for ext in exts:
        if os.path.exists(os.path.join(media_dir, base + ext)):
            return base + ext
    return None


def find_cached_image(media_dir: str, base: str) -> str | None:
    return find_cached(media_dir, base, [".jpg", ".jpeg", ".png", ".webp"])


def find_cached_audio(media_dir: str, base: str) -> str | None:
    return find_cached(media_dir, base, [".mp3", ".wav", ".ogg"])


def download_file(url: str, path: str) -> bool:
    """Download a URL to a local path. Returns True on success."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)
        return True
    except Exception as e:
        log.warning("Download failed (%s): %s", url, e)
        return False


def trim_to_mp3(src: str, dst: str, seconds: int = AUDIO_MAX_SECONDS) -> bool:
    """Trim audio to `seconds` and re-encode as MP3 via ffmpeg. Returns True on success."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", src,
             "-t", str(seconds),
             "-acodec", "libmp3lame", "-q:a", "4",
             dst],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception as e:
        log.warning("ffmpeg trim failed (%s): %s", src, e)
        return False
