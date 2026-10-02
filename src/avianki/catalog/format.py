"""The published catalog format: the contract between the Python pipeline and the browser.

Spec section 5 is the readable version; this module is the code version. It holds

* frozen dataclasses for every file (``to_dict`` / ``from_dict``),
* JSON Schemas (draft 2020-12) and ``validate_*`` functions that raise `FormatError`,
* content-addressing helpers (`media_filename`, `canonical_json`, `hashed_name`),
* `write_catalog` / `load_catalog`, which the pipeline uses to write a build and to load
  the previous release as state (ADR 0014), and which the validation gate reuses.

The format is neutral about Anki (ADR 0013): no GUIDs, note types or ``[sound:]`` tags.

Compatibility (spec section 5): adding *optional* keys doesn't change ``format``, so
readers here ignore keys they don't know and the schemas never set
``additionalProperties: false``. Anything else bumps `FORMAT_VERSION`.

Only ``avianki.core`` and third-party ``jsonschema`` may be imported here (dependency
rule). ``jsonschema`` is an optional extra (``avianki[catalog]``) and is imported lazily,
so the dataclasses and helpers also work in a downstream install without it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal

from avianki.core.licences import AssetRecord

FORMAT_VERSION = 1
AUDIO_RULE = 2  # ADR 0031: how audio is chosen. Audio recorded under an older rule is re-selected once.
MONTHS = 12
MANIFEST_NAME = "manifest.json"
# Where the published catalog lives (the web-app spec's example). Here rather than in
# catalog.build so the downstream client can use it without importing the pipeline; the
# build writes it into the manifest by default (`avianki-catalog build --base-url`).
DEFAULT_BASE_URL = "https://ian-costa18.github.io/AviAnki/catalog/"
MEDIA_EXTENSIONS = ("webp", "mp3")

Kind = Literal["photo", "audio"]
Verified = Literal["birdnet", "pinned"]

# ---------------------------------------------------------------------------------------
# Errors and content addressing
# ---------------------------------------------------------------------------------------

_MEDIA_NAME = re.compile(r"^media/[0-9a-f]{16}\.(?:webp|mp3)$")


class FormatError(ValueError):
    """A catalog file that violates the published format (schema, hash or consistency)."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def media_filename(data: bytes, ext: str) -> str:
    """``media/<first 16 hex of sha256(data)>.<ext>``; ``ext`` is ``webp`` or ``mp3``."""
    if ext not in MEDIA_EXTENSIONS:
        raise ValueError(f"media extension must be one of {MEDIA_EXTENSIONS}, got {ext!r}")
    return f"media/{_sha256_hex(data)[:16]}.{ext}"


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, UTF-8 (not ASCII-escaped).

    List order is preserved: region files are in rank order, so it is data.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def hashed_name(stem: str, obj: Any, subdir: str = "") -> str:
    """``[<subdir>/]<stem>.<first 8 hex of sha256(canonical_json(obj))>.json`` (ADR 0013).

    ``hashed_name("species", d)`` -> ``species.3f9a0c21.json``;
    ``hashed_name("us-ma", d, "regions")`` -> ``regions/us-ma.8c1e44d0.json``.
    """
    name = f"{stem}.{_sha256_hex(canonical_json(obj))[:8]}.json"
    subdir = subdir.strip("/")
    return f"{subdir}/{name}" if subdir else name


def file_digest16(path: Path) -> str:
    """First 16 hex of the sha256 of a file's bytes, read in chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegionRef:
    """One manifest row: where a region's species list lives."""

    slug: str
    name: str
    country: str
    file: str
    species_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "country": self.country,
            "file": self.file,
            "species_count": self.species_count,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RegionRef:
        return cls(d["slug"], d["name"], d["country"], d["file"], d["species_count"])


@dataclass(frozen=True)
class DatasetCredit:
    """Deck-level credit for a dataset (ADR 0012), e.g. the eBird Observation Dataset."""

    text: str
    licence_id: str
    url: str
    modifications: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "licence_id": self.licence_id,
            "url": self.url,
            "modifications": self.modifications,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> DatasetCredit:
        return cls(d["text"], d["licence_id"], d["url"], d["modifications"])


