// Species selection and note planning: a line-for-line mirror of the pure half of
// src/avianki/deck/build.py (`select_species`, `plan_notes`; spec section 6, ADR 0010).
// tests/web/test_web_select.py runs every case in tests/fixtures/selection/cases.json
// through selectSpecies, and the equivalence tests compare whole decks with the Python
// writer, so a drift in either language fails a test.

export const TIER_STANDARD = "standard";
const TIER_EVERYTHING = "everything";
const TIERS = [TIER_STANDARD, TIER_EVERYTHING];
export const STANDARD_LIMIT = 100;

// Card types in the order notes are written (ADR 0010). Frozen.
export const CARD_TYPES = ["photo", "audio", "photo_audio"];

const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

/** The card types in `cards`, in CARD_TYPES order. Unknown names are a RangeError. */
function wantedCardTypes(cards) {
  const wanted = new Set(cards);
  const unknown = [...wanted].filter((c) => !CARD_TYPES.includes(c)).sort();
  if (unknown.length) {
    throw new RangeError(`unknown card types ${unknown}; expected some of ${CARD_TYPES}`);
  }
  return CARD_TYPES.filter((c) => wanted.has(c));
}

/**
 * `{photo, audio}` (first assets, either may be null) when `entry` has the media `cardType`
 * needs, else null. `photo` needs a photo, `audio` a recording and `photo_audio` both; both first
 * assets come back either way, for the answer side.
 */
function cardMedia(entry, cardType) {
  const photo = entry.photo?.length ? entry.photo[0] : null;
  const audio = entry.audio?.length ? entry.audio[0] : null;
  const needsPhoto = cardType === "photo" || cardType === "photo_audio";
  const needsAudio = cardType === "audio" || cardType === "photo_audio";
  if ((needsPhoto && !photo) || (needsAudio && !audio)) return null;
  return { photo, audio };
}

/**
 * Species ids for a region that will each get at least one note, in the region's rank order.
 *
 * 1. Take the region's ordered list.
 * 2. With a month (1-12) keep a species when `monthly[month - 1] >= 0.1 * max(monthly)`,
 *    computed in integers (`10 * value >= max`) so a value at exactly 10% of the peak is kept
 *    (0.1 * 30 is 3.0000000000000004 in floating point). An all-zero vector is never kept.
 * 3. Keep only species that would get a note for `cards`: a photo card needs a photo, an audio
 *    card a recording, photo_audio both. A species missing from the species file is dropped
 *    with a warning.
 * 4. Take the first 100 (standard) or all of them (everything).
 *
 * The media check comes before the limit, so a Standard deck has 100 birds whenever the region
 * has that many with media (amended 2026-09-30).
 *
 * @param {{species: Array<[string, number[]]>}} regionFile a parsed region file
 * @param {Object<string, {photo: object[], audio: object[]}>} speciesFile
 * @param {Iterable<string>} cards a subset of CARD_TYPES, in any order
 * @param {{tier: string, month?: number|null, warn?: (message: string) => void}} options
 * @returns {string[]}
 */
export function selectSpecies(regionFile, speciesFile, cards, { tier, month = null, warn = console.warn } = {}) {
  if (!TIERS.includes(tier)) throw new RangeError(`tier must be one of ${TIERS}, got ${tier}`);
  if (month !== null && month !== undefined && !(Number.isInteger(month) && month >= 1 && month <= 12)) {
    throw new RangeError(`month must be 1-12 or null, got ${month}`);
  }
  const wanted = wantedCardTypes(cards);
  const ids = [];
  for (const [speciesId, monthly] of regionFile.species) {
    if (month !== null && month !== undefined) {
      const peak = Math.max(...monthly);
      if (peak === 0 || monthly[month - 1] * 10 < peak) continue;
    }
    if (!hasOwn(speciesFile, speciesId)) {
      warn(`species ${JSON.stringify(speciesId)} is not in the species file; skipped`);
      continue;
    }
    if (!wanted.some((cardType) => cardMedia(speciesFile[speciesId], cardType))) continue;
    ids.push(speciesId);
    if (tier === TIER_STANDARD && ids.length === STANDARD_LIMIT) break;
  }
  return ids;
}

/**
 * One note per selected card type whose media exists, in rank then card-type order.
 *
 * `photo` needs the species' first photo, `audio` its first recording and `photo_audio`
 * both; every note then carries both first assets, for the answer side. Only the first
 * photo and first recording are used. A species missing from the species file is skipped
 * with a warning; a repeated id is planned once.
 *
 * @param {Iterable<string>} speciesIds already in rank order (an array, as selectSpecies returns)
 * @param {Object<string, {name: string, sci: string, photo: object[], audio: object[], ioc_name?: string}>} speciesFile
 * @param {Iterable<string>} cards a subset of CARD_TYPES, in any order
 * @param {{warn?: (message: string) => void}} [options]
 * @returns {Array<{speciesId: string, cardType: string, photo: object|null, audio: object|null}>}
 */
export function planNotes(speciesIds, speciesFile, cards, { warn = console.warn } = {}) {
  const ordered = wantedCardTypes(cards);

  const notes = [];
  const seen = new Set();
  for (const speciesId of speciesIds) {
    if (seen.has(speciesId)) continue;
    seen.add(speciesId);
    if (!hasOwn(speciesFile, speciesId)) {
      warn(`species ${JSON.stringify(speciesId)} is not in the species file; skipped`);
      continue;
    }
    for (const cardType of ordered) {
      const media = cardMedia(speciesFile[speciesId], cardType);
      if (media) notes.push({ speciesId, cardType, photo: media.photo, audio: media.audio });
    }
  }
  return notes;
}
