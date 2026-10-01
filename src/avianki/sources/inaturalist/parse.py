"""Pure parsing and gating for iNaturalist API v1 responses: taxa, species counts, observations.

Every "this doesn't look like what iNaturalist documents" case raises `SourceError`. Every
"this observation isn't good enough" case returns a `Reject` with a reason instead, so the
caller can log it and move on: rejection is absence, a malformed response is failure (ADR 0007).

The gates here implement ADR 0011 (research grade, not captive, at least 2 identification
agreements for photos, the exact licence allowlist) and the licence research's rule that the
photo's or sound's *own* licence decides, never the observation's (§5.2 item 3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from avianki.core.http import SourceError
from avianki.core.licences import resolve_licence
from avianki.sources.contract import AssetKind

SOURCE = "inaturalist"
SITE = "https://www.inaturalist.org"

# Only these iNaturalist codes may reach the catalog. The API filters by them too, but the
# response is never trusted to have honoured the filter.
ALLOWED_CODES: tuple[str, ...] = ("cc0", "cc-by", "cc-by-sa")
_PERMISSIVENESS = {"cc0": 0, "cc-by": 1, "cc-by-sa": 2}  # tie-break after agreements (ADR 0011)

MIN_PHOTO_AGREEMENTS = 2  # ADR 0011
MIN_LONG_SIDE = 800  # ADR 0011; the size we fetch is min(original long side, LARGE_LONG_SIDE)
LARGE_LONG_SIDE = 1024

# What ffmpeg can read (iNaturalist serves wav, m4a and mp3; the rest is cheap insurance).
AUDIO_TYPES = frozenset({
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac", "audio/wav", "audio/x-wav",
    "audio/wave", "audio/ogg", "audio/webm",
})
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

# Hosts iNaturalist serves media from. A file URL anywhere else is not something we fetch.
MEDIA_HOSTS = frozenset({"static.inaturalist.org", "inaturalist-open-data.s3.amazonaws.com"})

_PHOTO_URL = re.compile(r"^(?P<base>https://[^/]+/photos/\d+/)square\.(?P<ext>jpe?g|png|webp)$", re.IGNORECASE)
_ATTRIBUTION_NAME = re.compile(r"^\(c\)\s+(?P<name>.+?),\s+(?:some|no)\s+rights\s+reserved\b", re.IGNORECASE)
_LOGIN = re.compile(r"^[A-Za-z0-9_-]+$")


def composed_title(common_name: str, sci_name: str) -> str:
    """The Work's title for an iNaturalist asset: "Common name (Scientific name)".

    iNaturalist photos and sounds have no title of their own, so AviAnki composes one the way
    iNaturalist names its observation page. The catalog build re-composes it when a kept
    asset's species is renamed (`catalog.select.retitle_for`), so both use this one format.
    """
    return f"{common_name} ({sci_name})"


def is_composed_title(title: str | None, sci_name: str) -> bool:
    """Whether ``title`` is `composed_title` for the species with ``sci_name`` (any common name)."""
    return title is not None and title.endswith(f" ({sci_name})")


def norm_name(name: str) -> str:
    """Case- and whitespace-normalised scientific name, the comparison form."""
    return " ".join(name.split()).casefold()


# ── taxa ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaxonMatch:
    taxon_id: int
    name: str  # iNaturalist's current name (differs from ours for a synonym)
    how: Literal["exact", "synonym"]


def _results(payload: Any, what: str) -> list[Mapping[str, Any]]:
    try:
        results = payload["results"]
    except (KeyError, TypeError) as e:
        raise SourceError(f"inaturalist: malformed {what} response: {e!r}") from e
    if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
        raise SourceError(f"inaturalist: malformed {what} response: 'results' is not a list of objects")
    return results


def pick_taxon(sci_name: str, payload: Any) -> TaxonMatch | None:
    """The one active bird species in a ``/taxa?q=`` response that *is* ``sci_name``, else None.

    Exact: the taxon's ``name`` is the IOC name. Synonym: iNaturalist matched the query through
    a synonym (``matched_term`` is the IOC name while ``name`` is something else), which is how
    it reports lumps and genus moves (Phalacrocorax auritus -> Nannopterum auritum). Either way
    the taxon must be an active species in Aves. Anything ambiguous returns None: absence is
    acceptable, a wrong bird is not (ADR 0008). Matching through a trinomial such as
    ``Numenius phaeopus hudsonicus`` is deliberately not a synonym match.
    """
    wanted = norm_name(sci_name)
    exact: dict[int, TaxonMatch] = {}
    synonym: dict[int, TaxonMatch] = {}
    for t in _results(payload, "taxa"):
        tid, name = t.get("id"), t.get("name")
        if not isinstance(tid, int) or isinstance(tid, bool) or not isinstance(name, str):
            raise SourceError(f"inaturalist: malformed taxon in taxa response: {t.get('id')!r}")
        if t.get("rank") != "species" or t.get("is_active") is not True or t.get("iconic_taxon_name") != "Aves":
            continue
        matched = t.get("matched_term")
        if norm_name(name) == wanted:
            exact[tid] = TaxonMatch(tid, name, "exact")
        elif isinstance(matched, str) and norm_name(matched) == wanted:
            synonym[tid] = TaxonMatch(tid, name, "synonym")
    for found in (exact, synonym):
        if len(found) == 1:
            return next(iter(found.values()))
        if len(found) > 1:
            return None  # two live taxa claim the same name; refuse to guess
    return None


def species_counts(payload: Any) -> dict[int, int]:
    """``{taxon id: observation count}`` from ``/observations/species_counts``.

    Taxa with no matching observations are absent from the response, so absent means 0 and
    the caller supplies that default. A response that says there are more rows than it holds
    is truncated and raises.
    """
    results = _results(payload, "species_counts")
    total = payload.get("total_results")
    if not isinstance(total, int) or total > len(results):
        raise SourceError(f"inaturalist: species_counts is truncated or malformed (total_results={total!r})")
    counts: dict[int, int] = {}
    for r in results:
        taxon, count = r.get("taxon"), r.get("count")
        tid = taxon.get("id") if isinstance(taxon, dict) else None
        if not isinstance(tid, int) or not isinstance(count, int) or count < 0:
            raise SourceError(f"inaturalist: malformed species_counts row: {r!r}"[:300])
        counts[tid] = count
    return counts


def is_plausible(na_count: int, expected: int, min_ratio: float) -> bool:
    """ADR 0008: a source's North American count below ``min_ratio`` of the expected one is a
    mapping error. An expected count of 0 or less says nothing, so it can't reject."""
    if expected <= 0:
        return True
    return na_count >= min_ratio * expected


