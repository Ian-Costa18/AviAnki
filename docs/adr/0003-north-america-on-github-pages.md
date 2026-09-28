# 0003 — North America only, hosted free on GitHub Pages

**Status:** Accepted, 2026-08-23 · **Tickets:** [#11](https://github.com/Ian-Costa18/AviAnki/issues/11), [#16](https://github.com/Ian-Costa18/AviAnki/issues/16) · **Evidence:** branch `research/free-hosting`

## Decision

- **Scope.** The v1 catalog covers the United States and Canada, one region per state, province and territory. Mexico and the rest of North America can come later without changing the format. Outside the catalog, the CLI's `--ebird` path is the answer ([0017](0017-cli-reads-the-catalog.md)).
- **Host.** GitHub Pages, deployed by an Actions workflow from an uploaded artifact, so media binaries never enter git history. Pages was switched to the `workflow` build type on 2026-09-28 and serves at `https://ian-costa18.github.io/AviAnki/`.
- **Durable store.** Each published catalog is also attached to a GitHub Release (`catalog-YYYY-MM-DD`) as a tarball. A deploy that only changes the web app pulls the latest release rather than rebuilding the catalog. Browsers can't read release assets because there's no CORS, but the workflow can.
- **Budget.** The published site has a hard cap of **900 MB** (Pages' limit is 1 GB). The validation gate in [0014](0014-catalog-rebuilds.md) enforces it.

## Constraints this carries

- Catalog fetches send **no custom request headers**. Pages answers a CORS preflight with 405.
- `max-age` is fixed at 600 seconds, so cache behaviour has to come from content-addressed filenames ([0013](0013-catalog-layout.md)).
- A deploy times out after 10 minutes. **Nobody has checked this at ~400 MB yet.** The first build milestone is a dummy-data deploy that measures it.
- There's a soft limit of 100 GB/month of bandwidth, which can't be bought up. `base_url` in the manifest is configurable, so moving hosts later is a config change.
