import be from "./i18n/be.js";
import en from "./i18n/en.js";
import ru from "./i18n/ru.js";

const DICTS = { en, ru, be };
export const LANGS = Object.keys(DICTS);
const KEY = "kept.lang";

// The landing (/, /ru/, /be/) is rendered on the server in one language; its URL decides.
const pageLang = DICTS[document.documentElement.dataset.pageLang] ? document.documentElement.dataset.pageLang : null;

function savedLang() {
  try {
    const saved = localStorage.getItem(KEY);
    return saved && DICTS[saved] ? saved : null;
  } catch (_) { return null; } /* storage unavailable */
}

function inBelarus() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone === "Europe/Minsk"; } catch (_) { return false; }
}

/** Page language, then the saved choice, then the browser (Russian in Belarus → Belarusian). */
export function detectLang() {
  if (pageLang) return pageLang;
  const saved = savedLang();
  if (saved) return saved;
  const nav = (navigator.language || "en").toLowerCase();
  if (nav.startsWith("be")) return "be";
  if (nav.startsWith("ru")) return inBelarus() ? "be" : "ru";
  return "en";
}

export let lang = detectLang();
document.documentElement.lang = lang;
// Someone who came to /ru/ or /be/ from search keeps that language on the next pages.
if (pageLang && !savedLang()) {
  try { localStorage.setItem(KEY, pageLang); } catch (_) { /* ignore */ }
}

export function landingPath(code = lang) {
  return code === "en" ? "/" : `/${code}/`;
}

export function setLang(next) {
  if (!DICTS[next]) return;
  lang = next;
  try { localStorage.setItem(KEY, next); } catch (_) { /* ignore */ }
  document.documentElement.lang = next;
  window.dispatchEvent(new CustomEvent("kept:lang"));
}

function lookup(dict, path) {
  return path.split(".").reduce((acc, k) => (acc && acc[k] !== undefined ? acc[k] : undefined), dict);
}

function fill(str, vars) {
  if (!vars) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? String(vars[k]) : `{${k}}`));
}

/** t("share.items", {n: 3}) — falls back to English, then to the key itself. */
export function t(path, vars) {
  let val = lookup(DICTS[lang], path);
  if (val === undefined) val = lookup(en, path);
  if (val === undefined) return path;
  return fill(val, vars);
}

const pluralRules = Object.fromEntries(LANGS.map((code) => [code, new Intl.PluralRules(code)]));

/** tn("items", 3) — count-aware; English dictionaries can use the plain "{n} items" form. */
export function tn(key, n) {
  const forms = lookup(DICTS[lang], `plural.${key}`);
  if (forms) {
    const cat = pluralRules[lang].select(n);
    return fill(forms[cat] || forms.other, { n });
  }
  if (lang === "en") {
    const one = { items: "{n} item", claimed: "{n} reserved" }[key];
    if (n === 1 && one) return fill(one, { n });
  }
  return t(`share.${key}`, { n });
}

export function timeAgo(iso) {
  const date = new Date(iso);
  const diff = (date.getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return t("share.ago.now");
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  const units = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, secs] of units) {
    if (abs >= secs) return rtf.format(Math.round(diff / secs), unit);
  }
  return t("share.ago.now");
}
