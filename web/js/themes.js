/**
 * Card themes and the name-on-photo layout in the browser (ADR 0028): the twin of
 * src/avianki/deck/themes.py and of `models_for` in deck/notetypes.py.
 *
 * Python defines everything once. scripts/gen_web_notetypes.py exports it as `notetypes.look`:
 * card.css, the token template, the fixed tables a theme's choices come from, each built-in theme
 * (tokens, extra rules, description) and the two layout pieces. This file only applies the same
 * rules to it:
 *
 *     css = card.css  +  "\n" + <theme css>  +  "\n" + <layout css>     (empty pieces left out)
 *
 * A theme is a set of tokens (see `validateTokens`). A built-in theme's CSS is the template
 * filled from its tokens plus its extra rules; `default` is empty, so a default build carries
 * card.css exactly. tests/web/test_web_themes.py compares this with Python for every theme and
 * layout, and for custom token sets.
 *
 * Safety: CSS is made from validated values only. A colour must be `#rrggbb`; every other value
 * must be a key of a fixed table; nothing a person types ever reaches CSS or HTML otherwise.
 */

export class ThemeError extends Error {}

const HEX = /^#[0-9a-fA-F]{6}$/;
const MODES = ["light", "night"];

/** The built-in theme called `name`, or undefined. */
export function builtinTheme(look, name) {
  return look.themes.find((t) => t.name === name);
}

/**
 * Tokens as the page and the TOML file hold them, checked and normalised (colours lower case).
 * Throws `ThemeError` for a colour that is not `#rrggbb` or a choice that is not in its table.
 * Unknown keys throw too, so a typo is not silently ignored.
 */
export function validateTokens(raw, look) {
  if (!raw || typeof raw !== "object") throw new ThemeError("a theme must be a set of tokens");
  const choices = Object.keys(look.tables);
  const allowed = new Set([...choices, ...MODES]);
  const unknown = Object.keys(raw).filter((k) => !allowed.has(k));
  if (unknown.length) throw new ThemeError(`unknown key(s) ${unknown.join(", ")}`);
  const out = {};
  for (const key of choices) {
    const value = raw[key];
    if (typeof value !== "string" || !Object.hasOwn(look.tables[key], value)) {
      throw new ThemeError(`${key}: ${JSON.stringify(value)} is not one of ${Object.keys(look.tables[key]).join(", ")}`);
    }
    out[key] = value;
  }
  for (const mode of MODES) {
    const colours = raw[mode];
    if (!colours || typeof colours !== "object") throw new ThemeError(`${mode} must be a table of colours`);
    out[mode] = {};
    for (const key of look.colour_keys) {
      const value = colours[key];
      if (typeof value !== "string" || !HEX.test(value)) {
        throw new ThemeError(`${key}: ${JSON.stringify(value)} is not a colour like #1a2b3c`);
      }
      out[mode][key] = value.toLowerCase();
    }
  }
  return out;
}

function substitutions(tokens, look) {
  const subs = {};
  for (const key of Object.keys(look.tables)) subs[key] = look.tables[key][tokens[key]];
  for (const mode of MODES) {
    for (const key of look.colour_keys) subs[`${mode}.${key}`] = tokens[mode][key];
  }
  return subs;
}

/** The CSS a set of (validated) tokens stands for: the template with its placeholders filled. */
export function cssFor(tokens, look) {
  const subs = substitutions(tokens, look);
  return look.template_css.replace(/@([a-z_.]+)@/g, (_, key) => subs[key]);
}

/**
 * The theme's CSS piece. `theme` is a built-in theme's name or a custom token set (an object);
 * "" for `default`.
 */
export function themeCss(theme, look) {
  if (typeof theme !== "string") return cssFor(validateTokens(theme, look), look);
  const built = builtinTheme(look, theme);
  if (!built) throw new ThemeError(`unknown theme ${JSON.stringify(theme)}`);
  return built.generate ? cssFor(built.tokens, look) + built.extra_css : "";
}

