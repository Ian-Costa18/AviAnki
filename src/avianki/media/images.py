"""Photo processing: inspect, then resize and re-encode as WebP (ADR 0011).

Pure functions over bytes; no network and no disk. Everything done here is a technical
modification (proportional resize, format conversion), so the result stays a copy rather
than an adaptation (licence research 3.1 and 5.2 item 7). Each step is recorded in
``ProcessedImage.modifications`` for the asset's credit.

Requires Pillow (the ``catalog`` extra).
"""

from __future__ import annotations

import io
import logging
import warnings
from dataclasses import dataclass

from PIL import Image, ImageCms, ImageOps

from avianki.media.errors import ImageRejected, MediaError

__all__ = [
    "ImageInfo",
    "ImageRejected",
    "MediaError",
    "ProcessedImage",
    "inspect_image",
    "process_image",
]

log = logging.getLogger("bird_deck")

# Decoding a 60 MP photo needs ~180 MB; anything larger is not a sane lead image and
# is more likely a decompression bomb. Checked from the header, before pixels are decoded.
MAX_PIXELS = 60_000_000

# Below q50 WebP shows visible blocking on feathers; better to reject than ship that.
QUALITY_START = 80
QUALITY_STEP = 5
QUALITY_FLOOR = 50

_RASTER_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF", "TIFF"})
_SNIFF_BYTES = 2048
_EXIF_ORIENTATION = 0x0112


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    format: str  # Pillow format name, e.g. "JPEG"


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int
    modifications: tuple[str, ...]
    quality: int  # WebP quality the byte cap settled on


def _looks_like_svg(data: bytes) -> bool:
    head = data[:_SNIFF_BYTES].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<svg", b"<?xml", b"<!doctype svg")) or b"<svg" in head


def _decode(data: bytes) -> Image.Image:
    """Open and fully decode ``data`` as a single-frame raster image, or reject it."""
    if _looks_like_svg(data):
        raise ImageRejected("svg")
    try:
        # Pillow only warns between MAX_IMAGE_PIXELS and twice that; make it an error.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            fmt = img.format or ""
            if fmt not in _RASTER_FORMATS:
                raise ImageRejected("unsupported_format", fmt or "unknown")
            if img.width * img.height > MAX_PIXELS:
                raise ImageRejected("too_many_pixels", f"{img.width}x{img.height}")
            frames = getattr(img, "n_frames", 1)
            if frames > 1:
                raise ImageRejected("animated", f"{frames} frames")
            img.load()
    except ImageRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageRejected("too_many_pixels", str(exc)) from exc
    except Exception as exc:  # Pillow raises OSError, ValueError, SyntaxError, ... on bad data
        raise ImageRejected("unreadable", f"{type(exc).__name__}: {exc}") from exc
    return img


def inspect_image(data: bytes) -> ImageInfo:
    """Return the displayed size (after EXIF orientation) and format of a raster image.

    Raises ``ImageRejected`` for SVG (sniffed from content, never the extension),
    non-raster, unreadable, truncated, animated or oversized images.
    """
    img = _decode(data)
    width, height = img.size
    if img.getexif().get(_EXIF_ORIENTATION, 1) in (5, 6, 7, 8):
        width, height = height, width
    return ImageInfo(width=width, height=height, format=img.format or "")


def _to_srgb_rgb(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white and return an 8-bit RGB image in sRGB."""
    profile = img.info.get("icc_profile")
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        img = flat
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if profile:
        # Metadata is stripped from the output, so bake a non-sRGB profile into the pixels
        # first; otherwise Adobe RGB photos would render with washed-out colours.
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            img = ImageCms.profileToProfile(
                img, src, ImageCms.createProfile("sRGB"), outputMode="RGB"
            ) or img
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            log.debug("ICC conversion skipped: %s", exc)
    return img


def process_image(
    data: bytes,
    *,
    min_long_side: int = 800,
    target_long_side: int = 800,
    max_bytes: int = 150_000,
) -> ProcessedImage:
    """Resize to ``target_long_side`` and encode as WebP no larger than ``max_bytes``.

    Rejects (``ImageRejected``) images whose long side is under ``min_long_side``
    (``too_small``), and images that stay over ``max_bytes`` at the lowest quality
    (``too_large``). Never upscales: an image between ``min_long_side`` and
    ``target_long_side`` is re-encoded at its own size. EXIF orientation is applied, the
    result is flattened to RGB and all metadata is dropped. The output is deterministic.
    """
    img = _decode(data)
    img = ImageOps.exif_transpose(img)  # returns a transposed copy, or a copy if untouched
    width, height = img.size
    long_side = max(width, height)
    if long_side < min_long_side:
        raise ImageRejected("too_small", f"long side {long_side} px < {min_long_side} px")

    img = _to_srgb_rgb(img)
    modifications: list[str] = []
    if long_side > target_long_side:
        scale = target_long_side / long_side
        size = (
            target_long_side if width >= height else max(1, round(width * scale)),
            target_long_side if height > width else max(1, round(height * scale)),
        )
        img = img.resize(size, Image.Resampling.LANCZOS)
        modifications.append(f"resized to {target_long_side} px on the long side")
    modifications.append("transcoded to WebP")

    for quality in range(QUALITY_START, QUALITY_FLOOR - 1, -QUALITY_STEP):
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=6)
        if buf.tell() <= max_bytes:
            return ProcessedImage(
                data=buf.getvalue(),
                width=img.width,
                height=img.height,
                modifications=tuple(modifications),
                quality=quality,
            )
    raise ImageRejected("too_large", f"over {max_bytes} bytes at q{QUALITY_FLOOR}")
