// The page (spec section 7): Pick -> Building -> Done. The other modules do the work: catalog.js
// reads the catalog, select.js chooses the birds, parts.js decides how to split a big build,
// deck.js writes the .apkg and lastmile.js says what to do with it.

import { selectSpecies, TIER_STANDARD, STANDARD_LIMIT } from "./select.js";
import { buildDeck, loadNotetypes, mediaFiles } from "./deck.js";
import { orderedPrefetch } from "./apkg/prefetch.js";
import {
  CatalogError, MESSAGE_UPDATED, createMediaFetcher, loadManifest, loadRegion,
  loadSpeciesFile, manifestUrl,
} from "./catalog.js";
import { detectPlatform, renderStudyGuide } from "./lastmile.js";
import { setupCustomize } from "./customize.js";
import {
  birdCounter, downloadWhat, fileName, isConstrained, isOutOfMemory, partSizeOverride, planParts, plural,
} from "./parts.js";

const $ = (id) => document.getElementById(id);
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
const COUNTRIES = { US: "United States", CA: "Canada" };
const REGION_KEY = "avianki.region";
const BUILDING_KEY = "avianki.building";

// Storage can be missing or throw (private windows, blocked cookies); the page works without it.
const store = (area) => ({
  get(key) { try { return globalThis[area].getItem(key); } catch { return null; } },
  set(key, value) { try { globalThis[area].setItem(key, value); } catch { /* not remembered */ } },
  remove(key) { try { globalThis[area].removeItem(key); } catch { /* nothing to do */ } },
});
const remembered = store("localStorage");
const session = store("sessionStorage");

const platform = detectPlatform({
  userAgent: navigator.userAgent, platform: navigator.platform, maxTouchPoints: navigator.maxTouchPoints,
});
const constrained = isConstrained({ deviceMemory: navigator.deviceMemory, platform });
const partSize = partSizeOverride(location.search);

let manifest = null;
// After an out-of-memory, the next builds are split into parts. A tab that was killed mid-build
// (the usual way a phone runs out of memory) leaves BUILDING_KEY behind, which counts too. A tab the
// user reloads or leaves fires `pagehide` and clears it first, so only a kill (which fires nothing)
// is mistaken for running out of memory.
let forceParts = session.get(BUILDING_KEY) !== null;
session.remove(BUILDING_KEY);
addEventListener("pagehide", () => session.remove(BUILDING_KEY));
let customize = null; // the "Customize your cards" section, once notetypes.json has loaded
let previewDataStarted = false;
let building = false; // one build at a time: a second submit while one runs is ignored
let saved = []; // {name, url, blob} of the last build, for "Save again"

// --- screens and messages -----------------------------------------------------------------

function show(name, { focus = true } = {}) {
  for (const id of ["pick", "build", "done"]) $(`screen-${id}`).hidden = id !== name;
  if (focus) {
    $({ pick: "pick-title", build: "build-title", done: "done-title" }[name]).focus();
    window.scrollTo(0, 0);
  }
}

function hideError() {
  $("error").hidden = true;
}

function showError(err, retry, { retryLabel = "Try again" } = {}) {
  const format = err instanceof CatalogError && err.kind === "format";
  let text;
  if (err instanceof CatalogError) text = err.message;
  else if (isOutOfMemory(err)) text = "Your device ran out of memory. Closing other tabs, or choosing the Standard size, usually helps.";
  else text = "Sorry, something went wrong while building your deck. Please try again.";
  if (!(err instanceof CatalogError)) console.error(err);
  $("error-text").textContent = text;
  const action = $("error-action");
  const pointless = err instanceof CatalogError && err.kind === "empty"; // trying again changes nothing
  action.hidden = pointless;
  action.textContent = format ? "Reload" : retryLabel;
  action.onclick = format ? () => location.reload() : retry;
  $("error").hidden = false;
}

let lastAnnounced = "";
function setProgress(text, fraction, { announce = false } = {}) {
  $("progress").textContent = text;
  if (fraction !== undefined) $("bar").value = Math.round(fraction * 100);
  if (announce && text !== lastAnnounced) {
    lastAnnounced = text;
    $("announce").textContent = text;
  }
}

