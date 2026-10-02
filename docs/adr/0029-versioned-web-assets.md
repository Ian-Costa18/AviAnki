# 0029 — The website's own files are versioned per deploy

**Status:** Accepted, 2026-10-01 · **Related:** [0003](0003-north-america-on-github-pages.md) (Pages), [0006](0006-browser-builds-the-apkg.md) (the browser build), [0013](0013-catalog-layout.md) (catalog file names), [0028](0028-card-themes.md) (`notetypes.json`) · **Closes:** #79

## Context

GitHub Pages serves every file with `cache-control: max-age=600`. For ten minutes after a deploy a returning visitor can get the new `index.html` next to old cached modules or an old `js/notetypes.json`. After the themes shipped ([0028](0028-card-themes.md)) this showed up as a theme picker with only "Default": the new page ran against a `notetypes.json` that predated themes. Any change to a module's exports, or to a JSON file the modules read, can break the same way.

The catalog doesn't have this problem. Its large files have content-addressed names ([0013](0013-catalog-layout.md)), and the manifest is the one entry point the client already checks.

## Decision

- **The app's own files move into a per-deploy directory.** `scripts/assemble_site.py` copies everything under `web/` except `index.html` (so `css/`, `js/`, `vendor/`) to `v/<version>/` at the same relative paths, and rewrites the local `<link href>` and `<script src>` URLs in `index.html` to point there. Only `index.html` stays at the root.
- **No other change is needed in the JavaScript.** Module imports are relative, and every fetch of an app file already resolves against `import.meta.url` (`notetypes.json` in `deck.js`, the sql.js script and wasm in `apkg/writer.js`). So once the entry module is at `v/<version>/js/app.js`, everything it loads is under the same directory. Page-relative URLs stay for the catalog (`catalog/manifest.json`, `catalog/credits.html`) and nothing else. A test enforces that.
- **The version is the commit SHA** (`--version "${{ github.sha }}"` in `pages.yml` and in `catalog.yml`'s deploy), shortened to 10 characters. Without `--version` the script uses a hash of the files in `web/`, so a local run still gets a name that changes whenever the app does. A new deploy always means a new directory, so a cached file can never be mixed with a newer page.
- **A stale `index.html` can name a directory that no longer exists.** Each deploy replaces the whole site, so the old `v/<old>/` is gone. `index.html` therefore carries a small inline script: if the stylesheet or the app module fails to load, it reloads once with a `?_cb=<time>` query, which is a different cache key and so fetches the current page. A `sessionStorage` flag allows one retry per tab session and is cleared when the app loads. If `sessionStorage` is unavailable there is no retry, because there is no way to guard against a loop. The query is removed from the address bar as soon as the page runs, so it is never bookmarked or shared. Every step is in a `try/catch`.
- **Local development is unchanged.** `web/index.html` in the repo uses plain `css/app.css` and `js/app.js`. Serving `web/` directly, and the browser tests' server, need no assemble step. The fallback is harmless there.
- **The catalog is not versioned by this.** It keeps its own scheme ([0013](0013-catalog-layout.md)).

## Consequences

- A page and its modules, note types and sql.js always come from the same deploy. Two deploys' files can sit in a visitor's HTTP cache without ever being used together.
- Pages keeps one copy of the app, because each deploy replaces the whole site, so the site doesn't grow. The scripts and the wasm have new URLs every deploy, so a returning visitor downloads them again after each one (about 150 KB gzipped plus the wasm). Deploys happen when `web/` changes, and monthly.
- **The first deploy of this change is the one exception.** A copy of the old `index.html` cached in a browser asks for `js/app.js`, which no longer exists, and the old page has no fallback. Those visitors see a broken page for at most ten minutes, until the browser refetches `index.html`. A hard refresh fixes it sooner.
- Anything new that a page loads must be a relative `<link>` or `<script>` in `index.html`, or resolve against `import.meta.url` in a module. `assemble_site.py` refuses a root-absolute URL or a file that isn't in `web/`, and `tests/scripts/test_assemble_site_versioning.py` checks every import, `new URL` and `fetch` in the assembled shell. A file that must sit at a fixed URL (a favicon at `/favicon.ico`, a service worker) would need the script to handle it explicitly.
- `tests/web/test_web_cache_busting.py` builds a deck in Chromium and WebKit from an assembled site, and checks that a stale page reloads once and recovers, and doesn't loop.
