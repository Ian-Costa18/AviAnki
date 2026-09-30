"""The catalog client: manifest, region lookup, species and media (cached, digest-checked).

No test here touches the network except the one marked ``integration``. Local-path tests read
the fixture catalog directly; HTTP tests serve it from a `http.server` thread on 127.0.0.1.
"""

from __future__ import annotations

import http.server
import inspect
import json
import shutil
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests

from avianki.catalog.client import (
    AmbiguousRegion,
    CatalogClient,
    CatalogError,
    RegionNotFound,
    default_cache_dir,
)
from avianki.catalog.format import DEFAULT_BASE_URL, FORMAT_VERSION, media_filename

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "catalog"


def some_media(client: CatalogClient, kind: str = "photo") -> str:
    """The first photo (or audio) file of the first species that has one."""
    for _, entry in client.species().items():
        refs = entry.photo if kind == "photo" else entry.audio
        if refs:
            return refs[0].file
    raise AssertionError("fixture has no such media")


@pytest.fixture()
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture()
def local(cache: Path) -> CatalogClient:
    return CatalogClient(FIXTURE, cache_dir=cache)


@pytest.fixture()
def catalog_copy(tmp_path: Path) -> Path:
    """A writable copy of the fixture catalog, for tests that damage it."""
    dest = tmp_path / "catalog"
    shutil.copytree(FIXTURE, dest, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    return dest


def edit_manifest(root: Path, **changes: object) -> None:
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(changes)
    path.write_text(json.dumps(manifest), encoding="utf-8")


# ---------------------------------------------------------------------------------------
# A local HTTP server that counts requests and can be told to misbehave
# ---------------------------------------------------------------------------------------


@dataclass
class Served:
    url: str
    hits: Counter[str] = field(default_factory=Counter)
    user_agents: list[str] = field(default_factory=list)
    # path -> list of (status, body) used for the next requests to that path, in order;
    # once exhausted the real file is served.
    script: dict[str, list[tuple[int, bytes]]] = field(default_factory=dict)


@pytest.fixture()
def served(tmp_path: Path) -> Iterator[Served]:
    root = tmp_path / "served"
    shutil.copytree(FIXTURE, root / "catalog", ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    state = Served(url="")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(root), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # silence
            pass

        def do_GET(self) -> None:
            state.hits[self.path] += 1
            state.user_agents.append(self.headers.get("User-Agent", ""))
            queued = state.script.get(self.path)
            if queued:
                status, body = queued.pop(0)
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}/catalog/"
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def http_client(served: Served, cache: Path, **kw: object) -> CatalogClient:
    kw.setdefault("backoff", 0.0)
    return CatalogClient(served.url, cache_dir=cache, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------------------


def test_manifest_parses(local: CatalogClient) -> None:
    m = local.manifest()
    assert m.format == FORMAT_VERSION
    assert [r.slug for r in m.regions] == ["us-ma", "ca-qc", "us-az"]
    assert m.species_file.startswith("species.")
    assert m.dataset_credits


def test_file_url_base_works(cache: Path) -> None:
    client = CatalogClient(FIXTURE.as_uri(), cache_dir=cache)
    assert client.manifest().regions[0].slug == "us-ma"


def test_default_base_is_the_published_catalog() -> None:
    assert DEFAULT_BASE_URL.startswith("https://") and DEFAULT_BASE_URL.endswith("/catalog/")
    # The constructor default is the format module's constant, not a copy.
    assert inspect.signature(CatalogClient).parameters["base_url"].default is DEFAULT_BASE_URL


def test_manifest_is_fetched_fresh_each_time(served: Served, cache: Path) -> None:
    client = http_client(served, cache)
    client.manifest()
    client.manifest()
    assert served.hits["/catalog/manifest.json"] == 2


def test_newer_format_is_refused(catalog_copy: Path, cache: Path) -> None:
    edit_manifest(catalog_copy, format=FORMAT_VERSION + 1, regions="a shape this code can't parse")
    with pytest.raises(CatalogError, match=r"pip install -U avianki"):
        CatalogClient(catalog_copy, cache_dir=cache).manifest()


@pytest.mark.parametrize("bad", [0, "1", None])
def test_unrecognised_format_is_an_error(catalog_copy: Path, cache: Path, bad: object) -> None:
    edit_manifest(catalog_copy, format=bad)
    with pytest.raises(CatalogError, match="format"):
        CatalogClient(catalog_copy, cache_dir=cache).manifest()


def test_missing_manifest_is_a_catalog_error(tmp_path: Path, cache: Path) -> None:
    with pytest.raises(CatalogError, match="manifest.json"):
        CatalogClient(tmp_path / "nowhere", cache_dir=cache).manifest()


def test_manifest_that_is_not_json_is_a_catalog_error(tmp_path: Path, cache: Path) -> None:
    (tmp_path / "manifest.json").write_text("<html>not json</html>", encoding="utf-8")
    with pytest.raises(CatalogError, match="JSON"):
        CatalogClient(tmp_path, cache_dir=cache).manifest()


def test_manifest_missing_a_key_is_a_catalog_error(catalog_copy: Path, cache: Path) -> None:
    path = catalog_copy / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["species_file"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CatalogError, match="species_file"):
        CatalogClient(catalog_copy, cache_dir=cache).manifest()


# ---------------------------------------------------------------------------------------
# find_region
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("us-ma", "us-ma"),
        ("US-MA", "us-ma"),
        ("  us-az ", "us-az"),
        ("Massachusetts", "us-ma"),
        ("massachusetts", "us-ma"),
        ("ca-qc", "ca-qc"),
        ("Québec", "ca-qc"),
        ("quebec", "ca-qc"),
        ("QUÉBEC", "ca-qc"),
        ("Québec", "ca-qc"),  # decomposed accent
    ],
)
def test_find_region(local: CatalogClient, query: str, slug: str) -> None:
    assert local.find_region(query).slug == slug