@dataclass(frozen=True)
class Manifest:
    """``manifest.json``: small, fetched on every visit; everything else is found from it.

    ``provenance_file`` is an optional key beyond spec section 5's example. It is how the
    audit file is found (the app never loads it), and readers may ignore it. So is
    ``eod_version``: the eBird Observation Dataset version the region lists came from
    (informational; the build stamps it, nothing reads it back).
    """

    catalog_version: str
    base_url: str
    gadm_version: str
    species_file: str
    regions: list[RegionRef]
    dataset_credits: list[DatasetCredit]
    total_bytes: int
    provenance_file: str | None = None
    eod_version: str | None = None
    format: int = FORMAT_VERSION

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "format": self.format,
            "catalog_version": self.catalog_version,
            "base_url": self.base_url,
            "gadm_version": self.gadm_version,
            "species_file": self.species_file,
            "regions": [r.to_dict() for r in self.regions],
            "dataset_credits": [c.to_dict() for c in self.dataset_credits],
            "total_bytes": self.total_bytes,
        }
        if self.provenance_file is not None:
            d["provenance_file"] = self.provenance_file
        if self.eod_version is not None:
            d["eod_version"] = self.eod_version
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Manifest:
        return cls(
            catalog_version=d["catalog_version"],
            base_url=d["base_url"],
            gadm_version=d["gadm_version"],
            species_file=d["species_file"],
            regions=[RegionRef.from_dict(r) for r in d["regions"]],
            dataset_credits=[DatasetCredit.from_dict(c) for c in d["dataset_credits"]],
            total_bytes=d["total_bytes"],
            provenance_file=d.get("provenance_file"),
            eod_version=d.get("eod_version"),
            format=d["format"],
        )


@dataclass(frozen=True)
class RegionFile:
    """``regions/<slug>.<hash>.json``: species in rank order, each with 12 monthly values.

    ``species`` is a list of ``(species_id, monthly)`` where ``monthly`` is January-first
    relative frequencies, each 0..255.
    """

    slug: str
    species: list[tuple[str, tuple[int, ...]]]

    def to_dict(self) -> dict[str, Any]:
        return {"slug": self.slug, "species": [[sid, list(m)] for sid, m in self.species]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RegionFile:
        return cls(d["slug"], [(sid, tuple(m)) for sid, m in d["species"]])


@dataclass(frozen=True)
class MediaRef:
    """One chosen asset: its content-addressed file, size, and rendered credit HTML."""

    file: str
    bytes: int
    credit: str

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "bytes": self.bytes, "credit": self.credit}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> MediaRef:
        return cls(d["file"], d["bytes"], d["credit"])


@dataclass(frozen=True)
class SpeciesEntry:
    """A species' names and chosen media. An empty ``photo`` or ``audio`` list is absence.

    ``ioc_name`` is the IOC English name, set only where it differs from ``name`` (ADR 0027).
    It is optional: the key is omitted when empty, and a catalog without it reads as "".
    """

    name: str
    sci: str
    photo: list[MediaRef]
    audio: list[MediaRef]
    ioc_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "sci": self.sci,
            "photo": [m.to_dict() for m in self.photo],
            "audio": [m.to_dict() for m in self.audio],
        }
        if self.ioc_name:
            d["ioc_name"] = self.ioc_name
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SpeciesEntry:
        return cls(
            d["name"],
            d["sci"],
            [MediaRef.from_dict(m) for m in d["photo"]],
            [MediaRef.from_dict(m) for m in d["audio"]],
            d.get("ioc_name", ""),
        )


