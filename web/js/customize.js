/**
 * The "Customize your cards" section (ADR 0028): the theme picker, the name-on-photo checkbox,
 * the custom-theme editor and the live preview. It owns one piece of state, the look
 * `{theme, custom, nameOnPhoto}`, which lives in the page address (so a link reproduces it) and
 * in localStorage (a convenience, never relied on).
 *
 * Every custom value comes from a colour input or a fixed list of choices, and is validated by
 * `themes.js` before it becomes CSS.
 */

import { mountPreview, PREVIEW_SPECIES } from "./preview.js";
import {
  ThemeError, builtinTheme, lookFromHash, lookToHash, themeArgument, tokensToToml, validateTokens,
} from "./themes.js";

const LOOK_KEY = "avianki.look";
const $ = (id) => document.getElementById(id);

const COLOUR_LABELS = {
  background: "Background", text: "Text", secondary: "Secondary text", name: "Bird name",
  accent: "Accent (IOC tag and rule)", credits: "Credit text",
};
const CHOICE_LABELS = {
  font: ["Font", { sans: "Sans-serif (your phone's own)", serif: "Serif", rounded: "Rounded", mono: "Monospace", humanist: "Humanist" }],
  name_style: ["Bird name style", { normal: "Normal", caps: "Spaced small capitals" }],
  name_weight: ["Bird name weight", { regular: "Regular", bold: "Bold" }],
  corners: ["Photo corners", { square: "Square", slight: "Slightly rounded", round: "Round" }],
  rule: ["Accent rule", { none: "None", side: "Beside the names" }],
};
const CARD_LABELS = { photo: "Photo", audio: "Audio", photo_audio: "Photo and audio" };

/** "field-guide" -> "Field guide". */
const themeLabel = (name) => name.charAt(0).toUpperCase() + name.slice(1).replace(/-/g, " ");

const clone = (tokens) => structuredClone(tokens);

/**
 * @param {object} opts
 * @param {object} opts.notetypes  the parsed notetypes.json
 * @param {() => string[]} opts.cards  the card types ticked in the form
 * @param {{get(k: string): string|null, set(k: string, v: string): void}} opts.store  localStorage, safely
 * @param {() => void} [opts.onChange]  called after the look changes
 */