def test_find_region_returns_the_manifest_row(local: CatalogClient) -> None:
    ref = local.find_region("Arizona")
    assert (ref.slug, ref.name, ref.country, ref.species_count) == ("us-az", "Arizona", "US", 6)
    assert ref in local.manifest().regions


def test_unknown_region_suggests_close_matches(local: CatalogClient) -> None:
    with pytest.raises(RegionNotFound) as exc:
        local.find_region("Massachusets")
    err = exc.value
    assert err.query == "Massachusets"
    assert [r.slug for r in err.suggestions] == ["us-ma"]
    assert "Massachusetts" in str(err) and "us-ma" in str(err)
    assert isinstance(err, CatalogError)


def test_unknown_region_suggests_by_substring(local: CatalogClient) -> None:
    with pytest.raises(RegionNotFound) as exc:
        local.find_region("mass")
    assert [r.slug for r in exc.value.suggestions] == ["us-ma"]


def test_unknown_region_without_a_match_has_no_suggestions(local: CatalogClient) -> None:
    with pytest.raises(RegionNotFound) as exc:
        local.find_region("Atlantis")
    assert exc.value.suggestions == []


def test_two_regions_with_the_same_name_are_ambiguous(catalog_copy: Path, cache: Path) -> None:
    path = catalog_copy / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["regions"][2]["name"] = "Massachusetts"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    client = CatalogClient(catalog_copy, cache_dir=cache)
    with pytest.raises(AmbiguousRegion, match=r"us-ma.*us-az|us-az.*us-ma"):
        client.find_region("massachusetts")
    assert client.find_region("us-az").slug == "us-az"  # slugs are still unique


# ---------------------------------------------------------------------------------------
# region() and species()
# ---------------------------------------------------------------------------------------


def test_region_and_species_parse(local: CatalogClient) -> None:
    region = local.region(local.find_region("us-ma"))
    assert region.slug == "us-ma"
    assert len(region.species) == 12
    assert all(len(monthly) == 12 for _, monthly in region.species)

    species = local.species()
    assert len(species) == 12
    assert {sid for sid, _ in region.species} == set(species)
    robin = species["turdus-migratorius"]
    assert robin.name == "American Robin" and len(robin.photo) == 2 and robin.audio


def test_region_and_species_are_fetched_once_per_client(served: Served, cache: Path) -> None:
    client = http_client(served, cache)
    ref = client.find_region("us-ma")
    assert client.region(ref) is client.region(ref)
    assert client.species() is client.species()
    assert served.hits[f"/catalog/{ref.file}"] == 1
    assert served.hits[f"/catalog/{client.manifest().species_file}"] == 1


def test_hashed_json_is_cached_on_disk_by_filename(served: Served, cache: Path) -> None:
    first = http_client(served, cache)
    ref = first.find_region("us-ma")
    first.region(ref)
    first.species()
    assert (cache / ref.file).is_file()
    served.hits.clear()

    second = http_client(served, cache)
    second.region(second.find_region("us-ma"))
    second.species()
    assert [p for p in served.hits if "regions/" in p or "species." in p] == []


def test_a_corrupt_cached_json_file_is_refetched(served: Served, cache: Path) -> None:
    first = http_client(served, cache)
    ref = first.find_region("us-ma")
    first.region(ref)
    (cache / ref.file).write_text('{"slug": "us-ma", "species": []}', encoding="utf-8")

    second = http_client(served, cache)
    assert len(second.region(ref).species) == 12


