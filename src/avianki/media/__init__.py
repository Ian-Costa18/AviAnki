"""Media processing for the catalog pipeline.

The submodules do the work: ``images`` (resize to WebP), ``audio`` (window, filter, MP3) and
``verify`` (the BirdNET check). ``MediaError`` is re-exported here for callers that only need
to catch it.
"""

from avianki.media.errors import MediaError

__all__ = ["MediaError"]