# ── observations ─────────────────────────────────────────────────────────────


def observations(payload: Any) -> list[Mapping[str, Any]]:
    """The observation objects in an ``/observations`` response, shape-checked."""
    results = _results(payload, "observations")
    for o in results:
        if not isinstance(o.get("id"), int) or not isinstance(o.get("taxon"), dict):
            raise SourceError(f"inaturalist: malformed observation: id={o.get('id')!r}")
    return results


@dataclass(frozen=True)
class Reject:
    reason: str


@dataclass(frozen=True)
class Found:
    """A photo or sound that passed every gate, ready to become a `Candidate`."""

    kind: AssetKind
    observation_id: int
    asset_id: int
    file_url: str
    source_url: str
    licence_code: str  # the iNaturalist code, lower case
    licence_id: str
    licence_version_assumed: bool
    creator: str
    creator_url: str | None
    attribution_text: str | None
    agreements: int
    width: int | None
    height: int | None

    @property
    def rank_key(self) -> tuple[int, int]:
        """Sort key, best first: more agreements, then the more permissive licence (ADR 0011)."""
        return (-self.agreements, _PERMISSIVENESS[self.licence_code])


def _observation_gate(obs: Mapping[str, Any], taxon_id: int, min_agreements: int | None) -> Reject | None:
    if obs.get("quality_grade") != "research":
        return Reject(f"quality_grade {obs.get('quality_grade')!r}")
    if obs.get("captive") is not False:  # missing counts as unknown, and unknown is rejected
        return Reject("captive or captive unknown")
    taxon = obs["taxon"]
    if taxon.get("id") != taxon_id or taxon.get("rank") != "species":
        return Reject(f"taxon {taxon.get('id')!r} ({taxon.get('rank')!r}) is not species taxon {taxon_id}")
    if obs.get("identifications_most_disagree") is True:
        return Reject("identifiers disagree")
    if obs.get("spam") is True:
        return Reject("flagged as spam")
    agreements = obs.get("num_identification_agreements")
    if min_agreements is not None and (not isinstance(agreements, int) or agreements < min_agreements):
        return Reject(f"{agreements!r} identification agreements, need {min_agreements}")
    return None


