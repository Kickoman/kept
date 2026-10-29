import { api, ApiError, getMe } from "../api.js";
import { t, tn } from "../i18n.js";
import { clear, confirmDialog, copyText, el, errorText, field, icon, nav, openDialog, setTitle, toast } from "../ui.js";

const app = document.getElementById("app");
setTitle(t("me.title"));
app.append(await nav({ active: "mylists" }));
const grid = el("div.grid-cards");
app.append(
  el("div.stack-6", { style: { marginTop: "16px" } }, [
    el("div.hstack", [
      el("h2", { style: { margin: 0 } }, t("me.title")),
      el("button.btn.btn-secondary.btn-icon.ml-auto", { title: t("profile.open"), "aria-label": t("profile.open"), onclick: () => profileDialog() }, icon("gear")),
      el("button.btn.btn-primary", { onclick: () => newListDialog() }, [icon("plus"), t("me.new")]),
    ]),
    grid,
  ]),
);

async function load() {
  const lists = await api.get("/api/wishlists");
  clear(grid);
  if (!lists.length) {
    grid.append(el("div.empty", { style: { gridColumn: "1 / -1" } }, t("me.empty")));
    return;
  }
  for (const wl of lists) grid.append(card(wl));
}

function card(wl) {
  return el("div.card.elev-sm", [
    el("a.card-title", { href: `/lists/${wl.id}/edit`, style: { color: "inherit", textDecoration: "none" } }, wl.title),
    wl.description ? el("p.card-body", wl.description) : null,
    el("div.card-meta", [tn("items", wl.item_count)]),
    el("div.card-actions", [
      el("a.btn.btn-primary", { href: `/lists/${wl.id}/edit` }, [icon("pencil-simple"), t("me.open")]),
      el("button.btn.btn-secondary", { onclick: async () => { await copyText(`${location.origin}/w/${wl.share_token}`); toast(t("edit.copied")); } }, [icon("copy"), t("me.copy")]),
      el("button.btn.btn-ghost.btn-icon.ml-auto", {
        title: t("me.delete"), "aria-label": t("me.delete"),
        onclick: async () => {
          if (!(await confirmDialog(t("me.confirm_delete", { title: wl.title }), { danger: true, okLabel: t("me.delete") }))) return;
          await api.del(`/api/wishlists/${wl.id}`);
          async function profileDialog() {
  const me = await getMe();
  const name = el("input.input", { id: "pf-name", required: true, maxLength: 80, value: me.display_name, style: { minHeight: "40px" } });
  const cur = el("input.input", { id: "pf-cur", type: "password", autocomplete: "current-password" });
  const nw = el("input.input", { id: "pf-new", type: "password", autocomplete: "new-password", minLength: 8 });
  const err1 = el("div.error.hidden");
  const err2 = el("div.error.hidden");
  openDialog((close) => [
    el("div.dialog-title", t("profile.title")),
    el("form.stack-3", { onsubmit: async (e) => {
      e.preventDefault(); err1.classList.add("hidden");
      try {
        const saved = await api.patch("/api/auth/me", { display_name: name.value.trim() });
        me.display_name = saved.display_name; toast(t("profile.saved"));
      } catch (err) { err1.textContent = errorText(err); err1.classList.remove("hidden"); }
    } }, [
      field({ label: t("profile.name"), input: name, hint: t("profile.name_hint") }),
      err1,
      el("div.dialog-actions", [el("button.btn.btn-primary", { type: "submit" }, t("profile.save"))]),
    ]),
    el("form.stack-3", { onsubmit: async (e) => {
      e.preventDefault(); err2.classList.add("hidden");
      if (nw.value.length < 8) { err2.textContent = t("profile.err_short"); err2.classList.remove("hidden"); return; }
      try {
        await api.post("/api/auth/change-password", { current_password: cur.value, new_password: nw.value }, { silent401: true });
        toast(t("profile.password_changed")); close();
      } catch (err) {
        err2.textContent = err instanceof ApiError && err.status === 401 ? t("profile.err_wrong") : errorText(err);
        err2.classList.remove("hidden");
      }
    } }, [
      el("div.dialog-title", { style: { fontSize: "16px", marginTop: "8px" } }, t("profile.change_password")),
      field({ label: t("profile.current"), input: cur }),
      field({ label: t("profile.new"), input: nw }),
      err2,
      el("div.dialog-actions", [
        el("button.btn.btn-secondary", { type: "button", onclick: close }, t("common.close")),
        el("button.btn.btn-primary", { type: "submit" }, t("profile.change_password")),
      ]),
    ]),
  ]);
}

load();
        },
      }, icon("trash")),
    ]),
  ]);
}