def test_a_region_file_that_does_not_match_its_hash_is_an_error(
    served: Served, cache: Path
) -> None:
    client = http_client(served, cache)
    ref = client.find_region("us-ma")
    served.script[f"/catalog/{ref.file}"] = [(200, b'{"slug":"us-ma","species":[]}')]
    with pytest.raises(CatalogError, match="hash"):
        client.region(ref)
    assert not (cache / ref.file).exists()


def test_a_region_file_for_the_wrong_slug_is_an_error(local: CatalogClient) -> None:
    us_ma = local.find_region("us-ma")
    us_az = local.find_region("us-az")
    wrong = type(us_ma)(us_az.slug, us_az.name, us_az.country, us_ma.file, us_az.species_count)
    with pytest.raises(CatalogError, match="slug"):
        local.region(wrong)


def test_species_file_that_is_not_a_species_map_is_an_error(catalog_copy: Path, cache: Path) -> None:
    edit_manifest(catalog_copy, species_file="species.00000000.json")
    (catalog_copy / "species.00000000.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(CatalogError):
        CatalogClient(catalog_copy, cache_dir=cache).species()


@pytest.mark.parametrize(
    "evil",
    ["../manifest.json", "regions/../../x.json", "/etc/passwd", "regions/us-ma.json", ""],
)
def test_file_names_from_the_manifest_are_checked_before_use(
    catalog_copy: Path, cache: Path, evil: str
) -> None:
    edit_manifest(catalog_copy, species_file=evil)
    with pytest.raises(CatalogError, match="not a catalog file name"):
        CatalogClient(catalog_copy, cache_dir=cache).species()


# ---------------------------------------------------------------------------------------
# media
# ---------------------------------------------------------------------------------------


def test_media_from_a_local_path_is_copied_into_the_cache(local: CatalogClient, cache: Path) -> None:
    file = some_media(local)
    path = local.media(file)
    assert path == cache / file
    assert path.read_bytes() == (FIXTURE / file).read_bytes()


def test_media_is_downloaded_once_then_cached(served: Served, cache: Path) -> None:
    client = http_client(served, cache)
    file = some_media(client)
    path = client.media(file)
    assert client.media(file) == path
    assert path.is_file() and path.suffix == ".webp"
    assert media_filename(path.read_bytes(), "webp") == file
    assert served.hits[f"/catalog/{file}"] == 1

    # A fresh client (a later run) reuses the on-disk cache.
    http_client(served, cache).media(file)
    assert served.hits[f"/catalog/{file}"] == 1


def test_media_digest_mismatch_raises_and_leaves_no_file(served: Served, cache: Path) -> None:
    client = http_client(served, cache)
    file = some_media(client, "audio")
    served.script[f"/catalog/{file}"] = [(200, b"these are not the bytes you asked for")]
    with pytest.raises(CatalogError, match="digest"):
        client.media(file)
    assert not (cache / file).exists()
    assert list((cache / "media").glob("*")) == []  # no temp file left behind

    # The next attempt (now served correctly) succeeds.
    assert client.media(file).is_file()


def test_truncated_local_media_is_a_digest_mismatch(catalog_copy: Path, cache: Path) -> None:
    client = CatalogClient(catalog_copy, cache_dir=cache)
    file = some_media(client)
    (catalog_copy / file).write_bytes((catalog_copy / file).read_bytes()[:-3])
    with pytest.raises(CatalogError, match="digest"):
        client.media(file)
    assert not (cache / file).exists()


def test_missing_local_media_is_a_catalog_error(catalog_copy: Path, cache: Path) -> None:
    client = CatalogClient(catalog_copy, cache_dir=cache)
    file = some_media(client)
    (catalog_copy / file).unlink()
    with pytest.raises(CatalogError, match=file.split("/")[-1]):
        client.media(file)


@pytest.mark.parametrize(
    "evil",
    ["media/../manifest.json", "manifest.json", "media/abc.webp", "media/0123456789abcdef.exe", "/x"],
)
def test_media_names_are_checked_before_use(local: CatalogClient, evil: str) -> None:
    with pytest.raises(CatalogError, match="not a catalog media file name"):
        local.media(evil)


def test_media_many_reports_progress_and_returns_paths(served: Served, cache: Path) -> None:
    client = http_client(served, cache)
    files = [some_media(client), some_media(client, "audio")]
    calls: list[tuple[int, int]] = []
    result = client.media_many([*files, files[0]], progress=lambda done, total: calls.append((done, total)))
    assert list(result) == files  # de-duplicated, in order
    assert all(p.is_file() for p in result.values())
    assert calls == [(0, 2), (1, 2), (2, 2)]
    assert served.hits[f"/catalog/{files[0]}"] == 1


def test_media_many_without_progress(local: CatalogClient) -> None:
    assert local.media_many([]) == {}
    assert len(local.media_many([some_media(local)])) == 1


# ---------------------------------------------------------------------------------------
# HTTP behaviour
# ---------------------------------------------------------------------------------------


def test_404_is_a_catalog_error_naming_the_url(served: Served, cache: Path) -> None:
    client = http_client(served, cache)
    file = some_media(client)
    served.script[f"/catalog/{file}"] = [(404, b"nope")]
    with pytest.raises(CatalogError, match=r"404") as exc:
        client.media(file)
    assert file in str(exc.value) and served.url in str(exc.value)
    assert served.hits[f"/catalog/{file}"] == 1  # a 404 is not retried


def test_persistent_500_is_retried_then_a_catalog_error(served: Served, cache: Path) -> None:
    client = http_client(served, cache, retries=2)
    served.script["/catalog/manifest.json"] = [(500, b"")] * 5
    with pytest.raises(CatalogError, match=r"500") as exc:
        client.manifest()
    assert "manifest.json" in str(exc.value)
    assert served.hits["/catalog/manifest.json"] == 3  # 1 try + 2 retries


def test_a_transient_500_is_retried(served: Served, cache: Path) -> None:
    client = http_client(served, cache, retries=2)
    served.script["/catalog/manifest.json"] = [(503, b""), (500, b"")]
    assert client.manifest().regions
    assert served.hits["/catalog/manifest.json"] == 3


def test_a_connection_failure_is_a_catalog_error_naming_the_url(cache: Path) -> None:
    # Nothing listens on a port we just released.
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}/catalog/"
    client = CatalogClient(url, cache_dir=cache, retries=0, timeout=5)
    with pytest.raises(CatalogError, match=f"127.0.0.1:{port}/catalog/manifest.json"):
        client.manifest()


