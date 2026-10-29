import { api, ApiError, getMe } from "../api.js";
import { landingPath, t, timeAgo, tn } from "../i18n.js";
import { clear, el, errorText, field, icon, initial, nav, openDialog, setTitle, stepper, thumb, toast } from "../ui.js";

const app = document.getElementById("app");
const token = decodeURIComponent((location.pathname.split("/w/")[1] || "").split("/")[0]);
const PENDING_KEY = "kept.pendingClaim";

let data = null;
let filter = "all";
const me = await getMe();

function loadPending() {
  try { return JSON.parse(localStorage.getItem(PENDING_KEY) || "null"); } catch (_) { return null; }
}
function savePending(p) {
  try { if (p) localStorage.setItem(PENDING_KEY, JSON.stringify(p)); else localStorage.removeItem(PENDING_KEY); } catch (_) { /* ignore */ }
}

app.append(await nav());
const main = el("div.stack", { style: { marginTop: "8px" } });
app.append(main);

async function load() {
  try {
    data = await api.get(`/api/w/${encodeURIComponent(token)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return renderNotFound();
    throw err;
  }
  setTitle(data.title);
  render();
  await finishPendingClaim();
}

// Keep the list fresh without a manual reload: Safari restores the page from bfcache on "back" and
// when returning from another app, so a claim made elsewhere would otherwise stay invisible.
let lastRefresh = Date.now();
async function refresh(reason) {
  if (!data || document.visibilityState !== "visible") return;
  // focus follows visibilitychange, and the timer may fire right after either: debounce those two only;
  // a real return to the page always refetches.
  if ((reason === "focus" || reason === "timer") && Date.now() - lastRefresh < 5000) return;
  lastRefresh = Date.now();
  try {
    const fresh = await api.get(`/api/w/${encodeURIComponent(token)}`);
    if (JSON.stringify(fresh) !== JSON.stringify(data)) { data = fresh; render(); }
  } catch (_) { /* transient; the next signal will retry */ }
}
window.addEventListener("pageshow", (e) => { if (e.persisted) refresh("pageshow"); });
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh("visible"); });
window.addEventListener("focus", () => refresh("focus"));
setInterval(() => refresh("timer"), 60000);

// A guest who clicked "Claim" before signing in comes back here after login/registration:
// the claim they filled in is placed right away, no second click needed.
async function finishPendingClaim() {
  const pending = loadPending();
  if (!pending || pending.token !== token) return;
  if (!me) return; // came back without signing in; keep it for the next visit
  savePending(null);
  const item = data.items.find((i) => i.id === pending.item_id);
  if (!item || item.available === 0) return;
  try {
    await api.post(`/api/w/${encodeURIComponent(token)}/items/${pending.item_id}/bookings`, { quantity: pending.quantity || 1, note: pending.note || "" });
    toast(t("share.claimed_after_login"));
    data = await api.get(`/api/w/${encodeURIComponent(token)}`);
    render();
  } catch (err) {
    toast(claimErrorText(err));
  }
}

function claimErrorText(err) {
  if (err instanceof ApiError && err.status === 409 && err.detail && err.detail.code === "not_enough") return t("share.err_not_enough", { n: err.detail.available });
  if (err instanceof ApiError && err.status === 403) return t("share.owner_cannot");
  return errorText(err);
}

function renderNotFound() {
  clear(main);
  main.append(el("div.empty", [el("h3", t("share.notfound")), el("p", t("share.notfound_text")), el("a.btn.btn-primary", { href: "/" }, t("share.home"))]));
}

const isFull = (it) => it.available === 0;
const hasClaims = (it) => it.booked_qty > 0;
const mine = (it) => it.bookings; // the API returns only the viewer's own bookings

function render() {
  clear(main);
  const items = data.items;
  const claimedCount = items.filter(hasClaims).length;
  const availableCount = items.filter((it) => !isFull(it)).length;
  const fullCount = items.filter(isFull).length;

  if (data.is_owner) main.append(el("div.banner", [icon("eye-slash"), t("share.owner_banner")]));

  main.append(
    el("div.page-head", [
      el("div.intro", [
        el("div.kicker", t("share.kicker")),
        el("h2", data.title),
        data.description ? el("p.lede", data.description) : null,
        el("div.meta", [tn("items", items.length), el("span", "·"), tn("claimed", claimedCount), el("span", "·"), t("share.updated", { when: timeAgo(data.updated_at) })]),
      ]),
      el("div.owner-badge", [el("div.avatar.avatar-lg", initial(data.owner_name)), el("span", data.owner_name)]),
    ]),
  );

  const seg = el("div.seg", [
    segOpt("all", `${t("share.all")} ${items.length}`),
    segOpt("available", `${t("share.available")} ${availableCount}`),
    segOpt("claimed", `${t("share.taken")} ${fullCount}`),
  ]);
  main.append(el("div.hstack", { style: { flexWrap: "wrap", gap: "var(--space-4)" } }, [seg]));

  const visible = items.filter((it) => filter === "all" || (filter === "available" ? !isFull(it) : isFull(it)));
  if (!items.length) main.append(el("div.empty", t("share.empty")));
  else main.append(el("div.rows", visible.map(row)));
  main.append(el("p.made-with", el("a", { href: landingPath() }, t("share.make_own"))));
}

function segOpt(value, label) {
  return el("label.seg-opt", [el("input", { type: "radio", name: "filter", checked: filter === value, onchange: () => { filter = value; render(); } }), label]);
}

function qtyLabel(it) {
  if (it.quantity === null) return t("share.unlimited");
  if (it.quantity === 1) return "×1";
  return it.booked_qty > 0 ? t("share.of", { k: it.booked_qty, n: it.quantity }) : `×${it.quantity}`;
}

function subText(it) {
  const own = mine(it);
  if (!it.booked_qty) return it.description;
  const parts = [];
  if (own.length) parts.push(it.my_qty > 1 ? `${t("share.by_you")} ×${it.my_qty}` : t("share.by_you"));
  if (isFull(it)) { if (!own.length || it.booked_qty > it.my_qty) parts.push(t("share.claimed_tag")); }
  else if (it.quantity !== null) parts.push(t("share.detail_partial", { k: it.booked_qty, n: it.quantity }));
  else parts.push(t("share.claimed_n", { n: it.booked_qty }));
  if (own.length) parts.push(timeAgo(own[own.length - 1].created_at));
  return parts.join(" · ");
}

function actionFor(it, { block = false } = {}) {
  const own = mine(it);
  if (isFull(it)) {
    if (own.length) return el("button.btn.btn-ghost", { style: { minWidth: "92px" }, onclick: (e) => { e.stopPropagation(); undo(own[0]); } }, [icon("arrow-counter-clockwise"), t("share.undo")]);
    return el("span.tag.tag-neutral", { style: { minWidth: "92px", justifyContent: "center" } }, t("share.claimed_tag"));
  }
  if (data.is_owner) return el("span.tag.tag-outline", { style: { minWidth: "92px", justifyContent: "center" } }, t("share.available"));
  const label = it.quantity !== null && it.quantity > 1 ? t("share.claim_one") : t("share.claim");
  return el("button.btn.btn-primary.btn-claim" + (block ? ".btn-block.btn-lg" : ""), { onclick: (e) => { e.stopPropagation(); openClaim(it); } }, label);
}

function row(it) {
  const own = mine(it);
  return el("div.row" + (isFull(it) ? ".is-claimed" : ""), [
    el("div.thumb.row-clickable", { onclick: () => detailDialog(it) }, it.image_url ? el("img", { src: it.image_url, alt: "", loading: "lazy" }) : icon("image")),
    el("div.row-main.row-clickable", { onclick: () => detailDialog(it) }, [
      el("div.row-title", it.title),
      el("div.row-sub" + (own.length ? ".claimed-by-you" : ""), subText(it)),
    ]),
    el("span.row-qty", qtyLabel(it)),
    actionFor(it),
  ]);
}

function statusKicker(it) {
  if (isFull(it)) return t("share.detail_claimed");
  if (it.quantity !== null && it.booked_qty > 0) return t("share.detail_partial", { k: it.booked_qty, n: it.quantity });
  return t("share.detail_available");
}

function detailDialog(it) {
  const own = mine(it);
  openDialog((close) => [
    el("a.back", { href: "#", onclick: (e) => { e.preventDefault(); close(); } }, [icon("arrow-left"), data.title]),
    el("div.detail", [
      thumb(it.image_url, "lg", t("item.no_image")),
      el("div.detail-side", [
        el("div", [el("div.kicker", { style: { marginBottom: "6px" } }, statusKicker(it)), el("h3", { style: { margin: 0 } }, it.title)]),
        it.description ? el("p.quote", it.description) : null,
        el("div.facts", [
          el("div", [el("span", t("share.wanted")), el("span", it.quantity === null ? "∞" : String(it.quantity))]),
          el("div", [el("span", t("share.claimed_so_far")), el("span", it.quantity === null ? String(it.booked_qty) : t("share.of", { k: it.booked_qty, n: it.quantity }))]),
          el("div", [el("span", t("share.added")), el("span", timeAgo(it.created_at))]),
        ]),
        own.length ? el("div.stack-2", own.map((b) => el("div.note.claimed-by-you", [icon("check"), `${t("share.by_you")}${b.quantity > 1 ? ` ×${b.quantity}` : ""}${b.note ? ` — ${b.note}` : ""}`]))) : null,
        it.url ? el("a", { href: it.url, target: "_blank", rel: "noopener noreferrer nofollow", style: { fontSize: "13px" } }, [t("share.open_link"), " ", icon("arrow-square-out")]) : null,
        el("div.stack-3", { style: { marginTop: "auto" } }, [
          (() => { const a = actionFor(it, { block: true }); a.addEventListener("click", () => setTimeout(close, 0)); return a; })(),
          own.length && !isFull(it) ? el("button.btn.btn-ghost", { onclick: () => { close(); undo(own[0]); } }, [icon("arrow-counter-clockwise"), t("share.undo")]) : null,
        ]),
      ]),
    ]),
  ], { wide: true });
}

// Re-read the list right before claiming: the row may be minutes old.
async function openClaim(it) {
  try {
    data = await api.get(`/api/w/${encodeURIComponent(token)}`);
    render();
  } catch (_) { /* fall back to what we have; the server validates anyway */ }
  const fresh = data.items.find((i) => i.id === it.id);
  if (!fresh) { toast(t("share.err_gone")); return; }
  if (fresh.available === 0) { toast(t("share.already_taken")); return; }
  claimDialog(fresh);
}

function claimDialog(it) {
  const maxQty = it.available === null ? 100 : it.available;
  const note = el("textarea.input", { id: "cl-note", maxLength: 500, placeholder: t("share.note_ph"), style: { minHeight: "64px" } });
  const error = el("div.error.hidden");
  let qty = 1;
  const qtyControl = maxQty > 1 ? stepper({ value: 1, min: 1, max: maxQty, large: true, onChange: (s) => { qty = s.value; } }) : null;
  openDialog((close) => [
    el("div.hstack", [thumb(it.image_url), el("div", [el("div.dialog-title", { style: { fontSize: "17px" } }, it.title), el("div.text-muted", { style: { fontSize: "12px" } }, statusKicker(it))])]),
    it.description ? el("p.quote", { style: { fontSize: "13px" } }, it.description) : null,
    me ? null : el("div.banner", [icon("sign-in"), t("share.login_to_claim")]),
    el("form.stack-3", { onsubmit: async (e) => {
      e.preventDefault();
      error.classList.add("hidden");
      if (!me) {
        savePending({ token, item_id: it.id, quantity: qty, note: note.value.trim() });
        location.href = `/login?next=${encodeURIComponent(`/w/${token}`)}`;
        return;
      }
      try {
        await api.post(`/api/w/${encodeURIComponent(token)}/items/${it.id}/bookings`, { quantity: qty, note: note.value.trim() });
        close();
        toast(t("share.claimed_ok"));
        await load();
      } catch (err) {
        error.textContent = claimErrorText(err); error.classList.remove("hidden");
        if (err instanceof ApiError && err.status === 409) await load();
      }
    } }, [
      qtyControl ? el("div.field", [el("label", t("share.how_many")), qtyControl]) : null,
      field({ label: t("share.note_self"), input: note, optional: true }),
      error,
      el("div.dialog-actions", [
        el("button.btn.btn-secondary", { type: "button", onclick: close }, t("common.cancel")),
        el("button.btn.btn-primary.btn-lg", { type: "submit" }, me ? t("share.claim_btn") : t("share.login_and_claim")),
      ]),
    ]),
  ]);
}

async function undo(booking) {
  try {
    await api.del(`/api/bookings/${booking.id}`);
    toast(t("share.undone"));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) toast(t("share.err_gone"));
    else toast(errorText(err));
  }
  await load();
}

load();