@dataclass(frozen=True)
class SpeciesFile:
    """``species.<hash>.json``: every species id -> `SpeciesEntry`. Behaves as a mapping."""

    entries: dict[str, SpeciesEntry]

    def __getitem__(self, species_id: str) -> SpeciesEntry:
        return self.entries[species_id]

    def __contains__(self, species_id: object) -> bool:
        return species_id in self.entries

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def items(self) -> Iterator[tuple[str, SpeciesEntry]]:
        return iter(self.entries.items())

    def to_dict(self) -> dict[str, Any]:
        return {sid: e.to_dict() for sid, e in self.entries.items()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SpeciesFile:
        return cls({sid: SpeciesEntry.from_dict(e) for sid, e in d.items()})


_RECORD_FIELDS = frozenset(f.name for f in fields(AssetRecord))


@dataclass(frozen=True)
class ProvenanceEntry:
    """One media file's audit record: licence research 5.1's `AssetRecord` plus pipeline keys.

    The JSON is flat: the record's fields, then ``species_id``, ``kind`` and ``token`` (the
    source-native pin token, so stickiness and pins can find the asset again), and the
    optional ``verified`` (``"birdnet"`` or ``"pinned"``) and ``birdnet_confidence``. Audio
    chosen under ADR 0031 also carries ``audio_rule`` (the selection rule's version) and the
    shipped clip's ``presence``, ``competitor`` and ``quality`` scores. Pinned audio has none.
    """

    record: AssetRecord
    species_id: str
    kind: Kind
    token: str
    verified: Verified | None = None
    birdnet_confidence: float | None = None
    audio_rule: int | None = None
    presence: float | None = None
    competitor: float | None = None
    quality: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = self.record.to_dict()
        d.update({"species_id": self.species_id, "kind": self.kind, "token": self.token})
        if self.verified is not None:
            d["verified"] = self.verified
        if self.birdnet_confidence is not None:
            d["birdnet_confidence"] = self.birdnet_confidence
        for key in ("audio_rule", "presence", "competitor", "quality"):
            if getattr(self, key) is not None:
                d[key] = getattr(self, key)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ProvenanceEntry:
        # Keys this version doesn't know are optional additions from a newer writer; drop
        # them rather than fail (spec section 5, "Compatibility").
        record = AssetRecord.from_dict({k: v for k, v in d.items() if k in _RECORD_FIELDS})
        return cls(
            record=record,
            species_id=d["species_id"],
            kind=d["kind"],
            token=d["token"],
            verified=d.get("verified"),
            birdnet_confidence=d.get("birdnet_confidence"),
            audio_rule=d.get("audio_rule"),
            presence=d.get("presence"),
            competitor=d.get("competitor"),
            quality=d.get("quality"),
        )


@dataclass(frozen=True)
class ProvenanceFile:
    """``provenance.<hash>.json``: media filename -> `ProvenanceEntry`. Audit only."""

    entries: dict[str, ProvenanceEntry]

    def __getitem__(self, media_file: str) -> ProvenanceEntry:
        return self.entries[media_file]

    def __contains__(self, media_file: object) -> bool:
        return media_file in self.entries

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def items(self) -> Iterator[tuple[str, ProvenanceEntry]]:
        return iter(self.entries.items())

    def to_dict(self) -> dict[str, Any]:
        return {name: e.to_dict() for name, e in self.entries.items()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ProvenanceFile:
        return cls({name: ProvenanceEntry.from_dict(e) for name, e in d.items()})


# ---------------------------------------------------------------------------------------
# JSON Schemas (draft 2020-12). Deliberately open: no additionalProperties: false.
# ---------------------------------------------------------------------------------------

_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_SLUG: dict[str, Any] = {"type": "string", "pattern": _SLUG_PATTERN}
_NONEMPTY: dict[str, Any] = {"type": "string", "minLength": 1}
_HTTP_URL: dict[str, Any] = {"type": "string", "pattern": r"^https?://\S+$"}
_NULLABLE_STR: dict[str, Any] = {"type": ["string", "null"]}
_DATE: dict[str, Any] = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_MONTHLY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "integer", "minimum": 0, "maximum": 255},
    "minItems": MONTHS,
    "maxItems": MONTHS,
}


def _media_file(ext: str | None = None) -> dict[str, Any]:
    return {"type": "string", "pattern": rf"^media/[0-9a-f]{{16}}\.{ext or '(?:webp|mp3)'}$"}


def _media_ref(ext: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["file", "bytes", "credit"],
        "properties": {
            "file": _media_file(ext),
            "bytes": {"type": "integer", "minimum": 1},
            "credit": _NONEMPTY,
        },
    }


_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": _SCHEMA_DIALECT,
    "title": "AviAnki catalog manifest",
    "type": "object",
    "required": [
        "format",
        "catalog_version",
        "base_url",
        "gadm_version",
        "species_file",
        "regions",
        "dataset_credits",
        "total_bytes",
    ],
    "properties": {
        "format": {"const": FORMAT_VERSION},
        "catalog_version": _DATE,
        "base_url": _NONEMPTY,
        "gadm_version": _NONEMPTY,
        "species_file": {"type": "string", "pattern": r"^species\.[0-9a-f]{8}\.json$"},
        "provenance_file": {"type": "string", "pattern": r"^provenance\.[0-9a-f]{8}\.json$"},
        "eod_version": _NONEMPTY,
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slug", "name", "country", "file", "species_count"],
                "properties": {
                    "slug": _SLUG,
                    "name": _NONEMPTY,
                    "country": _NONEMPTY,
                    "file": {
                        "type": "string",
                        "pattern": r"^regions/[a-z0-9]+(?:-[a-z0-9]+)*\.[0-9a-f]{8}\.json$",
                    },
                    "species_count": {"type": "integer", "minimum": 0},
                },
            },
        },
        "dataset_credits": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "licence_id", "url", "modifications"],
                "properties": {
                    "text": _NONEMPTY,
                    "licence_id": _NONEMPTY,
                    "url": _HTTP_URL,
                    "modifications": {"type": "string"},
                },
            },
        },
        "total_bytes": {"type": "integer", "minimum": 0},
    },
}