// --- the picker ---------------------------------------------------------------------------

function populateRegions() {
  const select = $("region");
  select.replaceChildren(new Option("Pick your state or province…", ""));
  const byCountry = new Map();
  for (const ref of manifest.regions) {
    if (!byCountry.has(ref.country)) byCountry.set(ref.country, []);
    byCountry.get(ref.country).push(ref);
  }
  const codes = [...byCountry.keys()].sort((a, b) => {
    const order = Object.keys(COUNTRIES);
    return (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99) || a.localeCompare(b);
  });
  for (const code of codes) {
    const group = document.createElement("optgroup");
    group.label = COUNTRIES[code] ?? code;
    for (const ref of byCountry.get(code).sort((a, b) => a.name.localeCompare(b.name))) {
      group.append(new Option(ref.name, ref.slug)); // display names only, never the slug
    }
    select.append(group);
  }
  const last = remembered.get(REGION_KEY);
  if (last && manifest.regions.some((r) => r.slug === last)) select.value = last;
  select.disabled = false;
  $("build").disabled = false;
}

function renderFooter() {
  const box = $("dataset-credits");
  box.replaceChildren();
  for (const c of manifest.dataset_credits ?? []) {
    const p = document.createElement("p");
    let link = c.url;
    if (/^https:\/\//i.test(c.url)) {  // never a javascript: or data: href from catalog data
      link = document.createElement("a");
      link.href = c.url;
      link.textContent = c.url;
    }
    p.append(`${c.text}, ${c.licence_id}, `, link, c.modifications ? ` (modified: ${c.modifications})` : "");
    box.append(p);
  }
  $("credits-link").href = new URL("credits.html", manifestUrl()).href;
}

function readSettings() {
  const slug = $("region").value;
  const cards = [...document.querySelectorAll('input[name="cards"]:checked')].map((el) => el.value);
  const month = Number.parseInt($("month").value, 10);
  return {
    slug,
    tier: document.querySelector('input[name="tier"]:checked').value,
    month: Number.isInteger(month) ? month : null,
    cards,
    subdeck: $("subdeck").checked,
    ...(customize?.settings() ?? { theme: "default", nameOnPhoto: false }),
  };
}

function regionRef(slug) {
  return manifest.regions.find((r) => r.slug === slug);
}

/** Tell people, before they start, when a build will come as several files. */
function refreshPartsHint() {
  const hint = $("parts-hint");
  const { slug, tier, month } = readSettings();
  const ref = slug ? regionRef(slug) : null;
  const big = ref && tier !== TIER_STANDARD && ref.species_count > partSize;
  if (big && (constrained || forceParts)) {
    const files = month === null ? `${Math.ceil(ref.species_count / partSize)} smaller files` : "several smaller files";
    hint.textContent = `That's a big deck, so your device will get it as ${files} of up to ${plural(partSize, "bird")} each.`;
    hint.hidden = false;
  } else {
    hint.hidden = true;
  }
}

// --- building -----------------------------------------------------------------------------

function saveFile(url, name) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.hidden = true;
  document.body.append(a);
  a.click();
  a.remove();
}

