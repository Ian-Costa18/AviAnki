# Free, browser-readable hosting for a ~400 MB bird media catalog

Research for [#16](https://github.com/Ian-Costa18/AviAnki/issues/16), under the map [#6](https://github.com/Ian-Costa18/AviAnki/issues/6).
Size budget and the free-hosting constraint come from [#11](https://github.com/Ian-Costa18/AviAnki/issues/11): ~1,000 North American species at ~400 KB each ≈ **400 MB**.

**Date of research:** 2026-08-23. Live header checks were run on that date; vendor behaviour can change, so re-run the checks in [Appendix A](#appendix-a-reproducing-the-live-checks) before relying on them.

---

## Recommendation in one line

**Host the catalog on GitHub Pages, deployed from a GitHub Actions artifact so the binaries never enter git history.** Runner-up is **Cloudflare R2 behind a custom domain**, which is only free if you already own a domain. **GitHub Release assets are ruled out**: they serve no CORS headers, so a browser cannot `fetch()` the bytes.

---

## 1. The decisive fact: Release assets send no CORS headers

This was the single most decision-relevant question in the ticket, and it was verified live rather than taken from documentation.

### What was tested

A release asset on a public repo was requested with an `Origin` header, following the redirect chain. No releases were created. Two independent repos were used to rule out a per-repo quirk.

```
GET https://github.com/cli/cli/releases/download/v2.98.0/gh_2.98.0_checksums.txt
  → 302 to release-assets.githubusercontent.com/... (signed, time-limited URL)
  → 200 (final hop)
```

### Results

| Hop | Status | `Access-Control-Allow-Origin` |
|---|---|---|
| `github.com/.../releases/download/...` | 302 | **absent** |
| `release-assets.githubusercontent.com/...` (final) | 200 | **absent** |
| `OPTIONS` preflight on the final hop | **405** | **absent** |
| Same test, second repo (`git-lfs/git-lfs`) | 200 | **absent** |

There is a tempting near-miss. The REST API asset endpoint *does* send CORS headers on its redirect:

```
GET https://api.github.com/repos/cli/cli/releases/assets/522857887
    Accept: application/octet-stream
  → 302  access-control-allow-origin: *      ← CORS present here
  → 200  (release-assets.githubusercontent.com)  ← CORS absent here
```

This does not help. Under the [Fetch standard's CORS protocol](https://fetch.spec.whatwg.org/#http-redirect-fetch), **every response in a redirect chain must pass the CORS check**, not just the first. The terminal hop carries no `Access-Control-Allow-Origin`, so the browser aborts the fetch and the response is never exposed to script.

### Verdict

> **A browser cannot `fetch()` a GitHub Release asset cross-origin. Release assets can be linked, but their bytes cannot be read by JavaScript.**

Since the whole architecture depends on reading media bytes in the browser to zip them into a `.apkg`, this rules Release assets out as the catalog store — despite them having, on paper, the most generous limits of any option here (see §3).

**Caveat on scope:** if the browser app were itself served *from* `github.com` this would not apply, but it will be served from `*.github.io`, which is a different origin. There is no same-origin escape.

**Secondary problem even if CORS existed:** the signed URL carries a per-request `sig` and a ~40-minute `se` expiry, and the final hop returns **no `Cache-Control` header at all**. Every visitor would get a distinct URL, defeating browser caching entirely.

---

## 2. GitHub Pages — the recommendation

### Documented limits

All figures from [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits):

| Limit | Value | Nature |
|---|---|---|
| Published site size | "Published GitHub Pages sites may be no larger than **1 GB**." | Stated flatly, not marked soft |
| Bandwidth | "a **soft** bandwidth limit of **100 GB per month**" | Explicitly soft |
| Builds | "a **soft** limit of **10 builds per hour**. This limit does not apply if you build and publish your site with a custom GitHub Actions workflow." | Explicitly soft; **waived for Actions workflows** |
| Source repository size | "recommended limit of **1 GB**" | Recommendation |
| Deployment timeout | "deployments will timeout if they take longer than **10 minutes**" | Hard |

**Enforcement, in GitHub's own words:** exceeding quotas means "we may not be able to serve your site, or you may receive a polite email from GitHub Support suggesting strategies for reducing your site's impact on our servers." Rate limiting surfaces as **HTTP 429**.

So the enforcement model is: a polite email first, throttling second. It is not a hard cutoff, but it is also not a guarantee — GitHub reserves the right to stop serving.

**400 MB against a 1 GB site limit leaves roughly 60% headroom.** This is the sizing that [#11](https://github.com/Ian-Costa18/AviAnki/issues/11) was built on, and it holds up.

### Live-verified serving behaviour

Tested against a real binary asset on a Pages site (`pages.github.com/images/slideshow/bootstrap.png`, 156,915 bytes):

| Property | Result | Why it matters |
|---|---|---|
| `access-control-allow-origin` | **`*`** | `fetch()` works cross-origin. **This is the header Release assets lack.** |
| `cache-control` | `max-age=600` | 10 minutes, fixed — see §5 |
| `etag` | `"689c7eef-264f3"` | Enables conditional revalidation |
| Conditional `If-None-Match` | **`304 Not Modified`** | Returning users re-download **zero bytes** |
| `accept-ranges` / Range request | **`206 Partial Content`**, correct `content-range` | Resumable / partial fetches work |
| `OPTIONS` preflight | `405` | **Not a problem** — see below |

The `405` on `OPTIONS` looks alarming but is harmless. A plain `GET` with no custom request headers is a [CORS *simple request*](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS#simple_requests) and is **not preflighted**. The constraint this imposes on the app: **fetch catalog media with no custom headers** (no `Authorization`, no bespoke `X-` headers). Adding one would trigger a preflight that Pages would answer with `405`, breaking the fetch. Nothing in this design needs custom headers, so this is a rule to document rather than an obstacle.

`ACAO: *` was observed on every Pages response tested, including `404` responses and CSS/JS as well as binary — it is blanket, not per-file. It is also **not configurable**; Pages sends it unconditionally.

### Bandwidth arithmetic

The 100 GB/month soft allowance is *not* consumed at 400 MB per user. Users download the media for the species in their chosen region, not the whole catalog. Using the [#11](https://github.com/Ian-Costa18/AviAnki/issues/11) figures:

| Scenario | Per-user download | Deck builds per 100 GB |
|---|---|---|
| One state/region (~400 species) | ~160 MB | ~640 |
| A more typical small deck (~100 species) | ~40 MB | ~2,500 |
| A starter deck (~50 species) | ~20 MB | ~5,000 |

Between roughly **600 and 5,000 deck builds per month** before the soft limit is approached. Adequate for a niche birding tool; a genuine ceiling if the project gets popular. This is the "bandwidth if this gets popular" open question already flagged on the map — the escape route is §3's runner-up.

### Repository health: the artifact deploy

This is the part that resolves the "no binaries in git history" constraint, and it resolves it cleanly.

A custom Actions workflow builds the site and uploads it as an artifact; `actions/deploy-pages` publishes that artifact. Per [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), the artifact must be "a compressed `gzip` archive containing a single `tar` file", and "The `tar` file must be under 10GB in size and should not contain any symbolic or hard links."

**The published content never needs to be committed.** The pipeline generates the 400 MB in the runner, uploads it as an artifact, and Pages serves it. Git history stays clean — no LFS, no giant blobs, no `git filter-repo` regret later.

[`actions/upload-pages-artifact`](https://github.com/actions/upload-pages-artifact) states "The GitHub Pages officially supported maximum size limit is 1GB", with a 10 GB absolute ceiling beyond which Pages will not attempt deployment, and warns that larger artifacts are "more prone to exceeding the maximum deployment timeout of 10 minutes."

**The real risk here is the 10-minute deployment timeout, not the size limit.** 400 MB of already-compressed media (WebP, MP3) tars quickly but must upload and then deploy within the window. This should be measured early rather than assumed. *Not verified — no deploy of this size was performed.*

Note also that Actions minutes are free for public repositories, so the build itself costs nothing.

### Why this is the recommendation

- Genuinely free, with no second vendor, no account beyond GitHub, and no payment method anywhere.
- 400 MB fits the documented 1 GB limit with headroom.
- CORS verified live — the app can read the bytes.
- Binaries never touch git history.
- Same origin as the app itself if the app is served from the same Pages site, which sidesteps CORS entirely as a bonus.

### Failure mode

**Success kills it.** The 100 GB/month bandwidth allowance is soft, and the stated consequence is an email from Support followed by possible throttling or refusal to serve. There is no dashboard, no alert, and no way to buy more — GitHub Pages has no paid tier for bandwidth. If AviAnki gets popular, the first signal may be a support email or users seeing 429s. The mitigation is to have the runner-up pre-planned (below), and to keep per-user download size small through regional sharding.

A secondary failure mode: a catalog that grows past 1 GB. North-America-only is what keeps this from happening, which is exactly why [#11](https://github.com/Ian-Costa18/AviAnki/issues/11) drew that boundary.

---

## 3. Alternatives, and why each loses

### GitHub Release assets — ruled out on CORS

Ironically the most generous limits of anything here. Per [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases):

- "Each file included in a release must be under **2 GiB**."
- "Up to **1000** release assets may be associated with a single release."
- **"There is no limit on the total size of a release, nor bandwidth usage."**

That last quote is the one people reach for, and it is real: release bandwidth is explicitly unmetered, unlike Pages' soft 100 GB. Releases also keep binaries out of git history by design, and GitHub itself recommends them for distributing large files.

**And none of it matters, because the browser cannot read the bytes.** See §1. Releases remain useful for shipping the *CLI*, and could serve a pre-built `.apkg` a user clicks to download — but not as a store the web app fetches from.

### Cloudflare R2 — the runner-up, with a catch

Per [R2 pricing](https://developers.cloudflare.com/r2/pricing/):

| Free tier | Allowance |
|---|---|
| Storage | **10 GB-month / month** |
| Class A operations (writes) | 1 million / month |
| Class B operations (reads) | 10 million / month |
| **Egress** | **Free** |

The zero-egress claim checks out and is stated precisely: "Egressing directly from R2, including via the Workers API, S3 API, and r2.dev domains does not incur data transfer (egress) charges and is free." Note the free tier "only applies to Standard storage, and does not apply to Infrequent Access storage."

400 MB against 10 GB of free storage is a **25x** margin — far more comfortable than Pages' 2.5x. And unmetered free egress directly solves the bandwidth failure mode that caps GitHub Pages.

CORS is fully configurable, unlike Pages. Per [R2 CORS docs](https://developers.cloudflare.com/r2/buckets/cors/), a bucket takes a JSON policy with `AllowedOrigins`, `AllowedMethods`, `AllowedHeaders`, `ExposeHeaders`, and `MaxAgeSeconds`, and custom domains "automatically return CORS response headers for cross-origin requests."

**The catch, and it is the whole story:** per [Public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/), "Public access through `r2.dev` subdomains is **rate-limited and should only be used for development purposes**", and the r2.dev endpoint is "intended for non-production traffic."

So the free `*.r2.dev` hostname is explicitly disclaimed for production. The supported path is a **custom domain**, which requires a domain registered and on Cloudflare. Domains cost money — typically ~$10/year. Under the ticket's hard "costs nothing" test, **R2 is not free unless you already own a domain.**

That makes R2 the right *escape route* rather than the right *starting point*: if Pages bandwidth becomes a problem, the project will likely justify a domain by then, and the migration is a URL-base change in the catalog manifest.

**Also unverified:** whether adding an R2 subscription requires a payment method on file. The [get-started docs](https://developers.cloudflare.com/r2/get-started/) say "R2 is free to get started with included free monthly usage" but also require completing "the checkout flow to add an R2 subscription to your account", without stating whether a card is mandatory. **This should be confirmed by attempting a signup before depending on R2.**

**Failure mode:** silent dependence on `r2.dev` in production, then rate-limiting under load with no warning — the documentation says it is rate-limited but does not publish the threshold. Plus a second vendor, a second account, and a renewal bill that, if missed, takes the catalog offline.

### Git LFS — ruled out, bandwidth is metered and billed

A common trap worth documenting so it is not re-litigated. Per [Git LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs), GitHub Free includes **10 GiB storage and 10 GiB bandwidth** per billing cycle, and **"Bandwidth is billed for each GiB of data downloaded."**

At 400 MB, roughly **25 full catalog downloads exhausts the monthly bandwidth allowance.** Then: with a payment method, you are billed; without one, **"Git LFS support is disabled on your account until the next month"** — the catalog goes dark.

LFS fails the "costs nothing" test outright, and fails it fast. Ruled out.

### `raw.githubusercontent.com` — ruled out on repository health

Verified live: sends `access-control-allow-origin: *` and `cache-control: max-age=300`, so a browser genuinely *can* fetch it.

But raw serves files **out of git**, which means committing 400 MB of binaries to history — the precise thing [#11](https://github.com/Ian-Costa18/AviAnki/issues/11) forbade. It also collides with GitHub's own guidance in [About large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github): files over **50 MiB** warn, files over **100 MiB** are **blocked**, and "We recommend repositories remain small, ideally less than 1 GB." Individual media files are small enough, but the repo would bloat permanently and every clone would pay for it. Raw is also undocumented as a CDN and rate-limited in practice. Ruled out.

### jsDelivr — viable but dependent on a third party's goodwill

Verified live: `access-control-allow-origin: *`, and excellent caching — `cache-control: public, max-age=604800, s-maxage=43200` for GitHub-sourced files, and `max-age=31536000, immutable` for versioned npm packages. Free, no account, global CDN.

Two problems. First, it fronts a GitHub repo, so the binaries still have to live in git — inheriting the repository-health objection above. Second, jsDelivr enforces a **~20 MB per-file limit** and package-size caps, and its acceptable-use policy exists precisely to stop the service being used as bulk file storage. A 400 MB media catalog is squarely the use case that policy targets. Serving it from someone else's free CDN without asking is the kind of thing that gets a project blocked.

*Partially unverified:* the exact current limits could not be read from jsDelivr's official documentation page (it renders as navigation shell); the 20 MB figure comes from the jsdelivr/jsdelivr issue tracker, not primary docs. Treat as indicative.

### Others considered

Cloudflare Pages, Netlify, and Vercel all have free tiers with configurable headers, but each meters bandwidth on the free plan and each adds a vendor. None improves on GitHub Pages for this specific shape of problem — a public, open-source, GitHub-hosted project whose build already runs in Actions. Not investigated in depth.

---

## 4. Cache behaviour: what a returning user re-downloads

This matters more than it first appears, because it determines whether the 100 GB soft limit is consumed once per user or once per visit.

### What was measured on GitHub Pages

```
Cache-Control: max-age=600        (10 minutes, fixed)
ETag: "689c7eef-264f3"
If-None-Match: <etag>  →  304 Not Modified, zero body
```

So the behaviour for a returning user is:

- **Within 10 minutes:** served from browser cache. **No request at all.**
- **After 10 minutes:** one conditional request per file, answered **`304`** with no body. **Effectively zero bandwidth**, but one round trip per file.

The bytes are not re-downloaded. That is the important part — bandwidth is consumed roughly once per user per catalog version, not once per visit.

### The publisher has almost no control

GitHub Pages **does not support custom headers**. There is no `_headers` file, no `.htaccess`, no config that injects response headers. `max-age=600` is fixed and cannot be raised. This is long-standing and repeatedly confirmed in GitHub's own community discussions ([#54257](https://github.com/orgs/community/discussions/54257), [#11884](https://github.com/orgs/community/discussions/11884)); GitHub has stated there is no ETA for the feature. *Verified live (the header is present and is `max-age=600`) and corroborated by GitHub community discussions rather than by formal documentation, which does not address the topic.*

The one lever available is **the URL itself**. Content-addressed filenames — `media/a1b2c3d4.webp`, where the hash is of the content — make a URL immutable by construction. The content at a given URL then never changes, so a stale cache is never *wrong*, and a rebuilt catalog simply produces new URLs for changed assets while unchanged assets keep theirs and stay cached.

### The design consequence

`max-age=600` means a returning user makes **one conditional request per file**. At one file per image and per audio clip, a 100-species deck is ~400 files, so ~400 revalidation round trips — cheap in bytes but slow in latency, especially on mobile.

**This argues for bundling.** Rather than one HTTP request per media file, the catalog should ship **per-region or per-shard bundles** the app fetches whole and unpacks client-side. Fewer, larger, content-addressed files:

- collapse hundreds of revalidations into a handful,
- get `304`s on the bundle rather than on every asset,
- and let a hash in the bundle filename make the whole shard immutable.

This connects directly to the map's open "catalog versioning and cache invalidation" question, and to the `.apkg` assembly prototype — the app is already going to unzip things client-side, so unpacking a bundle is not new machinery.

A manifest file (small, frequently changing) should be kept *separate* from the bundles (large, immutable), so the 10-minute revalidation lands on the cheap file and the expensive ones stay cached.

---

## 5. Recommendation

### Primary: GitHub Pages, deployed from an Actions artifact

| | |
|---|---|
| **Cost** | Zero. No payment method anywhere. Actions minutes free for public repos. |
| **Fit** | 400 MB against a documented 1 GB site limit — ~60% headroom |
| **CORS** | `access-control-allow-origin: *`, verified live, blanket, unconditional |
| **Repo health** | Artifact deploy — binaries never enter git history |
| **Caching** | `max-age=600` + ETag → returning users re-download zero bytes |
| **Ceiling** | ~600–5,000 deck builds/month against the soft 100 GB allowance |

**Conditions to honour:**

1. Fetch media with **no custom request headers** — a preflight would hit `405`.
2. Use **content-addressed filenames** for immutability, since `max-age` cannot be raised.
3. **Bundle per region/shard** rather than one request per media file.
4. Measure the deploy against the **10-minute timeout** early, at realistic size.
5. Keep the catalog North-America-only — that constraint is what keeps 400 MB under 1 GB.

**Failure mode:** popularity. The 100 GB/month bandwidth allowance is soft, unmonitored, and unbuyable. The warning shot is an email from GitHub Support or users seeing HTTP 429. There is no paid upgrade path within Pages, so the response is migration, not a bigger plan.

### Runner-up: Cloudflare R2 behind a custom domain

| | |
|---|---|
| **Cost** | Storage and egress free; **a domain is not** (~$10/yr) |
| **Fit** | 400 MB against 10 GB free storage — 25x headroom |
| **CORS** | Fully configurable per bucket |
| **Bandwidth** | **Free and unmetered** — solves Pages' one real weakness |

**Failure mode:** the free `r2.dev` hostname is documented as rate-limited and non-production, so depending on it invites silent throttling at an unpublished threshold. Avoiding that requires a custom domain, which means the setup is not strictly free — plus a second vendor, a second account, an unverified question about whether a payment method is required, and a renewal that takes the catalog offline if missed.

**When to switch:** if Pages bandwidth becomes a real constraint. Keeping the catalog base URL configurable in the manifest makes this a config change rather than a rewrite — worth doing from day one as cheap insurance.

### Ruled out

| Option | Reason |
|---|---|
| **GitHub Release assets** | **No CORS headers on the asset host.** Browser cannot `fetch()` the bytes. Verified live on two repos. |
| **Git LFS** | Bandwidth metered and billed; ~25 catalog downloads exhausts the free 10 GiB, then LFS is disabled or billed. |
| **`raw.githubusercontent.com`** | Requires committing 400 MB to git history. CORS works, repo health does not. |
| **jsDelivr** | Still needs binaries in git; ~20 MB per-file cap; a 400 MB catalog is what its acceptable-use policy exists to prevent. |

---

## What could not be verified

Stated plainly, per the ticket's instruction:

1. **Whether a Cloudflare R2 subscription requires a payment method on file.** Docs say "free to get started" but also require a checkout flow. Confirm by attempting signup before depending on R2.
2. **Whether a ~400 MB Pages deploy completes inside the 10-minute timeout.** No deploy of this size was performed. Measure early.
3. **jsDelivr's exact current limits.** The official documentation page renders as a navigation shell; the ~20 MB figure comes from the project's issue tracker, not primary docs.
4. **The `r2.dev` rate-limit threshold.** Documented as rate-limited; the actual numbers are not published.
5. **Whether GitHub's Pages bandwidth soft limit is enforced in practice, and at what point.** GitHub documents the consequence ("polite email", possible refusal to serve) but not the trigger.
6. **GitHub Pages' fixed `max-age=600` and lack of custom-header support** is verified live and corroborated by GitHub community discussions, but is *not* stated in formal GitHub documentation.

---

## Appendix A: reproducing the live checks

```sh
# 1. Release asset CORS — the decisive test. Expect NO access-control-* on the final hop.
SRC="https://github.com/cli/cli/releases/download/v2.98.0/gh_2.98.0_checksums.txt"
U=$(curl -s -o /dev/null -w '%{redirect_url}' "$SRC")
curl -s -D - -o /dev/null -H "Origin: https://example.github.io" "$U" | grep -i access-control
# → (no output)

# 2. Preflight on the release asset host. Expect 405.
curl -s -D - -o /dev/null -X OPTIONS \
     -H "Origin: https://example.github.io" \
     -H "Access-Control-Request-Method: GET" "$U" | head -1
# → HTTP/2 405

# 3. GitHub Pages CORS. Expect access-control-allow-origin: *
P="https://pages.github.com/images/slideshow/bootstrap.png"
curl -s -D - -o /dev/null -H "Origin: https://other.example.com" "$P" \
  | grep -iE "access-control-allow-origin|cache-control|etag"
# → access-control-allow-origin: *
# → cache-control: max-age=600
# → etag: "689c7eef-264f3"

# 4. Returning-user cache path. Expect 304 with no body.
ET=$(curl -s -D - -o /dev/null "$P" | grep -i "^etag:" | sed 's/^[Ee][Tt][Aa][Gg]: //' | tr -d '\r')
curl -s -D - -o /dev/null -H "If-None-Match: $ET" "$P" | head -1
# → HTTP/2 304

# 5. Range request support on Pages. Expect 206.
curl -s -D - -o /dev/null -r 0-99 "$P" | grep -iE "^HTTP|content-range"
# → HTTP/2 206
# → content-range: bytes 0-99/156915
```

## Appendix B: sources

**GitHub**
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) — site size, bandwidth, builds, timeout
- [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) — artifact-based deploy
- [`actions/upload-pages-artifact`](https://github.com/actions/upload-pages-artifact) — 1 GB supported / 10 GB ceiling
- [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) — 2 GiB/file, 1000 assets, no total size or bandwidth limit
- [About large files on GitHub](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) — 50 MiB warn, 100 MiB block, <1 GB repo
- [Git LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs) — 10 GiB storage/bandwidth, metered
- Community discussions on custom headers: [#54257](https://github.com/orgs/community/discussions/54257), [#11884](https://github.com/orgs/community/discussions/11884)

**Cloudflare**
- [R2 pricing](https://developers.cloudflare.com/r2/pricing/) — 10 GB-month free, free egress
- [R2 public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/) — r2.dev rate-limited, non-production
- [R2 CORS](https://developers.cloudflare.com/r2/buckets/cors/) — policy configuration
- [R2 get started](https://developers.cloudflare.com/r2/get-started/) — subscription/checkout

**Standards**
- [Fetch standard — HTTP redirect fetch](https://fetch.spec.whatwg.org/#http-redirect-fetch) — CORS applies to every hop
- [MDN — CORS simple requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS#simple_requests) — when preflight is skipped
