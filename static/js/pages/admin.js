import { api, ApiError, getMe } from "../api.js";
import { lang, t, timeAgo } from "../i18n.js";
import { clear, confirmDialog, el, errorText, field, icon, nav, openDialog, setTitle, stepper, thumb, toast } from "../ui.js";

const app = document.getElementById("app");
setTitle(t("admin.title"));
const me = await getMe();
app.append(await nav({ active: "admin" }));
if (!me || !me.is_admin) {
  app.append(el("div.empty", { style: { marginTop: "48px" } }, t("admin.forbidden")));
} else {
  await main();
}

async function main() {

  const state = { section: "users", q: "", page: 1, filter: {} };
  const statsBox = el("div.grid-stats");
  const search = el("input.input", { placeholder: t("admin.search_ph"), oninput: debounce(() => { state.q = search.value; state.page = 1; load(); }, 300) });
  const chip = el("span.filter-chip.hidden");
  const pager = el("div.pager");
  const tableWrap = el("div.table-wrap");
  const seg = el("div.seg");

  app.append(
    el("div.stack-6", { style: { marginTop: "8px" } }, [
      el("h2", { style: { margin: 0 } }, t("admin.title")),
      statsBox,
      el("div.admin-toolbar", [seg, search, chip, pager]),
      tableWrap,
    ]),
  );

  function debounce(fn, ms) { let tm; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; }
  const fmtDate = (iso) => iso ? new Date(iso).toLocaleString(lang, { dateStyle: "short", timeStyle: "short" }) : "—";
  const qtyText = (q) => q === null ? t("admin.unlimited") : String(q);

  function renderSeg() {
    clear(seg);
    for (const s of ["users", "wishlists", "items", "bookings", "ai"]) {
      seg.append(el("label.seg-opt", [el("input", { type: "radio", name: "section", checked: state.section === s, onchange: () => setSection(s) }), t(`admin.${s}`)]));
    }
  }
  function setSection(s, filter = {}) {
    state.section = s; state.filter = filter; state.page = 1; state.q = ""; search.value = "";
    renderSeg(); renderChip(); load();
  }
  function renderChip() {
    clear(chip);
    const f = state.filter;
    const label = f.user_id ? t("admin.filter_user", { id: f.user_id }) : f.wishlist_id ? t("admin.filter_list", { id: f.wishlist_id }) : f.item_id ? `#${f.item_id}` : null;
    chip.classList.toggle("hidden", !label);
    if (label) chip.append(el("span.tag.tag-outline", label), el("button.btn.btn-ghost", { onclick: () => setSection(state.section) }, t("admin.clear")));
  }

  async function loadStats() {
    const s = await api.get("/api/admin/stats");
    clear(statsBox);
    const cards = [["users", s.users, t("admin.sub_7d", { n: s.users_7d })], ["wishlists", s.wishlists, t("admin.sub_7d", { n: s.wishlists_7d })], ["items", s.items, t("admin.sub_24h", { n: s.items_24h })], ["bookings", s.bookings, t("admin.sub_24h", { n: s.bookings_24h })]];
    for (const [k, v, sub] of cards) statsBox.append(el("div.card.elev-sm", { onclick: () => setSection(k), style: { cursor: "pointer" } }, [el("div.card-kicker", t(`admin.stat_${k}`)), el("div.value", String(v)), el("div.sub", sub)]));
  }

  async function load() {
    const isAi = state.section === "ai";
    search.classList.toggle("hidden", isAi); chip.classList.toggle("hidden", isAi || chip.classList.contains("hidden")); pager.classList.toggle("hidden", isAi);
    if (isAi) { clear(tableWrap); tableWrap.append(await aiSettingsPanel()); return; }
    const params = new URLSearchParams({ q: state.q, page: String(state.page), per_page: "50", ...Object.fromEntries(Object.entries(state.filter).map(([k, v]) => [k, String(v)])) });
    const data = await api.get(`/api/admin/${state.section}?${params}`);
    clear(pager);
    pager.append(
      el("span", t("admin.total", { n: data.total })),
      el("button.btn.btn-ghost.btn-icon", { disabled: state.page <= 1, onclick: () => { state.page--; load(); } }, icon("caret-left")),
      el("span", t("admin.page", { p: state.page })),
      el("button.btn.btn-ghost.btn-icon", { disabled: state.page * data.per_page >= data.total, onclick: () => { state.page++; load(); } }, icon("caret-right")),
    );
    clear(tableWrap);
    if (!data.items.length) { tableWrap.append(el("div.empty", t("admin.empty"))); return; }
    tableWrap.append(TABLES[state.section](data.items));
  }

  const iconBtn = (name, title, onclick, danger = false) => el("button.btn.btn-secondary.btn-icon" + (danger ? ".btn-danger" : ""), { title, "aria-label": title, onclick }, icon(name));
  const th = (...labels) => el("thead", el("tr", labels.map((l) => el("th", { className: typeof l === "object" ? l.cls : "" }, typeof l === "object" ? l.text : l))));

  async function act(fn, okMsg) {
    try { await fn(); if (okMsg) toast(okMsg); await Promise.all([load(), loadStats()]); }
    catch (err) {
      const d = err instanceof ApiError ? err.detail : null;
      toast(d === "last_admin" ? t("admin.err_last_admin") : d === "self_delete" ? t("admin.err_self_delete") : errorText(err));
    }
  }

  const TABLES = {
    users(rows) {
      return el("table.table", [
        th(t("admin.col_user"), t("admin.col_name"), t("admin.col_registered"), t("admin.col_last_seen"), { text: t("admin.col_lists"), cls: "num" }, { text: t("admin.col_items"), cls: "num" }, { text: t("admin.col_claims"), cls: "num" }, { text: t("admin.col_sessions"), cls: "num" }, ""),
        el("tbody", rows.map((u) => el("tr", [
          el("td", [u.username, u.is_admin ? [" ", el("span.tag.tag-accent", t("admin.badge_admin"))] : null]),
          el("td.ellipsis", u.display_name),
          el("td.muted", { title: fmtDate(u.created_at) }, timeAgo(u.created_at)),
          el("td.muted", { title: fmtDate(u.last_seen) }, u.last_seen ? timeAgo(u.last_seen) : "—"),
          el("td.num.link", { onclick: () => setSection("wishlists", { user_id: u.id }) }, String(u.wishlists)),
          el("td.num.link", { onclick: () => setSection("items", { user_id: u.id }) }, String(u.items)),
          el("td.num", String(u.bookings_received)),
          el("td.num", String(u.sessions)),
          el("td.actions", [
            iconBtn("pencil-simple", t("admin.act_edit"), () => editUser(u)),
            iconBtn(u.is_admin ? "shield-slash" : "shield-check", u.is_admin ? t("admin.act_revoke") : t("admin.act_grant"), () => act(() => api.patch(`/api/admin/users/${u.id}`, { is_admin: !u.is_admin }), t("admin.done"))),
            iconBtn("key", t("admin.act_reset"), async () => { if (await confirmDialog(t("admin.confirm_reset", { name: u.username }))) act(async () => { const r = await api.post(`/api/admin/users/${u.id}/reset-password`); showPassword(r); }); }),
            iconBtn("sign-out", t("admin.act_logout"), async () => { if (await confirmDialog(t("admin.confirm_logout", { name: u.username }))) act(() => api.post(`/api/admin/users/${u.id}/logout`), t("admin.done")); }),
            iconBtn("trash", t("admin.act_delete"), async () => { if (await confirmDialog(t("admin.confirm_delete_user", { name: u.username }), { danger: true, okLabel: t("admin.act_delete") })) act(() => api.del(`/api/admin/users/${u.id}`), t("admin.deleted")); }, true),
          ]),
        ]))),
      ]);
    },
    wishlists(rows) {
      return el("table.table", [
        th("#", t("admin.col_title"), t("admin.col_owner"), { text: t("admin.col_items"), cls: "num" }, { text: t("admin.col_claims"), cls: "num" }, t("admin.col_updated"), ""),
        el("tbody", rows.map((w) => el("tr", [
          el("td.muted", String(w.id)),
          el("td.ellipsis.link", { onclick: () => wishlistDetail(w.id), title: w.description }, w.title),
          el("td.link", { onclick: () => setSection("users"), title: `#${w.owner_id}` }, w.owner_username),
          el("td.num.link", { onclick: () => setSection("items", { wishlist_id: w.id }) }, String(w.item_count)),
          el("td.num.link", { onclick: () => setSection("bookings", { wishlist_id: w.id }) }, String(w.booking_count)),
          el("td.muted", { title: fmtDate(w.updated_at) }, timeAgo(w.updated_at)),
          el("td.actions", [
            el("a.btn.btn-secondary.btn-icon", { href: w.share_url, target: "_blank", rel: "noopener", title: t("admin.act_open") }, icon("arrow-square-out")),
            iconBtn("list-bullets", t("admin.act_detail"), () => wishlistDetail(w.id)),
            iconBtn("pencil-simple", t("admin.act_edit"), () => editWishlist(w)),
            iconBtn("trash", t("admin.act_delete"), async () => { if (await confirmDialog(t("admin.confirm_delete_list", { title: w.title }), { danger: true, okLabel: t("admin.act_delete") })) act(() => api.del(`/api/admin/wishlists/${w.id}`), t("admin.deleted")); }, true),
          ]),
        ]))),
      ]);
    },
    items(rows) {
      return el("table.table", [
        th("", t("admin.col_title"), t("admin.col_list"), t("admin.col_owner"), { text: t("admin.col_qty"), cls: "num" }, { text: t("admin.col_booked"), cls: "num" }, t("admin.col_created"), ""),
        el("tbody", rows.map((it) => el("tr", [
          el("td", thumb(it.image_url, "sm")),
          el("td.ellipsis", { title: it.description }, [it.title, it.url ? [" ", el("a", { href: it.url, target: "_blank", rel: "noopener noreferrer nofollow" }, icon("link-simple"))] : null]),
          el("td.ellipsis.link", { onclick: () => wishlistDetail(it.wishlist_id) }, it.wishlist_title),
          el("td", it.owner_username),
          el("td.num", qtyText(it.quantity)),
          el("td.num.link", { onclick: () => setSection("bookings", { item_id: it.id }) }, String(it.booked_qty)),
          el("td.muted", { title: fmtDate(it.created_at) }, timeAgo(it.created_at)),
          el("td.actions", [
            iconBtn("pencil-simple", t("admin.act_edit"), () => editItem(it)),
            iconBtn("trash", t("admin.act_delete"), async () => { if (await confirmDialog(t("admin.confirm_delete_item", { title: it.title }), { danger: true, okLabel: t("admin.act_delete") })) act(() => api.del(`/api/admin/items/${it.id}`), t("admin.deleted")); }, true),
          ]),
        ]))),
      ]);
    },
    bookings(rows) {
      return el("table.table", [
        th(t("admin.col_guest"), { text: t("admin.col_qty"), cls: "num" }, t("admin.col_item"), t("admin.col_list"), t("admin.col_owner"), t("admin.col_note"), t("admin.col_created"), ""),
        el("tbody", rows.map((b) => el("tr", [
          el("td", b.booker_name),
          el("td.num", String(b.quantity)),
          el("td.ellipsis", b.item_title),
          el("td.ellipsis.link", { onclick: () => wishlistDetail(b.wishlist_id) }, b.wishlist_title),
          el("td", b.owner_username),
          el("td.ellipsis.muted", { title: b.note }, b.note),
          el("td.muted", { title: fmtDate(b.created_at) }, timeAgo(b.created_at)),
          el("td.actions", [iconBtn("trash", t("admin.act_delete"), async () => { if (await confirmDialog(t("admin.confirm_delete_booking", { name: b.booker_name }), { danger: true, okLabel: t("admin.act_delete") })) act(() => api.del(`/api/admin/bookings/${b.id}`), t("admin.deleted")); }, true)]),
        ]))),
      ]);
    },
  };

  function showPassword(r) {
    openDialog((close) => [
      el("div.dialog-title", t("admin.new_password", { name: r.username })),
      el("div.input", { style: { fontFamily: "monospace", fontSize: "16px", userSelect: "all" } }, r.password),
      el("p.dialog-body", t("admin.new_password_hint")),
      el("div.dialog-actions", [el("button.btn.btn-primary", { onclick: close }, t("common.ok"))]),
    ]);
  }

  function formDialog(title, fields, onSubmit) {
    const error = el("div.error.hidden");
    openDialog((close) => [
      el("div.dialog-title", title),
      el("form.stack-3", { onsubmit: async (e) => {
        e.preventDefault();
        try { await onSubmit(); close(); toast(t("admin.done")); await Promise.all([load(), loadStats()]); }
        catch (err) { error.textContent = errorText(err); error.classList.remove("hidden"); }
      } }, [...fields, error, el("div.dialog-actions", [
        el("button.btn.btn-secondary", { type: "button", onclick: close }, t("common.cancel")),
        el("button.btn.btn-primary", { type: "submit" }, t("edit.save")),
      ])]),
    ], { wide: true });
  }

  function editUser(u) {
    const name = el("input.input", { id: "au-name", value: u.display_name, maxLength: 80, required: true });
    const admin = el("input", { type: "checkbox", checked: u.is_admin });
    formDialog(t("admin.edit_user"), [
      field({ label: t("admin.col_name"), input: name }),
      el("label.checkbox", [admin, t("admin.badge_admin")]),
    ], () => api.patch(`/api/admin/users/${u.id}`, { display_name: name.value.trim(), is_admin: admin.checked }));
  }

  function editWishlist(w) {
    const title = el("input.input", { id: "aw-title", value: w.title, maxLength: 120, required: true });
    const desc = el("textarea.input", { id: "aw-desc", value: w.description, maxLength: 2000 });
    formDialog(t("admin.edit_list"), [field({ label: t("admin.col_title"), input: title }), field({ label: t("me.list_desc"), input: desc, optional: true })],
      () => api.patch(`/api/admin/wishlists/${w.id}`, { title: title.value.trim(), description: desc.value.trim() }));
  }

  function editItem(it) {
    const title = el("input.input", { id: "ai-title", value: it.title, maxLength: 160, required: true });
    const desc = el("textarea.input", { id: "ai-desc", value: it.description, maxLength: 4000 });
    const url = el("input.input", { id: "ai-url", type: "url", value: it.url || "", maxLength: 2048 });
    const removeImg = el("input", { type: "checkbox" });
    let qty = { value: it.quantity ?? 1, unlimited: it.quantity === null };
    const st = stepper({ value: qty.value, unlimited: qty.unlimited, allowUnlimited: true, onChange: (s) => { qty = s; } });
    formDialog(t("admin.edit_item"), [
      field({ label: t("admin.col_title"), input: title }),
      field({ label: t("item.note"), input: desc, optional: true }),
      field({ label: t("admin.link"), input: url, optional: true }),
      el("div.field", [el("label", t("admin.col_qty")), st]),
      it.image_url ? el("label.checkbox", [removeImg, t("admin.remove_image")]) : null,
    ], () => api.patch(`/api/admin/items/${it.id}`, { title: title.value.trim(), description: desc.value.trim(), url: url.value.trim(), unlimited: qty.unlimited, quantity: qty.unlimited ? undefined : qty.value, remove_image: removeImg.checked }));
  }

  async function wishlistDetail(id) {
    const w = await api.get(`/api/admin/wishlists/${id}`);
    openDialog((close) => [
      el("div.hstack", [el("div.dialog-title", `#${w.id} · ${w.title}`), el("a.btn.btn-ghost.btn-icon.ml-auto", { href: w.share_url, target: "_blank", rel: "noopener", title: t("admin.act_open") }, icon("arrow-square-out"))]),
      el("div.text-muted", { style: { fontSize: "12px" } }, `${w.owner_username} · ${fmtDate(w.created_at)}`),
      w.description ? el("p.quote", w.description) : null,
      el("div.rows.detail-list", w.items.length ? w.items.map((it) => el("div", [
        el("div.row", [thumb(it.image_url, "sm"), el("div.row-main", [el("div.row-title", it.title), el("div.row-sub", it.description)]), el("span.row-qty", `${it.booked_qty} / ${qtyText(it.quantity)}`)]),
        ...it.bookings.map((b) => el("div.booking", [icon("check"), ` ${b.booker_name} ×${b.quantity}`, b.note ? ` — ${b.note}` : "", el("span.muted", ` · ${timeAgo(b.created_at)}`)])),
      ])) : el("div.empty", t("admin.empty"))),
      el("div.dialog-actions", [el("button.btn.btn-secondary", { onclick: close }, t("common.close"))]),
    ], { wide: true });
  }

  async function aiSettingsPanel() {
    const s = await api.get("/api/admin/ai-settings");
    const status = el("div.note");
    const sel = (id, options, value) => el("select.input", { id, style: { maxWidth: "260px" } }, options.map(([v, label]) => el("option", { value: v, selected: v === value }, label)));
    const textSel = sel("ai-text", [["none", t("admin.ai_off")], ["anthropic", t("admin.ai_anthropic")], ["yandex", t("admin.ai_yandex")]], s.text_provider);
    const imageSel = sel("ai-image", [["none", t("admin.ai_off")], ["yandex", t("admin.ai_yandex")]], s.image_provider);
    const keyHint = (tail) => tail ? t("admin.ai_key_set", { tail }) : t("admin.ai_key_unset");
    const yKey = el("input.input", { id: "ai-ykey", type: "password", autocomplete: "off", placeholder: t("admin.ai_key_ph") });
    const yFolder = el("input.input", { id: "ai-yfolder", value: s.yandex_folder_id, placeholder: "b1g…" });
    const yText = el("input.input", { id: "ai-ytext", value: s.yandex_text_model });
    const yArt = el("input.input", { id: "ai-yart", value: s.yandex_art_model });
    const aKey = el("input.input", { id: "ai-akey", type: "password", autocomplete: "off", placeholder: t("admin.ai_key_ph") });
    const aModel = el("input.input", { id: "ai-amodel", value: s.anthropic_model });
    const yClear = el("input", { type: "checkbox" }); const aClear = el("input", { type: "checkbox" });
    const readiness = () => el("div.hstack", { style: { gap: "12px", fontSize: "12px" } }, [
      el("span", [t("admin.ai_text"), ": ", el("span.tag" + (s.text_ready ? ".tag-accent" : ".tag-neutral"), s.text_ready ? t("admin.ai_ready") : t("admin.ai_not_ready"))]),
      el("span", [t("admin.ai_image"), ": ", el("span.tag" + (s.image_ready ? ".tag-accent" : ".tag-neutral"), s.image_ready ? t("admin.ai_ready") : t("admin.ai_not_ready"))]),
    ]);
    const yandexBlock = el("div.card.elev-sm.stack-3", [
      el("div.card-title", t("admin.ai_yandex")),
      field({ label: t("admin.ai_key"), input: yKey, hint: keyHint(s.yandex_key_tail) }),
      el("label.checkbox", [yClear, t("admin.ai_clear_key")]),
      field({ label: t("admin.ai_folder"), input: yFolder }),
      el("div.hstack", { style: { alignItems: "flex-start" } }, [el("div.grow", field({ label: t("admin.ai_text_model"), input: yText })), el("div.grow", field({ label: t("admin.ai_art_model"), input: yArt }))]),
    ]);
    const anthropicBlock = el("div.card.elev-sm.stack-3", [
      el("div.card-title", t("admin.ai_anthropic")),
      field({ label: t("admin.ai_key"), input: aKey, hint: keyHint(s.anthropic_key_tail) }),
      el("label.checkbox", [aClear, t("admin.ai_clear_key")]),
      field({ label: t("admin.ai_model"), input: aModel }),
    ]);
    const testBtn = (kind) => el("button.btn.btn-secondary", { type: "button", onclick: async (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = t("admin.ai_testing");
      try { const r = await api.post("/api/admin/ai-settings/test", { kind }); status.textContent = `${kind}: ${r.ok ? "✓ " : "✗ "}${r.detail}`; status.style.color = r.ok ? "" : "var(--color-danger)"; }
      catch (err) { status.textContent = errorText(err); }
      finally { b.disabled = false; b.textContent = t("admin.ai_test"); }
    } }, t("admin.ai_test"));
    const form = el("form.stack-6", { onsubmit: async (e) => {
      e.preventDefault();
      try {
        await api.put("/api/admin/ai-settings", {
          text_provider: textSel.value, image_provider: imageSel.value,
          yandex_api_key: yKey.value.trim(), clear_yandex_api_key: yClear.checked, yandex_folder_id: yFolder.value.trim(), yandex_text_model: yText.value.trim(), yandex_art_model: yArt.value.trim(),
          anthropic_api_key: aKey.value.trim(), clear_anthropic_api_key: aClear.checked, anthropic_model: aModel.value.trim(),
        });
        toast(t("admin.ai_saved")); await load();
      } catch (err) { status.textContent = errorText(err); status.style.color = "var(--color-danger)"; }
    } }, [
      readiness(),
      el("div.hstack", { style: { flexWrap: "wrap", alignItems: "flex-end" } }, [
        field({ label: t("admin.ai_text") + " · " + t("admin.ai_provider"), input: textSel }), testBtn("text"),
        field({ label: t("admin.ai_image") + " · " + t("admin.ai_provider"), input: imageSel }), testBtn("image"),
      ]),
      status,
      el("div.grid-cards", [yandexBlock, anthropicBlock]),
      el("p.note", t("admin.ai_hint")),
      el("div.dialog-actions", { style: { justifyContent: "flex-start" } }, [el("button.btn.btn-primary", { type: "submit" }, t("admin.ai_save"))]),
      await mediaCard(),
    ]);
    return form;
  }

  const fmtBytes = (b) => b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`;
  async function mediaCard() {
    const m = await api.get("/api/admin/media");
    const line = el("div.card-body", t("admin.media_stats", { files: m.files, size: fmtBytes(m.bytes), orphans: m.orphans, osize: fmtBytes(m.orphan_bytes) }));
    const btn = el("button.btn.btn-secondary", { type: "button", disabled: m.removable === 0, onclick: async () => {
      if (!(await confirmDialog(t("admin.media_confirm", { n: m.removable, size: fmtBytes(m.removable_bytes) }), { danger: true, okLabel: t("admin.media_sweep") }))) return;
      const r = await api.post("/api/admin/media/sweep");
      toast(t("admin.media_done", { n: r.removed, size: fmtBytes(r.bytes) }));
      await load();
    } }, [icon("broom"), t("admin.media_sweep"), m.removable ? ` (${m.removable})` : ""]);
    return el("div.card.elev-sm.stack-2", [el("div.card-title", t("admin.media_title")), line, el("p.note", t("admin.media_hint")), el("div", btn)]);
  }

  renderSeg();
  await Promise.all([loadStats(), load()]);
}