function sizeText(bytes) {
  return bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

/** Build, once at a time: a second call while one is running does nothing. */
async function runBuild(settings) {
  if (building) return;
  building = true;
  try {
    await buildOnce(settings);
  } finally {
    building = false;
  }
}

async function buildOnce(settings) {
  hideError();
  for (const file of saved) URL.revokeObjectURL(file.url);
  saved = [];
  const ref = regionRef(settings.slug);
  const month = settings.month === null ? "" : ` in ${MONTHS[settings.month - 1]}`;
  const wanted = settings.month === null
    ? `${plural(settings.tier === TIER_STANDARD ? Math.min(STANDARD_LIMIT, ref.species_count) : ref.species_count, "bird")} ` : "";
  $("parts-announce").hidden = true;
  lastAnnounced = "";
  setProgress(`Finding the ${wanted || "birds "}most seen in ${ref.name}${month}…`, 0, { announce: true });
  show("build");
  session.set(BUILDING_KEY, "1");

  try {
    const current = await loadManifest(manifestUrl()); // fresh: a rebuilt catalog renames the hashed files
    const currentRef = current.regions.find((r) => r.slug === settings.slug);
    if (!currentRef) throw new CatalogError("format", MESSAGE_UPDATED);
    manifest = current;
    const [region, speciesFile] = await Promise.all([loadRegion(current, currentRef), loadSpeciesFile(current)]);

    const ids = selectSpecies(region, speciesFile, settings.cards, { tier: settings.tier, month: settings.month });
    const split = forceParts ? "always" : constrained ? "whenLarge" : "never";
    const parts = planParts(ids, speciesFile, settings.cards, { size: partSize, split });
    if (!parts.length) {
      throw new CatalogError("empty", "We couldn't find photos or recordings for the cards you chose. Try a different mix of cards.");
    }
    if (parts.length > 1) {
      const why = forceParts && !constrained ? "Your device ran out of memory, so" : "This is a big deck, so";
      $("parts-announce").textContent = `${why} we'll build it as ${parts.length} smaller files. ` +
        "Your browser will save each one as it's ready; open them all in Anki, in any order.";
      $("parts-announce").hidden = false;
      $("announce").textContent = $("parts-announce").textContent;
    }

    const fetchMedia = createMediaFetcher(current);
    const feed = (files) => orderedPrefetch(files, fetchMedia);
    const subdeck = settings.subdeck ? currentRef.name : null;
    const built = [];

    for (const part of parts) {
      const files = mediaFiles(part.notes);
      const birds = birdCounter(part.notes, files);
      const label = part.count > 1 ? `Part ${part.index} of ${part.count}: ` : "";
      const what = downloadWhat(part.notes);
      const overall = (fraction) => (part.index - 1 + fraction) / part.count;
      const { blob, summary } = await buildDeck({
        manifest: current, speciesFile, notes: part.notes, subdeck, media: feed,
        theme: settings.theme, nameOnPhoto: settings.nameOnPhoto,
        onProgress({ stage, done = 0, total = 0 }) {
          if (stage === "media" && done < total) {
            setProgress(`${label}Downloading ${what} (${birds.done(done)} of ${birds.total})…`,
              overall(done / total), { announce: done === 0 || done % Math.ceil(total / 4) === 0 });
          } else if (stage === "media" || stage === "done") {
            setProgress(`${label}Packing your deck…`, overall(0.98), { announce: true });
          } else if (stage === "database") {
            setProgress(`${label}Downloading ${what} (0 of ${birds.total})…`, overall(0));
          }
        },
      });
      const name = fileName(settings.slug, part);
      const url = URL.createObjectURL(blob);
      saved.push({ name, url, blob });
      saveFile(url, name);
      built.push({ part, summary, birds: birds.total });
    }

    session.remove(BUILDING_KEY);
    renderDone(currentRef, built);
    show("done");
  } catch (err) {
    session.remove(BUILDING_KEY);
    for (const file of saved) URL.revokeObjectURL(file.url);
    saved = [];
    if (isOutOfMemory(err) && !forceParts) {
      forceParts = true; // "the next attempt" is in parts; do it now rather than make people ask
      return buildOnce(settings);
    }
    show("pick");
    showError(err, () => runBuild(settings));
  }
}

function canShareFile(file) {
  try {
    return typeof navigator.canShare === "function" && navigator.canShare({ files: [file] });
  } catch {
    return false;
  }
}

function renderDone(ref, built) {
  const birds = built.reduce((n, b) => n + b.birds, 0);
  const cards = built.reduce((n, b) => n + b.summary.noteCount, 0);
  const bytes = built.reduce((n, b) => n + b.summary.bytes, 0);
  const files = built.length > 1 ? ` in ${plural(built.length, "file")}. Open them all in Anki, in any order` : "";
  $("done-summary").textContent = `${ref.name}: ${plural(birds, "bird")}, ${plural(cards, "card")}, ${sizeText(bytes)}${files}.`;

  const list = $("downloads");
  list.replaceChildren();
  for (const { name, url, blob } of saved) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = `${name} (${sizeText(blob.size)})`;
    const again = document.createElement("a");
    again.href = url;
    again.download = name;
    again.textContent = "Save again";
    again.setAttribute("aria-label", `Save ${name} again`);
    li.append(label, again);

    const file = new File([blob], name, { type: blob.type || "application/octet-stream" });
    if (canShareFile(file)) {
      const share = document.createElement("button");
      share.type = "button";
      share.textContent = "Share";
      share.setAttribute("aria-label", `Share ${name}`);
      share.onclick = async () => {
        try {
          await navigator.share({ files: [file] });
        } catch (err) {
          if (err?.name !== "AbortError") console.error(err); // closing the share sheet is not an error
        }
      };
      li.append(share);
    }
    list.append(li);
  }
}

