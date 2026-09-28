"""Errors shared by the media processing modules.

Kept free of third-party imports so callers can catch them without Pillow installed.
"""


class MediaError(Exception):
    """Media could not be processed: unreadable input or a missing tool (ffmpeg)."""


class ImageRejected(MediaError):
    """An image failed a quality gate. ``reason`` is a short machine-usable token.

    Reasons: ``svg``, ``unreadable``, ``unsupported_format``, ``animated``,
    ``too_many_pixels``, ``too_small``, ``too_large``.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
