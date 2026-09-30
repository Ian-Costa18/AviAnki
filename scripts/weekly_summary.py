#!/usr/bin/env python3
"""Summarise the weekly integration run and enforce ADR 0020's "no skips".

Reads the JUnit XML that ``pytest --integration -m integration --junitxml=...`` wrote and prints a
Markdown summary of the four checks (to ``$GITHUB_STEP_SUMMARY`` when set, else stdout). Exits 1 if

* the report is missing or unreadable (pytest never got as far as writing it),
* any test failed or errored,
* any test was skipped other than the eBird one, which may skip only because ``EBIRD_API_KEY``
  is not set (the one allowed skip, and the summary says so prominently), or
* a check ran no tests at all (a renamed or deselected test must not look like a pass).

Stdlib only, so the workflow can run it with any Python.

    python scripts/weekly_summary.py integration-junit.xml
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# A matcher is a test module's basename, or "module::test_name" to pick one test out of a module
# that also holds offline tests.
CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1. Source smoke tests (Commons, iNaturalist; Cardinal, Pelican, Whimbrel)", ("test_sources_live",)),
    ("2. GBIF EOD (us-ma lists at least 300 species)", ("test_gbif_live",)),
    (
        "3. The published site (manifest, media CORS, web app; live deck and live web build)",
        (
            "test_published_site_live",
            "test_catalog_client::test_live_manifest_has_us_ma",
            "test_acceptance_live",
            "test_web_live_catalog",
        ),
    ),
    ("4. eBird (CLI path)", ("test_ebird_live",)),
)
OTHER = "Other live tests (BirdNET model)"
EBIRD = "test_ebird_live"
EBIRD_KEY = "EBIRD_API_KEY"


@dataclass
class Case:
    module: str
    name: str
    outcome: str  # passed, failed, error or skipped
    seconds: float
    message: str = ""
    properties: dict[str, str] = field(default_factory=dict)

    def matches(self, matcher: str) -> bool:
        module, _, name = matcher.partition("::")
        return self.module == module and (not name or self.name.split("[")[0] == name)


@dataclass
class Group:
    title: str
    cases: list[Case] = field(default_factory=list)

    def count(self, outcome: str) -> int:
        return sum(1 for c in self.cases if c.outcome == outcome)

    @property
    def seconds(self) -> float:
        return sum(c.seconds for c in self.cases)


def parse(path: Path) -> list[Case]:
    cases = []
    for node in ET.parse(path).getroot().iter("testcase"):
        outcome, message = "passed", ""
        for child in node:
            if child.tag in ("failure", "error", "skipped"):
                outcome, message = ("failed" if child.tag == "failure" else child.tag), child.get("message", "")
                break
        properties = {p.get("name", ""): p.get("value", "") for p in node.iter("property")}
        cases.append(Case(
            module=node.get("classname", "").rsplit(".", 1)[-1],
            name=node.get("name", ""),
            outcome=outcome,
            seconds=float(node.get("time", 0) or 0),
            message=message,
            properties=properties,
        ))
    return cases


def group(cases: list[Case]) -> tuple[list[Group], Group]:
    """The four checks' cases, and everything else that ran."""
    groups = [Group(title) for title, _ in CHECKS]
    other = Group(OTHER)
    for case in cases:
        for g, (_, matchers) in zip(groups, CHECKS, strict=True):
            if any(case.matches(m) for m in matchers):
                g.cases.append(case)
                break
        else:
            other.cases.append(case)
    return groups, other


def is_allowed_skip(case: Case) -> bool:
    return case.module == EBIRD and EBIRD_KEY in case.message


def status(g: Group) -> str:
    if not g.cases:
        return "NOT RUN"
    if g.count("failed") or g.count("error"):
        return "FAILED"
    if g.count("skipped"):
        return "SKIPPED (allowed)" if all(is_allowed_skip(c) for c in g.cases if c.outcome == "skipped") else "SKIPPED"
    return "passed"


def render(groups: list[Group], other: Group, cases: list[Case]) -> tuple[str, bool]:
    """The Markdown summary, and whether the run is acceptable."""
    ok = True
    lines = ["## Weekly integration check", ""]
    lines += ["| Check | Outcome | Tests | Time |", "| --- | --- | --- | --- |"]
    for g in (*groups, other):
        if g is other and not g.cases:
            continue
        st = status(g)
        ok = ok and st in ("passed", "SKIPPED (allowed)")
        tests = f"{g.count('passed')} passed, {g.count('failed') + g.count('error')} failed, {g.count('skipped')} skipped"
        lines.append(f"| {g.title} | **{st}** | {tests} | {g.seconds / 60:.1f} min |")
    lines.append("")

    unexpected = [c for c in cases if c.outcome == "skipped" and not is_allowed_skip(c)]
    if unexpected:
        ok = False
        lines += ["> [!CAUTION]", "> **Skips are not allowed** (ADR 0020). The only allowed skip is the eBird test without a key:"]
        lines += [f"> - `{c.module}::{c.name}`: {c.message or 'no reason given'}" for c in unexpected]
        lines.append("")
    if any(is_allowed_skip(c) for c in cases):
        lines += [
            "> [!WARNING]",
            f"> **eBird smoke test SKIPPED:** the `{EBIRD_KEY}` secret is not set, so the eBird path was not tested this run.",
            "",
        ]
    failed = [c for c in cases if c.outcome in ("failed", "error")]
    if failed:
        lines += ["Failed tests:", *(f"- `{c.module}::{c.name}`" for c in failed), ""]

    versions = {c.properties["eod_version"]: c.properties.get("published_eod_version", "")
                for c in cases if "eod_version" in c.properties}
    for live, published in versions.items():
        lines.append("")
        lines.append(f"EOD dataset version now: `{live}`")
        if live == published:
            lines.append("It matches the published catalog's `manifest.json`.")
        else:
            lines.append(
                f"> [!NOTE]\n> **New EOD release.** The published catalog was built from `{published or 'unknown'}`. "
                "Not a failure: the next monthly catalog build picks it up."
            )
    lines += ["", "allaboutbirds.org is dormant (ADR 0002) and not monitored.", ""]
    return "\n".join(lines), ok


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    try:
        cases = parse(Path(argv[1]))
    except (OSError, ET.ParseError) as e:
        text, ok = f"## Weekly integration check\n\n> [!CAUTION]\n> **No test report** ({e}): pytest did not finish.\n", False
    else:
        groups, other = group(cases)
        text, ok = render(groups, other, cases)
    if target:
        with Path(target).open("a", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