// --- start-up -----------------------------------------------------------------------------

async function init() {
  hideError();
  try {
    manifest = await loadManifest(manifestUrl());
  } catch (err) {
    showError(err, init);
    return;
  }
  populateRegions();
  renderFooter();
  refreshPartsHint();
  customize?.setManifest(manifest);
  startPreviewData();
}

/** Once the catalog and the card section are both ready, fetch the species file (when idle) for the preview's real bird. */
function startPreviewData() {
  if (previewDataStarted || !customize || !manifest) return;
  previewDataStarted = true;
  const current = manifest;
  const idle = globalThis.requestIdleCallback ?? ((fn) => setTimeout(fn, 200));
  idle(async () => {
    try {
      customize.setCatalog(current, await loadSpeciesFile(current));
    } catch { /* the preview keeps its placeholder card */ }
  });
}

function syncProblems() {
  const { slug, cards } = readSettings();
  if (slug !== "") $("region-problem").hidden = true;
  if (cards.length > 0) $("cards-problem").hidden = true;
}

$("form").addEventListener("submit", (event) => {
  event.preventDefault();
  const settings = readSettings();
  $("region-problem").hidden = settings.slug !== "";
  $("cards-problem").hidden = settings.cards.length > 0;
  if (!settings.slug) return $("region").focus();
  if (!settings.cards.length) {
    $("advanced").open = true;
    return document.querySelector('input[name="cards"]').focus();
  }
  remembered.set(REGION_KEY, settings.slug);
  runBuild(settings);
});

for (const id of ["region", "month"]) $(id).addEventListener("change", refreshPartsHint);
// A validation message goes as soon as its input is fixed, not on the next submit.
$("region").addEventListener("change", syncProblems);
for (const el of document.querySelectorAll('input[name="cards"]')) {
  el.addEventListener("change", syncProblems);
  el.addEventListener("change", () => customize?.cardsChanged());
}
for (const el of document.querySelectorAll('input[name="tier"]')) el.addEventListener("change", refreshPartsHint);
$("again").addEventListener("click", () => show("pick"));

// The study guide is one component in two places: before anyone builds anything, and on Done.
renderStudyGuide($("study-pick"), platform, { id: "study-pick", heading: "How to study your deck" });
renderStudyGuide($("study-done"), platform, { id: "study-done", heading: "Now, open it in Anki" });
// A plain link would put "#study-pick" in the page address, which holds the card look (#theme=...).
$("study-link").addEventListener("click", (event) => {
  event.preventDefault();
  const heading = $("study-pick-title");
  heading.scrollIntoView({ behavior: "smooth", block: "start" });
  heading.focus({ preventScroll: true });
});
loadNotetypes()
  .then((nt) => {
    $("licence-notice").textContent = nt.description.licence_notice;
    customize = setupCustomize({
      notetypes: nt, store: remembered,
      cards: () => readSettings().cards,
    });
    if (manifest) customize.setManifest(manifest);
    startPreviewData();
  })
  .catch((err) => { console.error(err); /* the credits page carries the same licence notice */ });
init();
