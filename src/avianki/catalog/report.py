"""Human-readable outputs of a catalog build: build-report.md, contact-sheet.html, credits.html.

* `BuildReport` is the plain record the pipeline (``catalog.build``) fills while it runs;
  `render_build_report` turns it, plus the validation gate's result, into ``build-report.md``
  (the job summary, ADR 0014).
* `render_contact_sheet` is the page the build lead (or an agent, ADR 0019) eyeballs to
  check every photo is the right bird.
* `render_credits_page` is ``credits.html``, linked from the web app footer (ADR 0012).

Everything is deterministic (sorted, no clocks) and every untrusted string is escaped with
`html.escape`. The only markup taken from stored data is the credit line, which the
pipeline rendered and the gate validated; it is re-checked with `credit_is_safe` here and
escaped as text if it fails.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from avianki.catalog.credit import credit_is_safe, is_http_url, licence_label
from avianki.catalog.format import LoadedCatalog, MediaRef, ProvenanceEntry
from avianki.catalog.species_lists import group_re_resolved
from avianki.catalog.validate import Problem, ValidationResult
from avianki.core.licences import is_allowed, licence_url

# ---------------------------------------------------------------------------------------
# BuildReport
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rejection:
    """A candidate asset the pipeline turned down, and why (licence, BirdNET, ...)."""

    species_id: str
    kind: str  # "photo" | "audio"
    source: str  # source name, e.g. "commons", "inaturalist"
    token: str  # the source-native pin token of the rejected candidate
    reason: str  # short and stable, e.g. "birdnet: best 0.31 < 0.5", "licence: CC-BY-NC-4.0"


@dataclass(frozen=True)
class SourceFailure:
    """A source call that *failed* (timeout, 429/5xx after retries, malformed response...).

    A failure is never "no media" (ADR 0007): the species keeps its previous entry and is
    listed here. ``species_id`` is None for a failure not tied to one species (e.g. the
    species-list source, or a budget exhausted for the whole run).
    """

    source: str
    species_id: str | None
    error: str


@dataclass(frozen=True)
class PlausibilityFlag:
    """A source result flagged as a likely taxonomy mismatch (ADR 0008 plausibility check)."""

    species_id: str
    source: str
    detail: str  # e.g. "24 North American records vs 27517 expected (0.1%)"


@dataclass
class BuildReport:
    """What a catalog build did. The pipeline fills it; `render_build_report` prints it.

    Lists of species ids are in any order (rendering sorts them). Counters are plain ints.
    """

    catalog_version: str = ""
    # Failures first: these must never be mistaken for absence.
    source_failures: list[SourceFailure] = field(default_factory=list)
    # Species the run did not get to (request budget or job cap, ADR 0014): absent this month.
    unfinished_species: list[str] = field(default_factory=list)
    budget_exhausted: bool = False
    # Pins (src/avianki/data/pins.toml) that could not be honoured: unresolvable, unlicensed, unprocessable,
    # or naming a different species. A hard error for the build (ADR 0011), exit code 1.
    pin_errors: list[str] = field(default_factory=list)
    # Candidates turned down: licence, generic rejects, BirdNET (kind="audio").
    rejections: list[Rejection] = field(default_factory=list)
    # Species with no chosen photo / audio after selection (acceptable absence).
    species_without_photo: list[str] = field(default_factory=list)
    species_without_audio: list[str] = field(default_factory=list)
    plausibility_flags: list[PlausibilityFlag] = field(default_factory=list)
    # species id -> which of "birdnet_label", "inat_taxon_id", "wikipedia_title" it lacks.
    unmapped_species: dict[str, list[str]] = field(default_factory=dict)
    # species id -> {"inat_taxon_id"|"wikipedia_title"|"birdnet_label": value} found this
    # run; the diff a maintainer commits to src/avianki/data/species.csv.
    new_ids_discovered: dict[str, dict[str, str]] = field(default_factory=dict)
    # GBIF backbone keys named by eBird's own names, not the IOC entry for the key (ADR 0024), and the
    # regional records dropped from split keys over 10%. The source's `ReResolved`/`DroppedMinority` items.
    re_resolved: list[Any] = field(default_factory=list)
    dropped_minorities: list[Any] = field(default_factory=list)
    # Species that reuse their previous release entry vs species built fresh this run.
    reused: int = 0
    built: int = 0
    # Assets taken from src/avianki/data/pins.toml, and previous sticky assets dropped as invalid.
    pinned_used: int = 0
    sticky_invalidated: int = 0
    # Totals in the assembled catalog.
    species_total: int = 0
    photos: int = 0
    audio: int = 0
    photos_by_source: dict[str, int] = field(default_factory=dict)
    audio_by_source: dict[str, int] = field(default_factory=dict)
    requests_made: int = 0
    elapsed_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        return _report_markdown(self)


# ---------------------------------------------------------------------------------------
# build-report.md
# ---------------------------------------------------------------------------------------

MAX_LISTED = 200  # long lists are cut, with a count, to stay under job-summary limits


def _md(text: object) -> str:
    """Untrusted text for Markdown: HTML-escaped (job summaries render HTML) on one line."""
    return html.escape(" ".join(str(text).split()), quote=False)


def _bullets(lines: list[str], limit: int = MAX_LISTED) -> list[str]:
    out = [f"- {line}" for line in lines[:limit]]
    if len(lines) > limit:
        out.append(f"- ... and {len(lines) - limit} more")
    return out


def _ids(ids: list[str]) -> str:
    return ", ".join(_md(i) for i in sorted(set(ids)))


def _section(title: str, body: list[str]) -> list[str]:
    return [f"## {title}", "", *(body or ["none"]), ""]


def _counts(counter: dict[str, int]) -> str:
    return ", ".join(f"{_md(k)} {v}" for k, v in sorted(counter.items())) or "none"


def _problem_line(p: Problem) -> str:
    where = f" {_md(p.subject)}" if p.subject else ""
    return f"**{_md(p.code)}**{where}: {_md(p.message)}"


def _report_markdown(r: BuildReport, validation: ValidationResult | None = None) -> str:
    title = f"# Build report {_md(r.catalog_version)}".rstrip()
    lines = [title, "", *_problem_lines(r, validation), *_summary_lines(r), *_species_lines(r)]
    return "\n".join(lines).rstrip() + "\n"


def _problem_lines(r: BuildReport, validation: ValidationResult | None) -> list[str]:
    """The gate's verdict, then what went wrong: pins, source calls, a short run, the gate's problems."""
    lines: list[str] = []
    if validation is not None:
        verdict = "PASSED" if validation.ok else "FAILED: nothing is published"
        lines += [
            f"**Validation gate: {verdict}** "
            f"({len(validation.errors)} error(s), {len(validation.warnings)} warning(s))",
            "",
        ]

    if r.pin_errors:
        lines += [
            "## PIN ERRORS",
            "",
            f"**{len(r.pin_errors)} pin(s) could not be honoured.** The species keep their previous "
            "entry (or have none yet); fix src/avianki/data/pins.toml or the pinned asset and rerun.",
            "",
            *_bullets([_md(e) for e in r.pin_errors]),
            "",
        ]

    # Failures first and prominent: a failed source call is not "no media".
    if r.source_failures:
        lines += [
            "## SOURCE FAILURES",
            "",
            f"**{len(r.source_failures)} source call(s) FAILED.** These are not absences: the "
            "affected species keep their previous entry (or have none yet) and need a rerun.",
            "",
        ]
        failure_lines = [
            f"**{_md(f.source)}** {_md(f.species_id) if f.species_id else '(whole run)'}: {_md(f.error)}"
            for f in sorted(r.source_failures, key=lambda f: (f.source, f.species_id or "", f.error))
        ]
        lines += [*_bullets(failure_lines), ""]
    else:
        lines += _section("Source failures", [])

    if r.budget_exhausted or r.unfinished_species:
        body = []
        if r.budget_exhausted:
            body.append("The request budget or job cap ran out; the run published what it had.")
        body.append(f"Unfinished species ({len(set(r.unfinished_species))}): {_ids(r.unfinished_species) or 'none'}")
        lines += _section("Run stopped short", body)

    if validation is not None:
        lines += _section("Validation errors", _bullets([_problem_line(p) for p in validation.errors]))
        lines += _section("Validation warnings", _bullets([_problem_line(p) for p in validation.warnings]))
    return lines


def _summary_lines(r: BuildReport) -> list[str]:
    """The counts, then the rejected candidates: grouped by reason, then one by one."""
    lines = _section(
        "Summary",
        [
            f"- Species: {r.species_total} ({r.built} built this run, {r.reused} reused)",
            f"- Photos: {r.photos} ({_counts(r.photos_by_source)})",
            f"- Audio: {r.audio} ({_counts(r.audio_by_source)})",
            f"- Pinned assets used: {r.pinned_used}; sticky assets invalidated: {r.sticky_invalidated}",
            f"- Requests made: {r.requests_made}; elapsed: {r.elapsed_s:.1f} s",
        ],
    )

    reasons = Counter((x.kind, x.source, x.reason) for x in r.rejections)
    lines += _section(
        f"Rejections ({len(r.rejections)})",
        _bullets(
            [f"{n} x {_md(k)} / {_md(s)}: {_md(why)}" for (k, s, why), n in sorted(reasons.items())]
        ),
    )
    detail = sorted(r.rejections, key=lambda x: (x.species_id, x.kind, x.source, x.token, x.reason))
    if detail:
        lines += [
            "### Each rejection",
            "",
            *_bullets(
                [
                    f"{_md(x.species_id)} {_md(x.kind)} {_md(x.source)} {_md(x.token)}: {_md(x.reason)}"
                    for x in detail
                ]
            ),
            "",
        ]
    return lines


def _species_lines(r: BuildReport) -> list[str]:
    """Species-level lists: missing media, plausibility flags, GBIF key changes, new ids, notes."""
    lines = _section(
        f"Species without a photo ({len(set(r.species_without_photo))})",
        [_ids(r.species_without_photo)] if r.species_without_photo else [],
    )
    lines += _section(
        f"Species without audio ({len(set(r.species_without_audio))})",
        [_ids(r.species_without_audio)] if r.species_without_audio else [],
    )
    lines += _section(
        f"Plausibility flags ({len(r.plausibility_flags)})",
        _bullets(
            [
                f"{_md(f.species_id)} ({_md(f.source)}): {_md(f.detail)}"
                for f in sorted(r.plausibility_flags, key=lambda f: (f.species_id, f.source, f.detail))
            ]
        ),
    )
    groups = group_re_resolved(r.re_resolved)
    lines += _section(
        f"Re-resolved GBIF keys ({len(groups)}); eBird's own name, not the IOC entry for the key (ADR 0024)",
        _bullets(
            [
                f"key {_md(g.source_key)}: {_md(g.old_common_name)} ({_md(g.old_sci_name)}) -> "
                f"{_md(g.common_name)} ({_md(g.sci_name)}); {g.share} of its records; "
                f"{len(g.regions)} region(s): {_md(', '.join(g.regions[:8]))}"
                f"{f' and {len(g.regions) - 8} more' if len(g.regions) > 8 else ''}"
                for g in groups
            ]
        ),
    )
    lines += _section(
        f"Split GBIF keys that dropped over 10% of a region's records ({len(r.dropped_minorities)})",
        _bullets(
            [
                f"key {_md(d.source_key)} in {_md(d.region)}: kept {_md(d.common_name)} ({_md(d.sci_name)}), "
                f"{round(100 * d.kept_share)}% of the key's records; dropped {_md(', '.join(d.dropped))}"
                for d in sorted(r.dropped_minorities, key=lambda d: (int(d.source_key), d.region))
            ]
        ),
    )
    lines += _section(
        f"Unmapped species ({len(r.unmapped_species)})",
        _bullets([f"{_md(sid)}: no {_md(', '.join(sorted(m)))}" for sid, m in sorted(r.unmapped_species.items())]),
    )
    lines += _section(
        f"New ids discovered ({len(r.new_ids_discovered)}); commit to src/avianki/data/species.csv",
        _bullets(
            [
                f"{_md(sid)}: " + ", ".join(f"{_md(k)}={_md(v)}" for k, v in sorted(ids.items()))
                for sid, ids in sorted(r.new_ids_discovered.items())
            ]
        ),
    )
    if r.notes:
        lines += _section("Notes", _bullets([_md(n) for n in r.notes]))
    return lines


def render_build_report(report: BuildReport, validation: ValidationResult | None) -> str:
    """``build-report.md``: failures first, then the gate's verdict, counts and the lists.

    Empty sections say ``none``. ``validation`` is None when the gate has not run.
    """
    return _report_markdown(report, validation)


# ---------------------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------------------

_BASE_CSS = """
:root{color-scheme:light dark;--fg:#1c1c1c;--bg:#fff;--muted:#5c5c5c;--line:#d8d8d8;--warn:#b00020}
@media(prefers-color-scheme:dark){:root{--fg:#ececec;--bg:#161616;--muted:#a0a0a0;--line:#3a3a3a;--warn:#ff6b81}}
*{box-sizing:border-box}
body{margin:0 auto;padding:16px;max-width:60rem;font:16px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg)}
a{color:inherit}
h1{font-size:1.5rem}h2{font-size:1.15rem;margin:1.6em 0 .4em}
.muted{color:var(--muted)}small{color:var(--muted)}
code{font:.85em ui-monospace,monospace;overflow-wrap:anywhere}
"""


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _page(title: str, extra_css: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n<style>{_BASE_CSS}{extra_css}</style>\n</head>\n"
        f"<body>\n{body}</body>\n</html>\n"
    )


def _sorted_species(catalog: LoadedCatalog) -> list[tuple[str, str]]:
    """``(species_id, name)`` sorted by common name, then id, for stable output."""
    return sorted(((sid, e.name) for sid, e in catalog.species.items()), key=lambda t: (t[1].casefold(), t[1], t[0]))


# ---------------------------------------------------------------------------------------
# credits.html
# ---------------------------------------------------------------------------------------

_CREDITS_CSS = """
.sp{border-top:1px solid var(--line);padding:.6em 0}
.sp h3{font-size:1rem;margin:0}
.sp ul{margin:.3em 0 0;padding-left:1.2em}
.sp li{margin:.2em 0;overflow-wrap:anywhere}
"""

LICENCE_NOTICE = (
    "This deck is a compilation. AviAnki's templates and selection are MIT-licensed. "
    "Each photo and recording keeps its own licence, credited on its card, and no further "
    "terms are imposed on it."
)


def _dataset_credit_html(text: str, licence_id: str, url: str, modifications: str) -> str:
    if is_allowed(licence_id):
        licence = f'<a href="{_e(licence_url(licence_id))}">{_e(licence_label(licence_id))}</a>'
    else:
        licence = _e(licence_id)
    link = f'<a href="{_e(url)}">{_e(url)}</a>' if is_http_url(url) else _e(url)
    parts = [_e(text), licence, link]
    if modifications.strip():
        parts.append(f"modified: {_e(modifications.strip())}")
    return " &middot; ".join(parts)


def _credit_line_html(m: MediaRef) -> str:
    # The stored credit was rendered by credit.py and checked by the gate; if it somehow
    # isn't safe, show it as inert text rather than as markup.
    return m.credit if credit_is_safe(m.credit) else _e(m.credit)


def render_credits_page(catalog: LoadedCatalog) -> str:
    """``credits.html``: dataset credits, then every species' photo and audio credit lines.

    A standalone page with no scripts and no external assets, readable on a phone.
    """
    body = ["<h1>Credits</h1>\n", '<p class="muted">Every photo and recording in the AviAnki catalog, with its creator and licence.</p>\n']
    body.append("<h2>Data</h2>\n<ul>\n")
    for c in catalog.manifest.dataset_credits:
        body.append(f"<li>{_dataset_credit_html(c.text, c.licence_id, c.url, c.modifications)}</li>\n")
    body.append("</ul>\n")
    body.append(f"<h2>Licence notice</h2>\n<p>{_e(LICENCE_NOTICE)}</p>\n")

    rows = []
    for sid, name in _sorted_species(catalog):
        entry = catalog.species[sid]
        media = [*entry.photo, *entry.audio]
        if not media:
            continue
        items = "".join(f"<li>{_credit_line_html(m)}</li>" for m in media)
        rows.append(
            f'<div class="sp" id="sp-{_e(sid)}"><h3>{_e(name)} <small><i>{_e(entry.sci)}</i></small></h3>'
            f"<ul>{items}</ul></div>\n"
        )
    body.append(f"<h2>Photos and recordings ({len(rows)} species)</h2>\n")
    body.extend(rows)
    return _page("AviAnki credits", _CREDITS_CSS, "".join(body))


# ---------------------------------------------------------------------------------------
# contact-sheet.html
# ---------------------------------------------------------------------------------------

_SHEET_CSS = """
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(15rem,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:8px;padding:8px;overflow-wrap:anywhere}
.card img{width:100%;height:auto;display:block;border-radius:4px;background:var(--line)}
.card h3{font-size:1rem;margin:.4em 0 0}
.card audio{width:100%;margin:.3em 0}
.asset{margin:.4em 0;font-size:.85rem}
.nophoto{border:2px solid var(--warn)}
.alert{color:var(--warn);font-weight:700}
pre{margin:.2em 0;white-space:pre-wrap;font-size:.8rem}
"""


def _toml_pin(species_id: str, kind: str, source: str, token: str) -> str:
    """The lines to paste into src/avianki/data/pins.toml to force this asset (a note is required)."""
    ref = json.dumps(f"{source}:{token}", ensure_ascii=False)
    return f'[{species_id}]\n{kind} = {ref}\nnote = "why this {kind} is forced"'


def _asset_html(catalog: LoadedCatalog, sid: str, kind: str, ref: MediaRef, prefix: str) -> str:
    prov: ProvenanceEntry | None = catalog.provenance.entries.get(ref.file) if catalog.provenance else None
    src = _e(prefix + ref.file)
    if kind == "photo":
        media = f'<img loading="lazy" src="{src}" alt="{_e(catalog.species[sid].name)}">'
    else:
        media = f'<audio controls preload="none" src="{src}"></audio>'
    if prov is None:
        return f'<div class="asset">{media}<div class="alert">no provenance record</div></div>'
    facts = [f"{_e(kind)} from {_e(prov.record.source)}", _e(prov.record.licence_id)]
    facts.append(f"verified: {_e(prov.verified) if prov.verified else '<b>no</b>'}")
    if prov.birdnet_confidence is not None:
        facts.append(f"BirdNET {prov.birdnet_confidence:.2f}")
    return (
        f'<div class="asset">{media}<div>{" &middot; ".join(facts)}</div>'
        f"<pre>{_e(_toml_pin(sid, kind, prov.record.source, prov.token))}</pre></div>"
    )


def _card_html(catalog: LoadedCatalog, sid: str, prefix: str, *, no_photo: bool = False) -> str:
    entry = catalog.species[sid]
    cls = "card nophoto" if no_photo else "card"
    parts = [
        f'<div class="{cls}" id="sp-{_e(sid)}">',
        '<div class="alert">no photo</div>' if no_photo else "",
        f"<h3>{_e(entry.name)}</h3><small><i>{_e(entry.sci)}</i> &middot; <code>{_e(sid)}</code></small>",
    ]
    parts += [_asset_html(catalog, sid, "photo", m, prefix) for m in entry.photo]
    parts += [_asset_html(catalog, sid, "audio", m, prefix) for m in entry.audio]
    if not entry.audio:
        parts.append('<div class="muted">no audio</div>')
    parts.append("</div>")
    return "".join(parts)


def render_contact_sheet(catalog: LoadedCatalog, media_prefix: str = "") -> str:
    """``contact-sheet.html``: one card per species for eyeballing every photo.

    Species with no photo come first and prominently, then a list of species with no
    audio, then the grid. ``media_prefix`` is prepended to each ``media/...`` path (e.g.
    ``"catalog/"`` when the sheet is served beside the catalog directory).
    """
    ordered = _sorted_species(catalog)
    no_photo = [sid for sid, _ in ordered if not catalog.species[sid].photo]
    no_audio = [sid for sid, _ in ordered if not catalog.species[sid].audio]
    with_photo = [sid for sid, _ in ordered if catalog.species[sid].photo]

    body = [
        f"<h1>Contact sheet {_e(catalog.manifest.catalog_version)}</h1>\n",
        f'<p class="muted">{len(ordered)} species: {len(no_photo)} without a photo, '
        f"{len(no_audio)} without audio. Paste a card's <code>pins.toml</code> lines to force that asset.</p>\n",
    ]
    body.append(f'<h2 class="alert">No photo ({len(no_photo)})</h2>\n')
    if no_photo:
        body.append('<div class="grid">' + "".join(_card_html(catalog, s, media_prefix, no_photo=True) for s in no_photo) + "</div>\n")
    else:
        body.append("<p>none</p>\n")
    body.append(f"<h2>No audio ({len(no_audio)})</h2>\n")
    if no_audio:
        links = ", ".join(f'<a href="#sp-{_e(s)}">{_e(catalog.species[s].name)}</a>' for s in no_audio)
        body.append(f"<p>{links}</p>\n")
    else:
        body.append("<p>none</p>\n")
    body.append(f"<h2>All species with a photo ({len(with_photo)})</h2>\n")
    body.append('<div class="grid">' + "".join(_card_html(catalog, s, media_prefix) for s in with_photo) + "</div>\n")
    return _page("AviAnki contact sheet", _SHEET_CSS, "".join(body))
