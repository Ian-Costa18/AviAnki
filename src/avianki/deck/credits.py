"""The Credits field and the deck description (ADR 0012, ADR 0016).

Asset credits arrive as pipeline-rendered, already escaped HTML (spec section 5), so
`credits_field` joins them without escaping again. Everything else that reaches the
description from the manifest is data and is escaped here.
"""

from __future__ import annotations

import html
from typing import Final

from avianki.catalog.format import DatasetCredit, Manifest, MediaRef

# ADR 0016's "What you'll see" text, split into the three lines the description carries.
STUDY_GUIDANCE: Final[tuple[str, ...]] = (
    "Look at the photo or listen, think of the name, then tap Show Answer.",
    "Tap Good if you knew it and Again if you didn't.",
    "Anki starts you on 20 new cards a day so you're never swamped. "
    "The rest arrive day by day. That's normal, not broken.",
)

# ADR 0012, verbatim.
LICENCE_NOTICE: Final[str] = (
    "This deck is a compilation. AviAnki's templates and selection are MIT-licensed. "
    "Each photo and recording keeps its own licence, credited on its card, "
    "and no further terms are imposed on it."
)

EBIRD_NOTICE: Final[str] = (
    "Built from eBird data for personal use. "
    "eBird's terms don't allow redistributing this deck."
)


def credits_field(photo: MediaRef | None, audio: MediaRef | None) -> str:
    """One ``<div class="credits">`` holding the credit line of each asset actually used.

    The lines come only from the assets passed, never from other media the species happens
    to have. Returns ``""`` when no asset is used, so the answer side shows no empty box.
    """
    lines = [m.credit for m in (photo, audio) if m is not None]
    if not lines:
        return ""
    return '<div class="credits">' + "<br>".join(lines) + "</div>"


def _dataset_credit(c: DatasetCredit) -> str:
    text = html.escape(c.text)
    licence = html.escape(c.licence_id)
    url = html.escape(c.url, quote=True)
    line = f'{text}, {licence}, <a href="{url}">{html.escape(c.url)}</a>'
    if c.modifications:
        line += f" (modified: {html.escape(c.modifications)})"
    return f"<p>{line}</p>"


def deck_description(manifest: Manifest, *, ebird: bool) -> str:
    """The HTML shown on the deck overview in every Anki client (ADR 0012).

    In order: three lines of study guidance, each dataset credit from the manifest (the
    eBird Observation Dataset, and the IOC World Bird List when the manifest lists it), the
    compilation and licence notice, and for ``--ebird`` builds the not-for-redistribution
    line.
    """
    parts = ["<p>" + "<br>".join(STUDY_GUIDANCE) + "</p>"]
    parts.extend(_dataset_credit(c) for c in manifest.dataset_credits)
    parts.append(f"<p>{LICENCE_NOTICE}</p>")
    if ebird:
        parts.append(f"<p>{EBIRD_NOTICE}</p>")
    return "\n".join(parts)
