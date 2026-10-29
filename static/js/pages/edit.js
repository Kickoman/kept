import { api } from "../api.js";
import { t, timeAgo, tn } from "../i18n.js";
import { clear, confirmDialog, copyText, el, errorText, field, icon, nav, openDialog, setTitle, stepper, thumb, toast } from "../ui.js";
import { openItemDialog } from "./_item_dialog.js";

const app = document.getElementById("app");
const id = Number((location.pathname.match(/\/lists\/(\d+)\/edit/) || [])[1]);
let wl = null;

app.append(await nav({ active: "mylists" }));
const head = el("div.page-head");
const shareBox = el("div.share-box");
const addInput = el("input.input", { placeholder: t("edit.paste_ph"), "aria-label": t("edit.paste_ph"),
  onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); openAdd(); } } });
const rows = el("div.rows");
const emptyBox = el("div.empty.hidden", t("edit.empty"));
app.append(
  el("div.stack-6", { style: { marginTop: "8px" } }, [
    el("a.back", { href: "/me" }, [icon("arrow-left"), t("edit.back")]),
    head,
    el("div.linkbar", [icon("link"), addInput, el("button.btn.btn-primary", { style: { minHeight: "40px" }, onclick: openAdd }, [icon("plus"), t("edit.add")])]),
    rows,
    emptyBox,
  ]),
);

const shareLink = () => `${location.origin}/w/${wl.share_token}`;

async function load() {
  wl = await api.get(`/api/wishlists/${id}`);
  setTitle(wl.title);
  renderHead();
  renderRows();
}