export function setupCustomize({ notetypes, cards, store, onChange = () => {} }) {
  const look = notetypes.look;
  let state = lookFromHash(location.hash, look) ?? lookFromHash(store.get(LOOK_KEY) ?? "", look)
    ?? { theme: look.default_theme, custom: null, nameOnPhoto: false };
  let entry = null;
  let manifest = null;
  let lastBuiltin = state.theme === "custom" ? look.default_theme : state.theme;

  const preview = mountPreview({ questionFrame: $("preview-question"), answerFrame: $("preview-answer"), notetypes });

  // --- the controls ------------------------------------------------------------------------

  const themeSelect = $("theme");
  themeSelect.replaceChildren(
    ...look.themes.map((t) => new Option(themeLabel(t.name), t.name)),
    new Option("Custom…", "custom"),
  );
  const fromSelect = $("custom-from");
  fromSelect.replaceChildren(...look.themes.map((t) => new Option(themeLabel(t.name), t.name)));

  const swatches = $("swatches");
  swatches.replaceChildren();
  for (const heading of ["", "Day", "Night"]) {
    const span = document.createElement("span");
    span.className = "swatch-head";
    span.textContent = heading;
    swatches.append(span);
  }
  for (const key of look.colour_keys) {
    const name = document.createElement("span");
    name.className = "swatch-name";
    name.textContent = COLOUR_LABELS[key] ?? key;
    swatches.append(name);
    for (const mode of ["light", "night"]) {
      const input = document.createElement("input");
      input.type = "color";
      input.id = `custom-${mode}-${key}`;
      input.dataset.mode = mode;
      input.dataset.key = key;
      input.setAttribute("aria-label", `${COLOUR_LABELS[key] ?? key}, ${mode === "light" ? "day" : "night"}`);
      input.addEventListener("input", onCustomInput);
      swatches.append(input);
    }
  }

  const choices = $("custom-choices");
  choices.replaceChildren();
  for (const [key, [label, options]] of Object.entries(CHOICE_LABELS)) {
    const field = document.createElement("div");
    field.className = "field";
    const lab = document.createElement("label");
    lab.htmlFor = `custom-${key}`;
    lab.textContent = label;
    const select = document.createElement("select");
    select.id = `custom-${key}`;
    select.dataset.token = key;
    for (const value of Object.keys(look.tables[key])) select.append(new Option(options[value] ?? value, value));
    select.addEventListener("change", onCustomInput);
    field.append(lab, select);
    choices.append(field);
  }

  function writeControls(tokens) {
    for (const input of swatches.querySelectorAll("input[type=color]")) {
      input.value = tokens[input.dataset.mode][input.dataset.key];
    }
    for (const select of choices.querySelectorAll("select")) select.value = tokens[select.dataset.token];
  }

  function readControls() {
    const tokens = { light: {}, night: {} };
    for (const input of swatches.querySelectorAll("input[type=color]")) {
      tokens[input.dataset.mode][input.dataset.key] = input.value;
    }
    for (const select of choices.querySelectorAll("select")) tokens[select.dataset.token] = select.value;
    return validateTokens(tokens, look);
  }

  function showState() {
    themeSelect.value = state.theme;
    $("name-on-photo").checked = state.nameOnPhoto;
    $("custom").hidden = state.theme !== "custom";
    if (state.theme === "custom") {
      writeControls(state.custom);
      fromSelect.value = lastBuiltin;
    }
    $("theme-desc").textContent = state.theme === "custom"
      ? "Your own colours and type, below."
      : builtinTheme(look, state.theme)?.description ?? "";
  }

  // --- events -----------------------------------------------------------------------------------

  function commit() {
    let hash;
    try {
      hash = lookToHash(state, look);
    } catch (error) {
      if (!(error instanceof ThemeError)) throw error;
      return;
    }
    try {
      history.replaceState(null, "", location.pathname + location.search + hash);
    } catch { /* a page that can't change its address still works */ }
    store.set(LOOK_KEY, hash);
    $("copy-status").textContent = "";
    $("theme-text").hidden = true;
    refreshPreview();
    onChange();
  }

  themeSelect.addEventListener("change", () => {
    const choice = themeSelect.value;
    if (choice === "custom") {
      state = { ...state, theme: "custom", custom: state.custom ?? clone(builtinTheme(look, lastBuiltin).tokens) };
    } else {
      lastBuiltin = choice;
      state = { ...state, theme: choice };
    }
    showState();
    commit();
  });

  $("name-on-photo").addEventListener("change", () => {
    state = { ...state, nameOnPhoto: $("name-on-photo").checked };
    commit();
  });

  fromSelect.addEventListener("change", () => {
    lastBuiltin = fromSelect.value;
    state = { ...state, custom: clone(builtinTheme(look, lastBuiltin).tokens) };
    writeControls(state.custom);
    commit();
  });

  function onCustomInput() {
    state = { ...state, custom: readControls() };
    commit();
  }

  $("copy-theme").addEventListener("click", async () => {
    const text = tokensToToml(state.custom, look);
    const area = $("theme-text");
    area.value = text;
    try {
      await navigator.clipboard.writeText(text);
      area.hidden = true;
      $("copy-status").textContent = "Copied! Save it in a file such as my-theme.toml, then build with: avianki REGION --theme-file my-theme.toml";
    } catch {
      area.hidden = false;
      area.select();
      $("copy-status").textContent = "Your browser wouldn't copy it, so here it is. Save it in a file such as my-theme.toml, then build with: avianki REGION --theme-file my-theme.toml";
    }
  });

  $("preview-dark").addEventListener("change", refreshPreview);
  $("preview-card").addEventListener("change", refreshPreview);

  addEventListener("hashchange", () => {
    const next = lookFromHash(location.hash, look);
    if (!next || lookToHash(next, look) === lookToHash(state, look)) return;
    state = next;
    if (state.theme !== "custom") lastBuiltin = state.theme;
    showState();
    commit();
  });

  // --- the preview ------------------------------------------------------------------------------

  /** The card types the question can show: the ticked ones, or photo when none is. */
  function questionTypes() {
    const ticked = cards();
    return ticked.length ? ticked : ["photo"];
  }

  function refreshQuestionPicker() {
    const types = questionTypes();
    const select = $("preview-card");
    const current = select.value;
    if ([...select.options].map((o) => o.value).join() !== types.join()) {
      select.replaceChildren(...types.map((t) => new Option(CARD_LABELS[t] ?? t, t)));
    }
    select.value = types.includes(current) ? current : types[0];
    $("preview-card-wrap").hidden = types.length < 2;
    return select.value;
  }

  function refreshPreview() {
    const cardType = refreshQuestionPicker();
    preview.update({
      theme: themeArgument(state), nameOnPhoto: state.nameOnPhoto, cardType,
      night: $("preview-dark").checked, entry, manifest,
    });
  }

  showState();
  refreshPreview();

  return {
    /** What the build takes: `{theme, nameOnPhoto}`; `theme` is a name or custom tokens. */
    settings: () => ({ theme: themeArgument(state), nameOnPhoto: state.nameOnPhoto }),
    /** The card types ticked in the form changed. */
    cardsChanged: refreshPreview,
    /** The catalog is known: draw the real Rock Pigeon from it when the species file has it. */
    setCatalog(nextManifest, speciesFile) {
      manifest = nextManifest;
      entry = speciesFile?.[PREVIEW_SPECIES] ?? null;
      refreshPreview();
    },
    /** The catalog's manifest only; the preview keeps its placeholder until the species file arrives. */
    setManifest(nextManifest) { manifest = nextManifest; },
  };
}
