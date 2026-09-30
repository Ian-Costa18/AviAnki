// Reading the published catalog (spec section 5, ADR 0013): the manifest, then the region and
// species files it names, then media. Every path is resolved against `manifest.base_url`.
//
// * The manifest is fetched with `cache: "no-cache"` on every visit; everything else is
//   content-addressed, so the browser's default cache is right.
// * Media goes through Cache Storage keyed by its (hashed) URL: read when present, else fetched
//   and stored. Where `caches` is unavailable it is simply fetched.
// * A network failure is retried twice with a growing pause, then surfaces as one plain message.

const SUPPORTED_FORMAT = 1;
const DEFAULT_MANIFEST = "catalog/manifest.json"; // next to the page, as assemble_site.py lays out the site
const MEDIA_CACHE = "avianki-media-v1";
const RETRIES = 2;
const BACKOFF_MS = [400, 1200];

const MESSAGE_NETWORK = "We couldn't reach the bird catalog. Check your connection and try again.";
export const MESSAGE_UPDATED = "AviAnki has been updated. Please reload.";

/** `kind` is "network" (after retries) or "format" (the catalog is newer than this page). */
export class CatalogError extends Error {
  constructor(kind, message, cause) {
    super(message, { cause });
    this.name = "CatalogError";
    this.kind = kind;
  }
}

/** The manifest URL: `?catalog=<url>` when given (for testing against a live catalog), else next to the page. */
export function manifestUrl(pageHref = globalThis.location?.href) {
  const page = new URL(pageHref);
  // ?catalog= is for local development only. On the public site a crafted link could otherwise
  // build a deck named AviAnki from someone else's catalog, overwriting the user's notes on import.
  const override = isLocalHost(page.hostname) ? page.searchParams.get("catalog") : null;
  return new URL(override || DEFAULT_MANIFEST, page).href;
}

function isLocalHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

/** A catalog path (`media/ab12.webp`) as a URL: relative to `manifest.base_url`, ADR 0013. */
function resolveUrl(manifest, path) {
  const base = manifest.base_url.endsWith("/") ? manifest.base_url : manifest.base_url + "/";
  return new URL(path, base).href;
}

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(timer); reject(signal.reason); }, { once: true });
  });

/** Run `task`, retrying failures RETRIES times; give up as a network CatalogError. */
async function withRetries(task, { signal } = {}) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await task();
    } catch (err) {
      // A RangeError is an allocation failure, not the network: the app reacts to it (parts).
      if (signal?.aborted || err?.name === "AbortError" || err instanceof CatalogError || err instanceof RangeError) throw err;
      if (attempt >= RETRIES) throw new CatalogError("network", MESSAGE_NETWORK, err);
      await sleep(BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)], signal);
    }
  }
}

async function fetchOk(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response;
}

const fetchJson = (url) => withRetries(async () => (await fetchOk(url)).json());

/** The manifest, or a CatalogError: "format" for a format this page can't read, "network" otherwise. */
export async function loadManifest(url = manifestUrl()) {
  const manifest = await withRetries(async () => {
    const parsed = await (await fetchOk(url, { cache: "no-cache" })).json();
    if (parsed?.format !== undefined && parsed.format !== SUPPORTED_FORMAT) {
      throw new CatalogError("format", MESSAGE_UPDATED);
    }
    if (parsed?.format !== SUPPORTED_FORMAT || !Array.isArray(parsed.regions) || typeof parsed.base_url !== "string") {
      throw new Error(`${url} is not a catalog manifest`);
    }
    return parsed;
  });
  return manifest;
}

/** A region file by manifest row. */
export const loadRegion = (manifest, ref) => fetchJson(resolveUrl(manifest, ref.file));

/** The species file: every species' names, chosen media and credit lines. */
export const loadSpeciesFile = (manifest) => fetchJson(resolveUrl(manifest, manifest.species_file));

/**
 * `(file, signal) => Promise<Uint8Array>` for `orderedPrefetch`: media by catalog path, through Cache
 * Storage. A cache that can't be opened, read or written is ignored, never fatal.
 */
export function createMediaFetcher(manifest) {
  let cachePromise = null;
  const openCache = () => {
    cachePromise ??= (async () => {
      try {
        return globalThis.caches ? await caches.open(MEDIA_CACHE) : null;
      } catch {
        return null; // private windows and blocked storage throw
      }
    })();
    return cachePromise;
  };

  return async (file, signal) => {
    const url = resolveUrl(manifest, file);
    const cache = await openCache();
    if (cache) {
      try {
        const hit = await cache.match(url);
        if (hit) return new Uint8Array(await hit.arrayBuffer());
      } catch (err) {
        if (err instanceof RangeError) throw err;
        // any other cache trouble: fall through to the network
      }
    }
    return withRetries(async () => {
      const response = await fetchOk(url, { signal });
      const copy = cache ? response.clone() : null;
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (cache && copy) {
        try { await cache.put(url, copy); } catch { /* over quota: fine, it's only a cache */ }
      }
      return bytes;
    }, { signal });
  };
}