REGION_SCHEMA: dict[str, Any] = {
    "$schema": _SCHEMA_DIALECT,
    "title": "AviAnki catalog region file",
    "type": "object",
    "required": ["slug", "species"],
    "properties": {
        "slug": _SLUG,
        "species": {
            "type": "array",
            "items": {
                "type": "array",
                "prefixItems": [_SLUG, _MONTHLY],
                "items": False,
                "minItems": 2,
            },
        },
    },
}

SPECIES_SCHEMA: dict[str, Any] = {
    "$schema": _SCHEMA_DIALECT,
    "title": "AviAnki catalog species file",
    "type": "object",
    "propertyNames": _SLUG,
    "additionalProperties": {
        "type": "object",
        "required": ["name", "sci", "photo", "audio"],
        "properties": {
            "name": _NONEMPTY,
            "sci": _NONEMPTY,
            "ioc_name": _NONEMPTY,  # optional (ADR 0027)
            "photo": {"type": "array", "items": _media_ref("webp")},
            "audio": {"type": "array", "items": _media_ref("mp3")},
        },
    },
}

PROVENANCE_SCHEMA: dict[str, Any] = {
    "$schema": _SCHEMA_DIALECT,
    "title": "AviAnki catalog provenance file",
    "type": "object",
    "propertyNames": _media_file(),
    "additionalProperties": {
        "type": "object",
        # Licence research 5.1 record, plus the pipeline's species_id/kind/token.
        "required": [
            "source",
            "source_asset_id",
            "source_url",
            "file_url",
            "licence_id",
            "licence_url",
            "creator",
            "retrieved_at",
            "species_id",
            "kind",
            "token",
        ],
        "properties": {
            "source": _NONEMPTY,
            "source_asset_id": _NONEMPTY,
            "source_url": _NULLABLE_STR,
            "file_url": _NONEMPTY,
            "licence_id": _NONEMPTY,
            "licence_url": _NULLABLE_STR,
            "creator": _NULLABLE_STR,
            "creator_url": _NULLABLE_STR,
            "attribution_text": _NULLABLE_STR,
            "title": _NULLABLE_STR,
            "copyright_notice": _NULLABLE_STR,
            "modifications": {"type": "array", "items": {"type": "string"}},
            "prior_modifications": _NULLABLE_STR,
            "restrictions": _NULLABLE_STR,
            "retrieved_at": _DATE,
            "source_terms_version": _NULLABLE_STR,
            "licence_version_assumed": {"type": "boolean"},
            "species_id": _SLUG,
            "kind": {"enum": ["photo", "audio"]},
            "token": _NONEMPTY,
            "verified": {"enum": ["birdnet", "pinned", None]},
            "birdnet_confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "audio_rule": {"type": ["integer", "null"], "minimum": 1},
            "presence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "competitor": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            # mean target confidence less the competitor's excess over 0.3: from -0.7 to 1
            "quality": {"type": ["number", "null"], "minimum": -1, "maximum": 1},
        },
    },
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "manifest": MANIFEST_SCHEMA,
    "region": REGION_SCHEMA,
    "species": SPECIES_SCHEMA,
    "provenance": PROVENANCE_SCHEMA,
}


def _path_str(path: Sequence[Any]) -> str:
    out = "$"
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


def _validate(obj: Any, what: str) -> None:
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import best_match
    except ImportError as exc:  # pragma: no cover - only without the optional extra
        raise RuntimeError(
            "validating the catalog format needs jsonschema: pip install 'avianki[catalog]'"
        ) from exc
    error = best_match(Draft202012Validator(SCHEMAS[what]).iter_errors(obj))
    if error is not None:
        message = error.message if len(error.message) <= 300 else error.message[:300] + "..."
        raise FormatError(f"{what} file invalid at {_path_str(list(error.absolute_path))}: {message}")