function renderHead() {
  clear(head);
  head.append(
    el("div.intro", [
      el("div.hstack", [
        el("h2", { style: { fontSize: "32px" } }, wl.title),
        el("button.btn.btn-ghost.btn-icon", { "aria-label": t("edit.rename"), title: t("edit.rename"), onclick: renameDialog }, icon("pencil-simple")),
      ]),
      wl.description ? el("p.lede", { style: { fontSize: "14px" } }, wl.description) : null,
      el("div.meta", [tn("items", wl.items.length)]),
    ]),
    shareBox,
  );
  shareBox.classList.add("ml-auto");
  shareBox.replaceChildren(
    el("div.input", { title: shareLink() }, [icon("link-simple", { style: { fontSize: "15px", flex: "none" } }), shareLink().replace(/^https?:\/\//, "")]),
    el("button.btn.btn-primary", { style: { minHeight: "40px" }, onclick: async () => { await copyText(shareLink()); toast(t("edit.copied")); } }, [icon("copy"), t("edit.copy")]),
    el("button.btn.btn-secondary.btn-icon", { style: { height: "40px", width: "40px" }, title: t("edit.newlink"), "aria-label": t("edit.newlink"), onclick: async () => {
      if (!(await confirmDialog(t("edit.newlink_confirm"), { danger: true, okLabel: t("edit.newlink") }))) return;
      const res = await api.post(`/api/wishlists/${id}/regenerate-token`);
      wl.share_token = res.share_token;
      renderHead();
    } }, icon("arrows-clockwise")),
  );
}

function renderRows() {
  clear(rows);
  emptyBox.classList.toggle("hidden", wl.items.length > 0);
  wl.items.forEach((item, idx) => rows.append(row(item, idx)));
}

const patchTimers = new Map();
function patchQuantity(item, s) {
  clearTimeout(patchTimers.get(item.id));
  patchTimers.set(item.id, setTimeout(async () => {
    try {
      const body = s.unlimited ? { unlimited: true } : { unlimited: false, quantity: s.value };
      const saved = await api.patch(`/api/items/${item.id}`, body);
      Object.assign(item, saved);
    } catch (err) { toast(errorText(err)); }
  }, 350));
}

function row(item, idx) {
  const node = el("div.row.edit-row", { draggable: true, dataset: { id: item.id } }, [
    icon("dots-six-vertical", { className: "ph ph-dots-six-vertical drag-handle" }),
    el("div.move-btns", [
      el("button.btn", { "aria-label": t("edit.move_up"), disabled: idx === 0, onclick: () => move(idx, idx - 1) }, icon("caret-up")),
      el("button.btn", { "aria-label": t("edit.move_down"), disabled: idx === wl.items.length - 1, onclick: () => move(idx, idx + 1) }, icon("caret-down")),
    ]),
    thumb(item.image_url, "sm"),
    el("div.row-main.row-clickable", { onclick: () => openEdit(item) }, [
      el("div.row-title", item.title),
      el("div.row-sub", item.description || `${t("share.added")} ${timeAgo(item.created_at)}`),
    ]),
    stepper({ value: item.quantity ?? 1, unlimited: item.quantity === null, allowUnlimited: true, onChange: (s) => patchQuantity(item, s) }),
    el("div.row-actions", [
      el("button.btn.btn-secondary.btn-icon", { "aria-label": t("edit.edit_item"), title: t("edit.edit_item"), onclick: () => openEdit(item) }, icon("pencil-simple")),
      el("button.btn.btn-secondary.btn-icon", { "aria-label": t("edit.remove_item"), title: t("edit.remove_item"), onclick: async () => {
        if (!(await confirmDialog(t("edit.confirm_remove", { title: item.title }), { danger: true, okLabel: t("edit.remove_item") }))) return;
        await api.del(`/api/items/${item.id}`);
        wl.items = wl.items.filter((i) => i.id !== item.id);
        renderHead(); renderRows();
      } }, icon("trash")),
    ]),
  ]);
  // drag & drop reorder
  node.addEventListener("dragstart", (e) => { dragId = item.id; node.classList.add("is-dragging"); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", String(item.id)); } catch (_) {} });
  node.addEventListener("dragend", () => { node.classList.remove("is-dragging"); rows.querySelectorAll(".is-over").forEach((n) => n.classList.remove("is-over")); });
  node.addEventListener("dragover", (e) => { if (dragId === null || dragId === item.id) return; e.preventDefault(); node.classList.add("is-over"); });
  node.addEventListener("dragleave", () => node.classList.remove("is-over"));
  node.addEventListener("drop", (e) => {
    e.preventDefault();
    if (dragId === null || dragId === item.id) return;
    const from = wl.items.findIndex((i) => i.id === dragId);
    const to = wl.items.findIndex((i) => i.id === item.id);
    dragId = null;
    move(from, to);
  });
  return node;
}
let dragId = null;

async function move(from, to) {
  if (to < 0 || to >= wl.items.length || from === to) return;
  const [moved] = wl.items.splice(from, 1);
  wl.items.splice(to, 0, moved);
  renderRows();
  try {
    wl.items = await api.put(`/api/wishlists/${id}/items/order`, { item_ids: wl.items.map((i) => i.id) });
  } catch (err) { toast(errorText(err)); load(); }
}

function openAdd() {
  const text = addInput.value.trim();
  addInput.value = "";
  openItemDialog({ wishlist: wl, initialText: text, onSaved: (item) => { wl.items.push(item); renderHead(); renderRows(); } });
}

function openEdit(item) {
  openItemDialog({ wishlist: wl, item, onSaved: (saved) => { Object.assign(item, saved); renderRows(); } });
}

function renameDialog() {
  const title = el("input.input", { id: "rn-title", required: true, maxLength: 120, value: wl.title, style: { minHeight: "40px" } });
  const desc = el("textarea.input", { id: "rn-desc", maxLength: 2000, value: wl.description });
  openDialog((close) => [
    el("div.dialog-title", t("edit.settings")),
    el("form.stack-3", { onsubmit: async (e) => {
      e.preventDefault();
      const saved = await api.patch(`/api/wishlists/${id}`, { title: title.value.trim(), description: desc.value.trim() });
      wl.title = saved.title; wl.description = saved.description;
      close(); setTitle(wl.title); renderHead();
    } }, [
      field({ label: t("me.list_title"), input: title }),
      field({ label: t("me.list_desc"), input: desc, hint: t("me.list_desc_hint"), optional: true }),
      el("div.dialog-actions", [
        el("button.btn.btn-secondary", { type: "button", onclick: close }, t("common.cancel")),
        el("button.btn.btn-primary", { type: "submit" }, t("edit.save")),
      ]),
    ]),
  ]);
}

load();
