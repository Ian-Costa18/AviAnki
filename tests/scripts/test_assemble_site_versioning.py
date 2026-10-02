"""Per-deploy versioning of the web app's files (ADR 0029, issue #79).

Pages caches every file for ten minutes, so a page must only ever load files from its own deploy.
These tests assemble the real ``web/`` into a temp dir and check, without a browser or a network,
that every local script, stylesheet, module import and fetch the shell makes resolves inside
``v/<version>/`` and exists there.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

import pytest
from test_assemble_site import assemble_site, make_catalog, make_web

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web"
VERSION = "0123456789"

STATIC_IMPORT = re.compile(r"""(?:\bimport|\bexport)\b[^;'"`]*?\bfrom\s*["']([^"']+)["']|\bimport\s*["']([^"']+)["']""")
DYNAMIC_IMPORT = re.compile(r"""\bimport\(\s*(["'][^"']*["']|[^)]*)\)""")
URL_CALL = re.compile(r"""new URL\(\s*["']([^"']+)["']\s*,\s*([^)]*)\)""")
FETCH_CALL = re.compile(r"\bfetch\(([^\n]*)")  # the rest of the line: the URL argument and what follows
LOCAL_FILE = re.compile(r"\.(?:js|mjs|json|wasm|css)$|/$")
TAG = re.compile(r"""<(?:link|script)\b[^>]*>""", re.IGNORECASE)
URL_ATTR = re.compile(r"""\b(?:href|src)=["']([^"']*)["']""", re.IGNORECASE)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("site")
    out = root / "_site"
    assemble_site.assemble(make_catalog(root), out, WEB, version=VERSION)
    return out


def local_urls(html: str) -> list[str]:
    """Every local URL in a <link> or <script> tag of the page."""
    urls = [u for tag in TAG.findall(html) for u in URL_ATTR.findall(tag)]
    return [u for u in urls if u and not re.match(r"[A-Za-z][A-Za-z0-9+.-]*:|//|#", u)]


def js_files(version_dir: Path) -> list[Path]:
    return sorted(p for p in version_dir.rglob("*.js") if "vendor" not in p.parts)


def inside(version_dir: Path, path: Path) -> bool:
    return path == version_dir or version_dir in path.parents


def resolved(file: Path, relative: str) -> Path:
    """Where a URL written as ``relative`` in ``file`` points, with ``..`` collapsed."""
    return Path(posixpath.normpath((file.parent / relative).as_posix()))


def test_the_shell_loads_only_versioned_files(site: Path) -> None:
    version_dir = site / "v" / VERSION
    urls = local_urls((site / "index.html").read_text(encoding="utf-8"))

    assert "v/%s/js/app.js" % VERSION in urls
    assert "v/%s/css/app.css" % VERSION in urls
    for url in urls:
        assert url.startswith(f"v/{VERSION}/"), url
        assert inside(version_dir, resolved(site / "index.html", url)), url
        assert (site / url).is_file(), url
    # nothing of the app is left at a fixed URL, apart from index.html itself
    assert sorted(p.name for p in site.iterdir() if p.name != "v") == [".nojekyll", "catalog", "index.html"]


def test_every_import_stays_inside_the_version(site: Path) -> None:
    version_dir = site / "v" / VERSION
    files = js_files(version_dir)
    assert len(files) > 10  # the real app, not an empty glob

    for file in files:
        source = file.read_text(encoding="utf-8")
        specifiers = [a or b for a, b in STATIC_IMPORT.findall(source)]
        specifiers += [s.strip("\"'") for s in DYNAMIC_IMPORT.findall(source)]
        for spec in specifiers:
            assert spec.startswith("."), f"{file.name} imports {spec!r}, which is not relative"
            target = resolved(file, spec)
            assert inside(version_dir, target), f"{file.name} imports {spec!r} outside the version"
            assert target.is_file(), f"{file.name} imports {spec!r}, which is not in the assembled site"


def test_every_other_file_url_resolves_against_the_module(site: Path) -> None:
    """``new URL("x.json", import.meta.url)`` stays inside the version; page-relative ones are only catalog's."""
    version_dir = site / "v" / VERSION
    checked = 0
    for file in js_files(version_dir):
        for literal, base in URL_CALL.findall(file.read_text(encoding="utf-8")):
            if not LOCAL_FILE.search(literal):
                continue  # credits.html and the like belong to the catalog
            assert base.strip() == "import.meta.url", f"{file.name}: new URL({literal!r}, {base}) is page-relative"
            target = resolved(file, literal)
            assert inside(version_dir, target), f"{file.name}: {literal!r} leaves the version"
            assert target.exists(), f"{file.name}: {literal!r} is not in the assembled site"
            checked += 1
    assert checked >= 2  # notetypes.json and the vendored sql.js directory


def test_every_fetch_resolves_inside_the_version_or_is_the_catalogs(site: Path) -> None:
    version_dir = site / "v" / VERSION
    for file in js_files(version_dir):
        for argument in FETCH_CALL.findall(file.read_text(encoding="utf-8")):
            if file.name == "catalog.js":
                continue  # catalog URLs come from the manifest and are not part of the app's versions
            assert "import.meta.url" in argument, f"{file.name} fetches {argument.strip()!r}, a page-relative URL"


def test_the_stylesheet_names_no_other_local_file(site: Path) -> None:
    css = (site / "v" / VERSION / "css" / "app.css").read_text(encoding="utf-8")
    assert "@import" not in css
    for url in re.findall(r"url\(\s*[\"']?([^)\"']+)", css):
        assert re.match(r"data:|https:|#", url), f"app.css loads {url!r}, which a versioned directory does not cover"


def test_the_vendored_files_the_writer_loads_exist(site: Path) -> None:
    vendor = site / "v" / VERSION / "vendor"
    for name in ("sql-wasm.js", "sql-wasm.wasm", "fflate.js"):
        assert (vendor / name).is_file(), name
    assert (site / "v" / VERSION / "js" / "notetypes.json").is_file()


def test_the_page_carries_the_reload_once_fallback(site: Path) -> None:
    html = (site / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<script type="module" src="v/\w+/js/app\.js" onload="[^"]+" onerror="aviankiLoadFailed\(\)">', html)
    fallback = html.split("</script>", 1)[0]
    assert "sessionStorage" in fallback and "location.replace" in fallback and "_cb" in fallback
    assert fallback.count("try {") >= 4  # every storage and URL operation is guarded


def test_the_source_page_is_not_versioned() -> None:
    """Serving ``web/`` directly (local development, the browser tests) needs no assemble step."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'href="css/app.css"' in html and 'src="js/app.js"' in html
    assert "/v/" not in html


def test_the_catalog_is_not_versioned(site: Path) -> None:
    assert (site / "catalog" / "manifest.json").is_file()
    assert not (site / "v" / VERSION / "catalog").exists()


def test_each_deploy_gets_its_own_directory(tmp_path: Path) -> None:
    catalog, web = make_catalog(tmp_path), make_web(tmp_path)
    for n, version in enumerate(("aaaaaaa", "bbbbbbb")):
        assemble_site.assemble(catalog, tmp_path / f"_site{n}", web, version=version)
    assert (tmp_path / "_site0" / "v" / "aaaaaaa" / "js" / "app.js").is_file()
    assert (tmp_path / "_site1" / "v" / "bbbbbbb" / "js" / "app.js").is_file()


def test_a_full_commit_sha_is_shortened(tmp_path: Path) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    assemble_site.assemble(make_catalog(tmp_path), tmp_path / "_site", make_web(tmp_path), version=sha)
    assert (tmp_path / "_site" / "v" / sha[:10] / "index.html").exists() is False
    assert (tmp_path / "_site" / "v" / sha[:10] / "js" / "app.js").is_file()


def test_without_a_version_the_content_hash_is_used(tmp_path: Path) -> None:
    web = make_web(tmp_path)
    first = assemble_site.content_version(web)
    assert first == assemble_site.content_version(web)  # stable
    (web / "js" / "app.js").write_text("// changed", encoding="utf-8")
    assert assemble_site.content_version(web) != first  # any change makes a new directory

    assemble_site.assemble(make_catalog(tmp_path), tmp_path / "_site", web)
    assert (tmp_path / "_site" / "v" / assemble_site.content_version(web) / "js" / "app.js").is_file()


@pytest.mark.parametrize("version", ["../x", "a/b", "a b", ".hidden", "x" * 65])
def test_an_unusable_version_is_refused(tmp_path: Path, version: str) -> None:
    with pytest.raises(assemble_site.AssembleError, match="version"):
        assemble_site.assemble(make_catalog(tmp_path), tmp_path / "_site", make_web(tmp_path), version=version)


def test_index_urls_are_rewritten_and_others_are_left_alone(tmp_path: Path) -> None:
    web = make_web(tmp_path)
    (web / "css").mkdir()
    (web / "css" / "app.css").write_text("body{}", encoding="utf-8")
    (web / "index.html").write_text(
        '<link rel="icon" href="data:image/svg+xml,%3Csvg/%3E">\n'
        '<link rel="stylesheet" href="./css/app.css?x=1" onerror="f()">\n'
        '<script type="module" src="js/app.js"></script>\n'
        '<script src="https://example.com/x.js"></script>\n'
        '<a href="catalog/credits.html">credits</a>',
        encoding="utf-8",
    )
    assemble_site.assemble(make_catalog(tmp_path), tmp_path / "_site", web, version="v1")

    html = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'href="v/v1/css/app.css"' in html  # query dropped: the file name is the version
    assert 'src="v/v1/js/app.js"' in html
    assert 'onerror="f()"' in html
    assert 'href="data:image/svg+xml,%3Csvg/%3E"' in html
    assert 'src="https://example.com/x.js"' in html
    assert '<a href="catalog/credits.html">' in html


@pytest.mark.parametrize(
    "tag, message",
    [
        ('<script type="module" src="js/missing.js"></script>', "not a file"),
        ('<script type="module" src="/js/app.js"></script>', "relative"),
    ],
)
def test_an_index_that_cannot_be_versioned_is_refused(tmp_path: Path, tag: str, message: str) -> None:
    web = make_web(tmp_path)
    (web / "index.html").write_text(tag, encoding="utf-8")
    with pytest.raises(assemble_site.AssembleError, match=message):
        assemble_site.assemble(make_catalog(tmp_path), tmp_path / "_site", web, version="v1")
    assert not (tmp_path / "_site").exists()


def test_a_web_dir_without_an_index_is_refused(tmp_path: Path) -> None:
    web = make_web(tmp_path)
    (web / "index.html").unlink()
    with pytest.raises(assemble_site.AssembleError, match="index.html"):
        assemble_site.assemble(make_catalog(tmp_path), tmp_path / "_site", web)