def test_requests_carry_the_project_user_agent_and_no_email(served: Served, cache: Path) -> None:
    from avianki.core.http import default_user_agent

    client = http_client(served, cache, session=requests.Session())
    client.manifest()
    assert set(served.user_agents) == {default_user_agent()}
    assert "@" not in served.user_agents[0]


def test_paths_resolve_against_where_the_manifest_was_read_not_base_url(
    served: Served, cache: Path
) -> None:
    # The fixture's manifest.base_url is a placeholder (fixture.invalid); nothing may go there.
    client = http_client(served, cache)
    assert client.manifest().base_url == "https://fixture.invalid/catalog/"
    client.species()
    client.media(some_media(client))


def test_base_url_without_trailing_slash_works(served: Served, cache: Path) -> None:
    client = CatalogClient(served.url.rstrip("/"), cache_dir=cache, backoff=0.0)
    assert client.manifest().regions


# ---------------------------------------------------------------------------------------
# Cache directory
# ---------------------------------------------------------------------------------------


def test_default_cache_dir_per_platform(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert default_cache_dir(platform="win32", env={"LOCALAPPDATA": str(tmp_path / "lad")}, home=home) == (
        tmp_path / "lad" / "avianki" / "cache"
    )
    assert default_cache_dir(platform="win32", env={}, home=home) == (
        home / "AppData" / "Local" / "avianki" / "cache"
    )
    assert default_cache_dir(platform="darwin", env={}, home=home) == home / "Library" / "Caches" / "avianki"
    assert default_cache_dir(platform="linux", env={"XDG_CACHE_HOME": str(tmp_path / "xdg")}, home=home) == (
        tmp_path / "xdg" / "avianki"
    )
    assert default_cache_dir(platform="linux", env={}, home=home) == home / ".cache" / "avianki"
    # A relative XDG_CACHE_HOME must be ignored (XDG base dir spec).
    assert default_cache_dir(platform="linux", env={"XDG_CACHE_HOME": "rel"}, home=home) == (
        home / ".cache" / "avianki"
    )


def test_constructor_uses_the_default_cache_dir_when_none_given(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert CatalogClient(FIXTURE).cache_dir.is_relative_to(tmp_path)


# ---------------------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------------------


def test_importing_the_client_pulls_in_no_pipeline_dependencies() -> None:
    code = (
        "import sys\n"
        "import avianki.catalog.client\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in {'jsonschema', 'PIL', 'birdnet'}"
        " or m == 'avianki.sources' or m.startswith('avianki.sources.')"
        " or m == 'avianki.media' or m.startswith('avianki.media.')"
        " or m == 'avianki.catalog.build']\n"
        "print(sorted(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------------------


@pytest.mark.integration
def test_live_manifest_has_us_ma(tmp_path: Path) -> None:
    client = CatalogClient(cache_dir=tmp_path)
    manifest = client.manifest()
    assert manifest.format == FORMAT_VERSION
    ref = client.find_region("us-ma")
    assert ref.name == "Massachusetts"
    assert client.find_region("Massachusetts") == ref
