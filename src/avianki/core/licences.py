"""The licence allowlist and the per-asset licence record.

The allowlist is exact and versioned (spec §4; licence research §5.2 items 1–2):
a source string is resolved to one of `ALLOWED_LICENCES` or rejected. There is no
prefix matching, so ``cc-by`` can never match ``cc-by-nd``, and anything that can't
be resolved to an exact id is rejected rather than guessed.

`AssetRecord` carries the licence research §5.1 fields, plus one flag,
``licence_version_assumed``, which records that the source gave no licence
version (iNaturalist's ``cc-by``). ADR 0012 makes credits for such assets follow
the stricter 3.0 rules, so the fact has to survive into the record.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields, replace
from typing import Any, NamedTuple

ALLOWED_LICENCES: frozenset[str] = frozenset(
    {
        "CC0-1.0",
        "PDM-1.0",
        "CC-BY-2.0",
        "CC-BY-2.5",
        "CC-BY-3.0",
        "CC-BY-4.0",
        "CC-BY-SA-2.0",
        "CC-BY-SA-2.5",
        "CC-BY-SA-3.0",
        "CC-BY-SA-4.0",
    }
)

# Canonical lower-case, hyphenated spellings → exact ids. Valid for every source.
_VERSIONED: dict[str, str] = {lid.lower(): lid for lid in ALLOWED_LICENCES} | {
    # CC0 and the Public Domain Mark exist only as 1.0, so the bare names are resolvable.
    "cc0": "CC0-1.0",
    "pdm": "PDM-1.0",
    "public-domain-mark-1.0": "PDM-1.0",
}

# iNaturalist's codes carry no version. Spec §4 accepts cc-by / cc-by-sa as 4.0 for the
# licence URL, with credits following the 3.0 rules (ADR 0012).
_INAT_UNVERSIONED: dict[str, str] = {
    "cc-by": "CC-BY-4.0",
    "cc-by-sa": "CC-BY-SA-4.0",
}

_SEPARATORS = re.compile(r"[\s_]+")
_ID_SHAPE = re.compile(r"^(?P<family>CC0|PDM|CC-BY|CC-BY-SA)-(?P<version>\d\.\d)$")


class ResolvedLicence(NamedTuple):
    licence_id: str
    version_assumed: bool


def _canonical(raw: str) -> str:
    return _SEPARATORS.sub("-", raw.strip().lower())


def resolve_licence(raw: str | None, source: str) -> ResolvedLicence | None:
    """Resolve a source-native licence string to an allowed id, or None to reject.

    ``source`` selects source-specific rules: only ``"inaturalist"`` may resolve an
    unversioned ``cc-by``/``cc-by-sa``, and then ``version_assumed`` is True.
    Commons values (``LicenseShortName`` such as ``CC BY-SA 3.0``, or ``License``
    such as ``cc-by-sa-3.0``) resolve only when they name one exact, unported version.
    """
    if not raw:
        return None
    key = _canonical(raw)
    if key in _VERSIONED:
        return ResolvedLicence(_VERSIONED[key], False)
    if source == "inaturalist" and key in _INAT_UNVERSIONED:
        return ResolvedLicence(_INAT_UNVERSIONED[key], True)
    return None


def normalise_licence(raw: str | None, source: str) -> str | None:
    """The exact allowed licence id for ``raw``, or None ("reject rather than guess")."""
    resolved = resolve_licence(raw, source)
    return resolved.licence_id if resolved else None


def is_allowed(licence_id: str) -> bool:
    """Exact membership in the allowlist. No case folding, no prefixes."""
    return licence_id in ALLOWED_LICENCES


def licence_url(licence_id: str) -> str:
    """The canonical creativecommons.org deed URL for an allowed licence id."""
    if not is_allowed(licence_id):
        raise ValueError(f"not an allowed licence id: {licence_id!r}")
    m = _ID_SHAPE.match(licence_id)
    assert m is not None  # every allowed id has this shape
    family, ver = m["family"], m["version"]
    if family == "CC0":
        return f"https://creativecommons.org/publicdomain/zero/{ver}/"
    if family == "PDM":
        return f"https://creativecommons.org/publicdomain/mark/{ver}/"
    return f"https://creativecommons.org/licenses/{family[3:].lower()}/{ver}/"


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


@dataclass(frozen=True, kw_only=True)
class AssetRecord:
    """One asset's licence and provenance record (licence research §5.1).

    ``retrieved_at`` and ``source_terms_version`` are ISO 8601 dates.
    ``modifications`` grows as pipeline stages touch the asset; see `with_modification`.
    """

    source: str
    source_asset_id: str
    source_url: str | None
    file_url: str
    licence_id: str
    licence_url: str | None
    creator: str | None
    creator_url: str | None = None
    attribution_text: str | None = None
    title: str | None = None
    copyright_notice: str | None = None
    modifications: tuple[str, ...] = ()
    prior_modifications: str | None = None
    restrictions: str | None = None
    retrieved_at: str
    source_terms_version: str | None = None
    # Not in §5.1: the source gave no licence version and licence_id's version was assumed.
    licence_version_assumed: bool = False

    def with_modification(self, text: str) -> AssetRecord:
        """A copy with ``text`` appended to ``modifications``."""
        return replace(self, modifications=(*self.modifications, text))

    def missing_required_fields(self) -> list[str]:
        """Fields a credit line can't do without (ADR 0012). Empty means creditable."""
        missing = []
        for name in ("creator", "licence_id", "licence_url", "source_url"):
            if _is_blank(getattr(self, name)):
                missing.append(name)
        if _is_blank(self.title) and title_required(self):
            missing.append("title")
        return missing

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["modifications"] = list(self.modifications)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetRecord:
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown AssetRecord fields: {sorted(unknown)}")
        kwargs = dict(data)
        if "modifications" in kwargs:
            kwargs["modifications"] = tuple(kwargs["modifications"])
        return cls(**kwargs)


def title_required(record: AssetRecord) -> bool:
    """Whether the credit line must include the title (ADR 0012).

    True for attribution licences (BY, BY-SA) at version 3.0 or earlier, and whenever
    the version was assumed rather than stated by the source. CC0 and the Public
    Domain Mark carry no attribution condition, so never. An id outside the
    allowlist gets the strict answer.
    """
    m = _ID_SHAPE.match(record.licence_id)
    if m is None:
        return True  # not an allowed id; stay on the strict side
    if m["family"] in ("CC0", "PDM"):
        return False
    if record.licence_version_assumed:
        return True
    return float(m["version"]) <= 3.0
