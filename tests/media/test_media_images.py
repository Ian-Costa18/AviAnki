"""Tests for avianki.media.images: everything is synthesised with Pillow, no network."""

import io
import os
import struct

import pytest
from PIL import Image, ImageCms

from avianki.media import MediaError
from avianki.media.images import ImageRejected, inspect_image, process_image

RESIZED = "resized to 800 px on the long side"
TRANSCODED = "transcoded to WebP"


def _gradient(size: tuple[int, int]) -> Image.Image:
    """A smooth, photograph-like image (compresses well)."""
    w, h = size
    img = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    r, g, b = img.split()
    return Image.merge("RGB", (r, g.transpose(Image.Transpose.FLIP_LEFT_RIGHT), b))


def _noise(size: tuple[int, int]) -> Image.Image:
    """Incompressible RGB noise: the worst case for the byte cap."""
    return Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))


def _encode(img: Image.Image, fmt: str = "JPEG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def test_large_jpeg_becomes_800px_webp_under_cap():
    result = process_image(_encode(_gradient((1600, 1200))))
    assert (result.width, result.height) == (800, 600)
    assert len(result.data) <= 150_000
    assert result.modifications == (RESIZED, TRANSCODED)
    decoded = Image.open(io.BytesIO(result.data))
    assert decoded.format == "WEBP"
    assert decoded.size == (800, 600)


def test_portrait_long_side_is_the_height():
    result = process_image(_encode(_gradient((1200, 1600))))
    assert (result.width, result.height) == (600, 800)


def test_exact_800_is_not_resized():
    result = process_image(_encode(_gradient((800, 800))))
    assert (result.width, result.height) == (800, 800)
    assert result.modifications == (TRANSCODED,)


def test_799px_long_side_is_too_small():
    with pytest.raises(ImageRejected) as exc:
        process_image(_encode(_gradient((799, 500))))
    assert exc.value.reason == "too_small"


def test_min_long_side_below_target_keeps_size_without_upscaling():
    result = process_image(_encode(_gradient((700, 500))), min_long_side=600)
    assert (result.width, result.height) == (700, 500)
    assert result.modifications == (TRANSCODED,)


def test_svg_is_rejected_by_content_not_extension():
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="2000" height="2000"/>'
    for data in (svg, b"  \n<svg viewBox='0 0 10 10'></svg>"):
        with pytest.raises(ImageRejected) as exc:
            inspect_image(data)
        assert exc.value.reason == "svg"
        with pytest.raises(ImageRejected):
            process_image(data)


def test_garbage_and_empty_bytes_are_rejected():
    for data in (b"", b"definitely not an image" * 50):
        with pytest.raises(ImageRejected) as exc:
            inspect_image(data)
        assert exc.value.reason == "unreadable"


def test_truncated_jpeg_is_rejected():
    data = _encode(_noise((900, 900)))
    with pytest.raises(ImageRejected) as exc:
        inspect_image(data[: len(data) // 2])
    assert exc.value.reason == "unreadable"


def test_animated_image_is_rejected():
    frames = [Image.new("RGB", (900, 900), c) for c in ("red", "blue")]
    data = _encode(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100)
    with pytest.raises(ImageRejected) as exc:
        inspect_image(data)
    assert exc.value.reason == "animated"


def test_non_raster_format_is_rejected():
    data = _encode(Image.new("RGB", (900, 900)), "BMP")
    with pytest.raises(ImageRejected) as exc:
        inspect_image(data)
    assert exc.value.reason == "unsupported_format"


def test_pixel_cap_rejects_before_decoding(monkeypatch):
    monkeypatch.setattr("avianki.media.images.MAX_PIXELS", 1_000_000)
    with pytest.raises(ImageRejected) as exc:
        inspect_image(_encode(_gradient((1200, 1000))))
    assert exc.value.reason == "too_many_pixels"


def test_decompression_bomb_is_rejected(monkeypatch):
    # Pillow's own guard (error at 2x MAX_IMAGE_PIXELS) is the second line of defence.
    monkeypatch.setattr("avianki.media.images.MAX_PIXELS", 10**9)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100_000)
    with pytest.raises(ImageRejected) as exc:
        inspect_image(_encode(Image.new("L", (1000, 1000))))
    assert exc.value.reason == "too_many_pixels"


def test_inspect_reports_size_and_format():
    info = inspect_image(_encode(_gradient((1000, 700)), "PNG"))
    assert (info.width, info.height, info.format) == (1000, 700, "PNG")


def test_inspect_reports_displayed_size_for_rotated_exif():
    exif = Image.Exif()
    exif[0x0112] = 6
    info = inspect_image(_encode(_gradient((1000, 700)), exif=exif))
    assert (info.width, info.height) == (700, 1000)


def test_noisy_image_is_squeezed_under_cap_by_quality_stepping():
    data = _encode(_noise((4000, 3000)), quality=95)
    default = process_image(data)
    assert len(default.data) <= 150_000
    assert (default.width, default.height) == (800, 600)
    # Downscaled noise is ~120 KB at q80; a tighter cap must be met by stepping down.
    tight = process_image(data, max_bytes=90_000)
    assert len(tight.data) <= 90_000
    assert tight.quality < 80


def test_incompressible_image_is_too_large_at_the_quality_floor():
    # Barely-downscaled white noise stays over 150 KB even at q50.
    with pytest.raises(ImageRejected) as exc:
        process_image(_encode(_noise((1000, 750)), quality=95))
    assert exc.value.reason == "too_large"


def test_pathological_cap_is_too_large():
    with pytest.raises(ImageRejected) as exc:
        process_image(_encode(_gradient((1600, 1200))), max_bytes=1000)
    assert exc.value.reason == "too_large"


def test_exif_orientation_is_applied():
    src = Image.new("RGB", (1200, 900), "white")
    src.paste("red", (0, 0, 600, 900))  # left half red
    exif = Image.Exif()
    exif[0x0112] = 6  # display rotated 90 degrees clockwise
    result = process_image(_encode(src, exif=exif, quality=95))
    assert (result.width, result.height) == (600, 800)
    out = Image.open(io.BytesIO(result.data)).convert("RGB")
    # Rotating clockwise moves the red left half to the top.
    top, bottom = out.getpixel((300, 100)), out.getpixel((300, 700))
    assert top[0] > 200 and top[1] < 80
    assert bottom[1] > 200


def test_metadata_is_stripped():
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"
    exif[0x0112] = 3
    src = _gradient((1200, 900))
    data = _encode(src, exif=exif, icc_profile=b"\x00" * 128)
    result = process_image(data)
    out = Image.open(io.BytesIO(result.data))
    assert not out.getexif()
    assert "icc_profile" not in out.info
    assert "exif" not in out.info
    assert b"SecretCam" not in result.data


def test_transparency_is_flattened_onto_white():
    img = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    result = process_image(_encode(img, "PNG"))
    out = Image.open(io.BytesIO(result.data))
    assert out.mode == "RGB"
    assert all(c > 250 for c in out.getpixel((450, 450)))


def _linear_rgb_profile() -> bytes:
    """sRGB primaries with a linear (gamma 1.0) transfer curve, built by patching lcms' sRGB."""
    raw = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    tags = struct.unpack(">I", raw[128:132])[0]
    for k in range(tags):
        sig, off, _size = struct.unpack(">4sII", raw[132 + 12 * k : 144 + 12 * k])
        if sig in (b"rTRC", b"gTRC", b"bTRC"):
            raw[off + 8 : off + 10] = b"\x00\x00"  # parametric curve function 0: pure gamma
            raw[off + 12 : off + 16] = struct.pack(">i", 0x00010000)  # gamma 1.0
    return bytes(raw)


def test_non_srgb_icc_profile_is_converted_not_just_dropped():
    src = Image.new("RGB", (900, 900), (60, 60, 60))
    result = process_image(_encode(src, "PNG", icc_profile=_linear_rgb_profile()))
    out = Image.open(io.BytesIO(result.data)).convert("RGB")
    # Linear 60/255 is about sRGB 0.53, so the pixels must have been brightened.
    assert out.getpixel((10, 10))[0] > 100


def test_same_input_gives_identical_bytes():
    data = _encode(_gradient((1600, 1200)))
    assert process_image(data).data == process_image(data).data


def test_image_rejected_is_a_media_error():
    assert issubclass(ImageRejected, MediaError)