/** card.css, then the theme's CSS, then the layout's, each non-empty piece after a newline. */
export function composeCss(look, theme = look.default_theme, nameOnPhoto = false) {
  let css = look.base_css;
  for (const piece of [themeCss(theme, look), nameOnPhoto ? look.layout_css.name_on_photo : ""]) {
    if (piece) css += "\n" + piece;
  }
  return css;
}

/** The back template for a layout (shared by every card type). */
export function backFor(look, nameOnPhoto = false) {
  return nameOnPhoto ? look.backs.name_on_photo : look.backs.default;
}

/**
 * The three note types' JSON for a theme and layout, in card-type order, as `models_for(...)`
 * serialises them: the default models with their CSS and back swapped in place. Ids, names, fields
 * and template names are copied untouched (ADR 0009).
 */
export function modelsFor(notetypes, theme = notetypes.look.default_theme, nameOnPhoto = false) {
  const css = composeCss(notetypes.look, theme, nameOnPhoto);
  const afmt = backFor(notetypes.look, nameOnPhoto);
  return notetypes.card_types.map((cardType) => {
    const json = notetypes.models[cardType].json;
    return { ...json, css, tmpls: json.tmpls.map((tmpl) => ({ ...tmpl, afmt })) };
  });
}

// --- the shareable text form (TOML), as tokens_to_toml in Python ------------------------------

/** What "Copy theme" gives and `avianki --theme-file` reads. Identical to `tokens_to_toml`. */
export function tokensToToml(tokens, look) {
  const t = validateTokens(tokens, look);
  const lines = ["# An AviAnki card theme. Use it with: avianki REGION --theme-file this-file.toml"];
  for (const key of Object.keys(look.tables)) lines.push(`${key} = "${t[key]}"`);
  for (const mode of MODES) {
    lines.push("", `[${mode}]`);
    for (const key of look.colour_keys) lines.push(`${key} = "${t[mode][key]}"`);
  }
  return lines.join("\n") + "\n";
}

// --- the look in a link: #theme=nord&photo=1 or #theme=custom&font=serif&light=...&night=... ---

/**
 * The page's look as a URL hash. `look` state is `{theme, custom, nameOnPhoto}`; `custom` holds
 * tokens and is only written when `theme` is "custom". Colours are written without the "#",
 * comma-separated in `colour_keys` order.
 */
export function lookToHash(state, look) {
  const params = new URLSearchParams();
  params.set("theme", state.theme);
  if (state.theme === "custom" && state.custom) {
    const t = validateTokens(state.custom, look);
    for (const key of Object.keys(look.tables)) params.set(key, t[key]);
    for (const mode of MODES) params.set(mode, look.colour_keys.map((k) => t[mode][k].slice(1)).join(","));
  }
  if (state.nameOnPhoto) params.set("photo", "1");
  return "#" + params.toString().replace(/%2C/g, ",");
}

/**
 * The look a hash stands for, or null when it carries none or anything in it is not allowed (a
 * bad link never half-applies). `base` supplies tokens for a custom theme that leaves some out.
 */
export function lookFromHash(hash, look) {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const theme = params.get("theme");
  if (theme === null) return null;
  const nameOnPhoto = params.get("photo") === "1";
  if (theme !== "custom") {
    return builtinTheme(look, theme) ? { theme, custom: null, nameOnPhoto } : null;
  }
  try {
    const raw = {};
    for (const key of Object.keys(look.tables)) raw[key] = params.get(key);
    for (const mode of MODES) {
      const parts = (params.get(mode) ?? "").split(",");
      if (parts.length !== look.colour_keys.length) return null;
      raw[mode] = Object.fromEntries(look.colour_keys.map((k, i) => [k, "#" + parts[i]]));
    }
    return { theme: "custom", custom: validateTokens(raw, look), nameOnPhoto };
  } catch (error) {
    if (error instanceof ThemeError) return null;
    throw error;
  }
}

/** What `buildDeck` and the preview take for the theme argument: a name, or the custom tokens. */
export function themeArgument(state) {
  return state.theme === "custom" ? state.custom : state.theme;
}