function newListDialog() {
  const title = el("input.input", { id: "nl-title", required: true, maxLength: 120, placeholder: t("me.title_ph"), style: { minHeight: "40px" } });
  const desc = el("textarea.input", { id: "nl-desc", maxLength: 2000, placeholder: t("me.desc_ph") });
  const error = el("div.error.hidden");
  openDialog((close) => [
    el("div.dialog-title", t("me.new_title")),
    el("form.stack-3", {
      onsubmit: async (e) => {
        e.preventDefault();
        try {
          const wl = await api.post("/api/wishlists", { title: title.value.trim(), description: desc.value.trim() });
          close();
          location.href = `/lists/${wl.id}/edit`;
        } catch (err) {
          error.textContent = errorText(err);
          error.classList.remove("hidden");
        }
      },
    }, [
      field({ label: t("me.list_title"), input: title }),
      field({ label: t("me.list_desc"), input: desc, hint: t("me.list_desc_hint"), optional: true }),
      error,
      el("div.dialog-actions", [
        el("button.btn.btn-secondary", { type: "button", onclick: close }, t("common.cancel")),
        el("button.btn.btn-primary", { type: "submit" }, t("me.create")),
      ]),
    ]),
  ]);
}

async function profileDialog() {
  const me = await getMe();
  const name = el("input.input", { id: "pf-name", required: true, maxLength: 80, value: me.display_name, style: { minHeight: "40px" } });
  const cur = el("input.input", { id: "pf-cur", type: "password", autocomplete: "current-password" });
  const nw = el("input.input", { id: "pf-new", type: "password", autocomplete: "new-password", minLength: 8 });
  const err1 = el("div.error.hidden");
  const err2 = el("div.error.hidden");
  openDialog((close) => [
    el("div.dialog-title", t("profile.title")),
    el("form.stack-3", { onsubmit: async (e) => {
      e.preventDefault(); err1.classList.add("hidden");
      try {
        const saved = await api.patch("/api/auth/me", { display_name: name.value.trim() });
        me.display_name = saved.display_name; toast(t("profile.saved"));
      } catch (err) { err1.textContent = errorText(err); err1.classList.remove("hidden"); }
    } }, [
      field({ label: t("profile.name"), input: name, hint: t("profile.name_hint") }),
      err1,
      el("div.dialog-actions", [el("button.btn.btn-primary", { type: "submit" }, t("profile.save"))]),
    ]),
    el("form.stack-3", { onsubmit: async (e) => {
      e.preventDefault(); err2.classList.add("hidden");
      if (nw.value.length < 8) { err2.textContent = t("profile.err_short"); err2.classList.remove("hidden"); return; }
      try {
        await api.post("/api/auth/change-password", { current_password: cur.value, new_password: nw.value }, { silent401: true });
        toast(t("profile.password_changed")); close();
      } catch (err) {
        err2.textContent = err instanceof ApiError && err.status === 401 ? t("profile.err_wrong") : errorText(err);
        err2.classList.remove("hidden");
      }
    } }, [
      el("div.dialog-title", { style: { fontSize: "16px", marginTop: "8px" } }, t("profile.change_password")),
      field({ label: t("profile.current"), input: cur }),
      field({ label: t("profile.new"), input: nw }),
      err2,
      el("div.dialog-actions", [
        el("button.btn.btn-secondary", { type: "button", onclick: close }, t("common.close")),
        el("button.btn.btn-primary", { type: "submit" }, t("profile.change_password")),
      ]),
    ]),
  ]);
}

load();
