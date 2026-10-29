import { api, getMe } from "./api.js";
import { LANGS, lang, landingPath, setLang, t } from "./i18n.js";
import { cycleTheme, getTheme } from "./theme.js";

/** el("div.card", {onclick}, child, "text") — tiny DOM builder; strings become text nodes (safe). */
export function el(spec, attrs = {}, ...children) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");
  if (attrs instanceof Node || typeof attrs === "string" || Array.isArray(attrs)) {
    children.unshift(attrs);
    attrs = {};
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k in node && k !== "list" && k !== "form") { try { node[k] = v; } catch (_) { node.setAttribute(k, v); } }
    else node.setAttribute(k, v === true ? "" : v);
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function icon(name, extra = {}) {
  return el("i", { className: `ph ph-${name}`, "aria-hidden": "true", ...extra });
}

export function initial(name) {
  return (name || "?").trim().charAt(0).toUpperCase() || "?";
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

let toastTimer;
export function toast(message) {
  document.querySelectorAll(".toast").forEach((n) => n.remove());
  const node = el("div.toast", { role: "status" }, message);
  document.body.append(node);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), 2800);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const ta = el("textarea", { value: text, style: { position: "fixed", opacity: "0" } });
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

/** Opens a modal. Returns {close, node}. `build(close)` returns the dialog's children. */
export function openDialog(build, { wide = false } = {}) {
  const backdrop = el("div.dialog-backdrop", { role: "dialog", "aria-modal": "true" });
  const box = el("div.dialog" + (wide ? ".dialog-wide" : ""));
  const close = () => {
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  append(box, [build(close)]);
  backdrop.append(box);
  document.body.append(backdrop);
  const first = box.querySelector("input, textarea, button");
  if (first) first.focus();
  return { close, node: box };
}

export function confirmDialog(message, { danger = false, okLabel } = {}) {
  return new Promise((resolve) => {
    const { close } = openDialog((closeDlg) => [
      el("p.dialog-body", message),
      el("div.dialog-actions", [
        el("button.btn.btn-secondary", { onclick: () => { closeDlg(); resolve(false); } }, t("common.cancel")),
        el("button.btn" + (danger ? ".btn-danger" : ".btn-primary"), { onclick: () => { closeDlg(); resolve(true); } }, okLabel || t("common.confirm")),
      ]),
    ]);
    void close;
  });
}

export function field({ label, hint, input, optional = false }) {
  return el("div.field", [
    label ? el("label", { htmlFor: input.id }, [label, optional ? [" ", el("span.text-muted", t("item.optional"))] : null]) : null,
    input,
    hint ? el("div.hint", hint) : null,
  ]);
}

export function stepper({ value, min = 1, max = 100000, onChange, unlimited = false, allowUnlimited = false, large = false }) {
  const state = { value, unlimited };
  const val = el("span.val");
  const minus = el("button.btn", { type: "button", "aria-label": "−" }, "−");
  const plus = el("button.btn", { type: "button", "aria-label": "+" }, "+");
  const inf = allowUnlimited ? el("button.btn", { type: "button", title: t("item.unlimited"), "aria-label": t("item.unlimited") }, "∞") : null;
  const render = () => {
    val.textContent = state.unlimited ? "∞" : String(state.value);
    minus.disabled = state.unlimited || state.value <= min;
    plus.disabled = state.unlimited || state.value >= max;
    if (inf) inf.classList.toggle("is-on", state.unlimited);
  };
  minus.addEventListener("click", () => { state.value = Math.max(min, state.value - 1); render(); onChange(state); });
  plus.addEventListener("click", () => { state.value = Math.min(max, state.value + 1); render(); onChange(state); });
  if (inf) inf.addEventListener("click", () => { state.unlimited = !state.unlimited; render(); onChange(state); });
  render();
  const node = el("div.stepper" + (large ? ".stepper-lg" : ""), [minus, val, plus, inf]);
  node.set = (v, u) => { state.value = v; state.unlimited = !!u; render(); };
  return node;
}

export function thumb(imageUrl, size = "", labelText = null) {
  const node = el("div.thumb" + (size ? `.thumb-${size}` : ""));
  if (imageUrl) node.append(el("img", { src: imageUrl, alt: "", loading: "lazy" }));
  else if (labelText) node.append(el("div.thumb-label", [icon("image"), el("span", labelText)]));
  else node.append(icon("image"));
  return node;
}

export function langSwitch() {
  const select = el("select.lang-switch", {
    "aria-label": "Language",
    onchange: () => {
      setLang(select.value);
      // The landing has one URL per language; everywhere else the page re-renders in place.
      if (document.documentElement.dataset.pageLang) location.href = landingPath(select.value);
      else location.reload();
    },
  }, LANGS.map((code) => el("option", { value: code, selected: code === lang }, code.toUpperCase())));
  return select;
}

const THEME_ICONS = { system: "circle-half", light: "sun", dark: "moon" };

/** System / light / dark, cycling on click. The choice persists and overrides the OS setting. */
export function themeSwitch() {
  const btn = el("button.btn.btn-ghost.btn-icon.theme-switch", { type: "button" });
  const render = (mode) => {
    clear(btn);
    btn.append(icon(THEME_ICONS[mode]));
    btn.title = t(`theme.${mode}`);
    btn.setAttribute("aria-label", t(`theme.${mode}`));
  };
  render(getTheme());
  btn.addEventListener("click", () => render(cycleTheme()));
  return btn;
}

/** Header bar. `active` is one of "how" | "mylists". */
export async function nav({ active = null } = {}) {
  const me = await getMe();
  const items = [];
  if (me) {
    items.push(el("a", { href: "/me", "aria-current": active === "mylists" ? "page" : null }, t("nav.mylists")));
    if (me.is_admin) items.push(el("a", { href: "/admin", "aria-current": active === "admin" ? "page" : null }, t("admin.nav")));
    items.push(el("a.hide-sm", { href: "#", onclick: async (e) => { e.preventDefault(); await api.post("/api/auth/logout"); location.href = "/"; } }, t("nav.signout")));
    items.push(el("div.avatar.avatar-sm", { title: me.display_name }, initial(me.display_name)));
  } else {
    items.push(el("a", { href: "/login" }, t("nav.signin")));
    items.push(el("a.btn.btn-secondary", { href: "/register" }, t("nav.start")));
  }
  items.push(themeSwitch(), langSwitch());
  return el("nav.nav", [el("a.nav-brand", { href: landingPath() }, [icon("bookmark-simple"), t("brand")]), ...items]);
}

export function errorText(err) {
  const d = err && err.detail;
  if (typeof d === "string") return d;
  if (d && d.code) return d.code;
  if (Array.isArray(d) && d[0] && d[0].msg) return d[0].msg;
  return t("common.error");
}

export function isUrl(text) {
  return /^https?:\/\/\S+\.\S+/i.test((text || "").trim());
}

/**
 * Pull the first link out of free text: "кружки https://shop.example/cups" → {url, rest: "кружки"}.
 * Only http(s):// and www. links count: bare domains would misfire on things like "v1.2".
 */
export function splitLinkText(text) {
  const src = (text || "").trim();
  const m = src.match(/(https?:\/\/[^\s<>"'«»]+|www\.[^\s<>"'«»]+)/i);
  if (!m) return { url: null, rest: src };
  let url = m[1].replace(/[.,;:!?)\]»]+$/, "");
  if (/^www\./i.test(url)) url = `https://${url}`;
  const rest = (src.slice(0, m.index) + " " + src.slice(m.index + m[1].length))
    .replace(/\s+/g, " ")
    .replace(/^[\s\-–—:,;]+|[\s\-–—:,;]+$/g, "")
    .trim();
  return { url, rest };
}

export function hostOf(url) {
  try { return new URL(url).host.replace(/^www\./, ""); } catch (_) { return url; }
}

export function setTitle(text) {
  document.title = text ? `${text} · Kept` : "Kept";
}