def validate_manifest(obj: Any) -> None:
    """Raise `FormatError` (path-qualified) unless ``obj`` matches `MANIFEST_SCHEMA`."""
    _validate(obj, "manifest")


def validate_region(obj: Any) -> None:
    """Raise `FormatError` unless ``obj`` matches `REGION_SCHEMA`."""
    _validate(obj, "region")


def validate_species(obj: Any) -> None:
    """Raise `FormatError` unless ``obj`` matches `SPECIES_SCHEMA`."""
    _validate(obj, "species")


def validate_provenance(obj: Any) -> None:
    """Raise `FormatError` unless ``obj`` matches `PROVENANCE_SCHEMA`."""
    _validate(obj, "provenance")


# ---------------------------------------------------------------------------------------
# Writing and loading a catalog directory
# ---------------------------------------------------------------------------------------


def write_media(out_dir: Path, data: bytes, ext: str) -> str:
    """Write ``data`` to ``out_dir/media/<hash>.<ext>``; return the catalog-relative name."""
    name = media_filename(data, ext)
    path = out_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():  # content-addressed: an existing file is identical
        path.write_bytes(data)
    return name


def _write_hashed(out_dir: Path, stem: str, obj: Any, subdir: str = "") -> tuple[str, int]:
    name = hashed_name(stem, obj, subdir)
    data = canonical_json(obj)
    path = out_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return name, len(data)