def _agreements(obs: Mapping[str, Any]) -> int:
    n = obs.get("num_identification_agreements")
    return n if isinstance(n, int) and n > 0 else 0


def _licence(code: Any) -> tuple[str, str, bool] | Reject:
    """(iNat code, licence id, version assumed) for an allowlisted code, else a rejection."""
    key = code.strip().lower() if isinstance(code, str) else ""
    if key not in ALLOWED_CODES:
        return Reject(f"licence {code!r} not on the allowlist")
    resolved = resolve_licence(key, SOURCE)
    if resolved is None:  # unreachable while ALLOWED_CODES and core.licences agree
        return Reject(f"licence {code!r} does not resolve")
    return key, resolved.licence_id, resolved.version_assumed


def _clean(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    return cleaned or None


def _creator(obs: Mapping[str, Any], attribution: str | None) -> tuple[str, str | None] | Reject:
    """The creator's display name and profile URL.

    iNaturalist's ``attribution`` names the copyright holder ("(c) Name, some rights
    reserved (CC BY)") except for CC0, which names nobody, so the observer's name or login
    stands in. The profile link is only offered when the credited name is the observer's.
    """
    user = obs.get("user")
    user = user if isinstance(user, dict) else {}
    login = _clean(user.get("login"))
    name = _clean(user.get("name"))
    if user.get("spam") is True or user.get("suspended") is True:
        return Reject("observer is flagged")
    parsed = None
    if attribution:
        m = _ATTRIBUTION_NAME.match(attribution)
        parsed = _clean(m["name"]) if m else None
    display = parsed or name or login
    if not display:
        return Reject("no creator name")
    is_observer = display in (name, login)
    url = f"{SITE}/people/{login}" if login and _LOGIN.match(login) and is_observer else None
    return display, url


def large_photo(url: Any, dims: Any) -> tuple[str, int | None, int | None] | Reject:
    """The ``large`` (1024 px) URL for a photo's ``square`` URL, and its pixel size when known."""
    if not isinstance(url, str):
        return Reject("photo has no url")
    m = _PHOTO_URL.match(url)
    if m is None or urlsplit(url).hostname not in MEDIA_HOSTS:
        return Reject(f"unrecognised photo url {url!r}")  # not raster from a known host
    large = f"{m['base']}large.{m['ext'].lower()}"
    if not isinstance(dims, dict):
        return large, None, None
    w, h = dims.get("width"), dims.get("height")
    if not (isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0):
        return large, None, None
    long_side = max(w, h)
    if long_side < MIN_LONG_SIDE:
        return Reject(f"{w}x{h} is under {MIN_LONG_SIDE} px on the long side")
    if long_side > LARGE_LONG_SIDE:
        scale = LARGE_LONG_SIDE / long_side
        w, h = max(1, round(w * scale)), max(1, round(h * scale))
    return large, w, h


def _hidden_or_flagged(asset: Mapping[str, Any]) -> bool:
    return bool(asset.get("hidden")) or bool(asset.get("flags")) or bool(asset.get("moderator_actions"))


def photo_asset(obs: Mapping[str, Any], taxon_id: int, *, min_agreements: int | None = MIN_PHOTO_AGREEMENTS,
                photo_id: int | None = None) -> Found | Reject:
    """The observation's lead photo (or, for a pin, the photo with ``photo_id``) if it passes every gate."""
    if (bad := _observation_gate(obs, taxon_id, min_agreements)) is not None:
        return bad
    photos = obs.get("photos")
    if not isinstance(photos, list) or not photos:
        return Reject("no photos")
    if photo_id is None:
        photo = photos[0]  # the observer's lead photo; later ones may show something else
    else:
        photo = next((p for p in photos if isinstance(p, dict) and p.get("id") == photo_id), None)
    if not isinstance(photo, dict) or not isinstance(photo.get("id"), int):
        return Reject("photo not found in the observation")
    if _hidden_or_flagged(photo):
        return Reject("photo is hidden or flagged")
    lic = _licence(photo.get("license_code"))
    if isinstance(lic, Reject):
        return lic
    large = large_photo(photo.get("url"), photo.get("original_dimensions"))
    if isinstance(large, Reject):
        return large
    attribution = _clean(photo.get("attribution"))
    who = _creator(obs, attribution)
    if isinstance(who, Reject):
        return who
    code, licence_id, assumed = lic
    return Found(
        kind=AssetKind.PHOTO,
        observation_id=obs["id"],
        asset_id=photo["id"],
        file_url=large[0],
        source_url=f"{SITE}/photos/{photo['id']}",
        licence_code=code,
        licence_id=licence_id,
        licence_version_assumed=assumed,
        creator=who[0],
        creator_url=who[1],
        attribution_text=attribution,
        agreements=_agreements(obs),
        width=large[1],
        height=large[2],
    )


def sound_asset(obs: Mapping[str, Any], taxon_id: int, *, sound_id: int | None = None) -> Found | Reject:
    """The observation's first usable sound (or, for a pin, the sound with ``sound_id``).

    Sounds carry no identification-agreement floor (ADR 0011 ranks by agreements instead):
    research grade already means the community confirmed the species.
    """
    if (bad := _observation_gate(obs, taxon_id, None)) is not None:
        return bad
    sounds = obs.get("sounds")
    if not isinstance(sounds, list) or not sounds:
        return Reject("no sounds")
    if sound_id is not None:
        sounds = [s for s in sounds if isinstance(s, dict) and s.get("id") == sound_id]
        if not sounds:
            return Reject("sound not found in the observation")
    reasons: list[str] = []
    for sound in sounds:
        found = _sound(obs, sound)
        if isinstance(found, Found):
            return found
        reasons.append(found.reason)
    return Reject("; ".join(reasons))


def _sound(obs: Mapping[str, Any], sound: Any) -> Found | Reject:
    if not isinstance(sound, dict) or not isinstance(sound.get("id"), int):
        return Reject("malformed sound")
    if _hidden_or_flagged(sound):
        return Reject("sound is hidden or flagged")
    lic = _licence(sound.get("license_code"))
    if isinstance(lic, Reject):
        return lic
    ctype = sound.get("file_content_type")
    if not isinstance(ctype, str) or ctype.split(";")[0].strip().lower() not in AUDIO_TYPES:
        return Reject(f"sound content type {ctype!r} is not audio ffmpeg reads")
    url = sound.get("file_url")
    if not isinstance(url, str) or not url.startswith("https://") or urlsplit(url).hostname not in MEDIA_HOSTS:
        return Reject(f"unrecognised sound url {url!r}")
    attribution = _clean(sound.get("attribution"))
    who = _creator(obs, attribution)
    if isinstance(who, Reject):
        return who
    code, licence_id, assumed = lic
    return Found(
        kind=AssetKind.AUDIO,
        observation_id=obs["id"],
        asset_id=sound["id"],
        file_url=url,
        source_url=f"{SITE}/observations/{obs['id']}",  # iNaturalist has no page for a sound alone
        licence_code=code,
        licence_id=licence_id,
        licence_version_assumed=assumed,
        creator=who[0],
        creator_url=who[1],
        attribution_text=attribution,
        agreements=_agreements(obs),
        width=None,
        height=None,
    )


def ranked(found: Iterable[Found]) -> list[Found]:
    """Best first. The sort is stable, so ties keep the API's own (votes) order."""
    return sorted(found, key=lambda f: f.rank_key)