def write_catalog(
    out_dir: Path,
    manifest: Manifest,
    regions: Sequence[RegionFile],
    species: SpeciesFile,
    provenance: ProvenanceFile,
) -> Manifest:
    """Write the hashed JSON files and ``manifest.json`` into ``out_dir``; return the manifest.

    ``manifest`` is a template: its ``catalog_version``, ``base_url``, ``gadm_version``,
    ``dataset_credits`` and the ``name``/``country``/order of ``regions`` are kept (one
    `RegionRef` per `RegionFile`, matched by slug; their ``file`` and ``species_count``
    are ignored). ``species_file``, ``provenance_file``, every region ``file`` and
    ``species_count``, and ``total_bytes`` are recomputed and returned in the manifest
    that was written. ``total_bytes`` is each distinct media file's size plus the size of
    the hashed JSON files (not the manifest itself).

    All inputs are schema-validated before anything is written. Media is not written
    here: the pipeline puts it in ``out_dir/media/`` with `write_media`.
    """
    region_by_slug = {r.slug: r for r in regions}
    if len(region_by_slug) != len(regions):
        raise FormatError("duplicate region slugs in the regions to write")
    refs = {r.slug: r for r in manifest.regions}
    if set(refs) != set(region_by_slug) or len(refs) != len(manifest.regions):
        raise FormatError(
            "manifest.regions and regions disagree: "
            f"only in manifest {sorted(set(refs) - set(region_by_slug))}, "
            f"only in regions {sorted(set(region_by_slug) - set(refs))}"
        )
    validate_species(species.to_dict())
    validate_provenance(provenance.to_dict())
    for r in regions:
        validate_region(r.to_dict())

    media_bytes: dict[str, int] = {}
    for entry in species.entries.values():
        for m in (*entry.photo, *entry.audio):
            media_bytes[m.file] = m.bytes

    json_bytes = 0
    species_file, n = _write_hashed(out_dir, "species", species.to_dict())
    json_bytes += n
    provenance_file, n = _write_hashed(out_dir, "provenance", provenance.to_dict())
    json_bytes += n
    new_refs: list[RegionRef] = []
    for ref in manifest.regions:
        region = region_by_slug[ref.slug]
        file, n = _write_hashed(out_dir, region.slug, region.to_dict(), "regions")
        json_bytes += n
        new_refs.append(
            RegionRef(ref.slug, ref.name, ref.country, file, len(region.species))
        )

    written = Manifest(
        catalog_version=manifest.catalog_version,
        base_url=manifest.base_url,
        gadm_version=manifest.gadm_version,
        species_file=species_file,
        regions=new_refs,
        dataset_credits=list(manifest.dataset_credits),
        total_bytes=sum(media_bytes.values()) + json_bytes,
        provenance_file=provenance_file,
        eod_version=manifest.eod_version,
        format=manifest.format,
    )
    manifest_dict = written.to_dict()
    validate_manifest(manifest_dict)
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest_dict, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return written


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FormatError(f"missing catalog file: {path}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormatError(f"unreadable catalog file {path}: {exc}") from exc


def _check_hashed(name: str, obj: Any) -> None:
    """The hash in a hashed JSON file's name must match its canonical content."""
    m = re.search(r"\.([0-9a-f]{8})\.json$", name)
    if m is None or m.group(1) != _sha256_hex(canonical_json(obj))[:8]:
        raise FormatError(f"{name}: content does not match the hash in its name")


@dataclass(frozen=True)
class LoadedCatalog:
    """A catalog directory read and schema-validated by `load_catalog`.

    ``provenance`` is None only for a manifest without ``provenance_file``.
    """

    root: Path
    manifest: Manifest
    regions: dict[str, RegionFile]
    species: SpeciesFile
    provenance: ProvenanceFile | None

    def media_path(self, name: str) -> Path:
        """The path of a catalog-relative media name (``media/<16 hex>.<ext>``)."""
        if not _MEDIA_NAME.match(name):
            raise FormatError(f"not a catalog media filename: {name!r}")
        return self.root / name

    def referenced_media(self) -> dict[str, MediaRef]:
        """Every media file the species file references, by name."""
        out: dict[str, MediaRef] = {}
        for entry in self.species.entries.values():
            for m in (*entry.photo, *entry.audio):
                out[m.file] = m
        return out

    def media_problem(self, name: str, expected_bytes: int | None = None) -> str | None:
        """Why ``name`` isn't a good media file (missing / wrong size / bytes don't hash to
        the name), or None when it is fine."""
        path = self.media_path(name)
        if not path.is_file():
            return f"{name}: missing"
        if expected_bytes is not None and path.stat().st_size != expected_bytes:
            return f"{name}: {path.stat().st_size} bytes on disk, {expected_bytes} in the catalog"
        if file_digest16(path) != name.split("/")[-1].split(".")[0]:
            return f"{name}: content does not hash to its filename"
        return None

    def media_problems(self) -> list[str]:
        """`media_problem` for every referenced media file (reads every file once)."""
        problems = []
        for name, ref in sorted(self.referenced_media().items()):
            problem = self.media_problem(name, ref.bytes)
            if problem:
                problems.append(problem)
        return problems


def load_catalog(directory: Path) -> LoadedCatalog:
    """Read ``directory/manifest.json`` and every file it points to, validating each.

    Raises `FormatError` for a missing or unparseable file, a schema violation, a hashed
    file whose name doesn't match its content, or a region file that disagrees with its
    manifest row (slug, species count). Media is not read: use
    `LoadedCatalog.media_problems`. This is how the pipeline loads the previous release
    as state (ADR 0014) and how the validation gate checks a build.
    """
    manifest_obj = _read_json(directory / MANIFEST_NAME)
    validate_manifest(manifest_obj)
    manifest = Manifest.from_dict(manifest_obj)

    species_obj = _read_json(directory / manifest.species_file)
    validate_species(species_obj)
    _check_hashed(manifest.species_file, species_obj)

    provenance: ProvenanceFile | None = None
    if manifest.provenance_file is not None:
        prov_obj = _read_json(directory / manifest.provenance_file)
        validate_provenance(prov_obj)
        _check_hashed(manifest.provenance_file, prov_obj)
        provenance = ProvenanceFile.from_dict(prov_obj)

    regions: dict[str, RegionFile] = {}
    for ref in manifest.regions:
        region_obj = _read_json(directory / ref.file)
        validate_region(region_obj)
        _check_hashed(ref.file, region_obj)
        region = RegionFile.from_dict(region_obj)
        if region.slug != ref.slug:
            raise FormatError(f"{ref.file}: slug {region.slug!r} but manifest says {ref.slug!r}")
        if len(region.species) != ref.species_count:
            raise FormatError(
                f"{ref.file}: {len(region.species)} species but manifest says {ref.species_count}"
            )
        if ref.slug in regions:
            raise FormatError(f"manifest lists region {ref.slug!r} twice")
        regions[ref.slug] = region

    return LoadedCatalog(
        root=directory,
        manifest=manifest,
        regions=regions,
        species=SpeciesFile.from_dict(species_obj),
        provenance=provenance,
    )
