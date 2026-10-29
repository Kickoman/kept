import { api, ApiError, getConfig } from "../api.js";
import { lang, t } from "../i18n.js";
import { el, errorText, field, hostOf, icon, isUrl, openDialog, splitLinkText, stepper, thumb } from "../ui.js";

/**
 * Add / edit item dialog (design screens 05–06).
 * opts: { wishlist, item?, initialText?, onSaved(item) }
 */
export async function openItemDialog({ wishlist, item = null, initialText = "", onSaved }) {
  const config = await getConfig().catch(() => ({}));
  const isEdit = !!item;
  const state = {
    title: item ? item.title : "",
    description: item ? item.description : "",
    url: item ? item.url || "" : "",
    quantity: item ? item.quantity ?? 1 : 1,
    unlimited: item ? item.quantity === null : false,
    imageUrl: item ? item.image_url : null, // existing stored image
    suggestedImage: null, // remote og:image from enrichment
    useSuggested: false,
    file: null, // local upload
    filePreview: null,
    generated: null, // {image_url, image_path} from /ai/image
    generating: false,
    removeImage: false,
    touchedTitle: isEdit, touchedDesc: isEdit,
    reading: false, lastEnriched: null,
  };
  if (!isEdit && initialText) {
    // "кружки https://shop.example/cups": the link is read for description and photo,
    // the words around it become the title and win over whatever the page suggests.
    const { url, rest } = splitLinkText(initialText);
    if (url) state.url = url;
    if (rest) { state.title = rest; state.touchedTitle = true; }
  }

  const linkInput = el("input.input", { id: "it-url", type: "url", placeholder: t("item.link_ph"), value: state.url, style: { minHeight: "44px", paddingLeft: "34px" } });
  const linkWrap = el("div", { style: { position: "relative" } }, [
    icon("link", { style: { position: "absolute", left: "11px", top: "14px", fontSize: "16px", color: "var(--color-accent)" } }),
    linkInput,
  ]);
  const reading = el("div.reading.hidden", [icon("circle-notch", { className: "ph ph-circle-notch spin" }), t("item.reading")]);
  const readFail = el("div.hint.hidden", { style: { color: "var(--color-danger)" } }, t("item.read_failed"));
  const linkField = el("div.field", [el("label", { htmlFor: "it-url" }, t("item.paste")), linkWrap, reading, readFail]);
  const linkLine = el("div.linkline");
  let linkVisible = !isEdit && !state.title; // show the link field up front for the paste flow

  const titleInput = el("input.input", { id: "it-title", required: true, maxLength: 160, placeholder: t("item.title_ph"), value: state.title, style: { minHeight: "40px" },
    oninput: () => { state.title = titleInput.value; state.touchedTitle = true; } });
  const descInput = el("textarea.input", { id: "it-desc", maxLength: 4000, placeholder: t("item.note_ph"), value: state.description,
    oninput: () => { state.description = descInput.value; state.touchedDesc = true; } });
  const qty = stepper({ value: state.quantity, unlimited: state.unlimited, allowUnlimited: true, large: true, onChange: (s) => { state.quantity = s.value; state.unlimited = s.unlimited; } });

  const mediaBox = el("div");
  const fileInput = el("input", { type: "file", accept: "image/*", style: { display: "none" }, onchange: () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f) return;
    state.file = f; state.removeImage = false; state.useSuggested = false; state.generated = null;
    if (state.filePreview) URL.revokeObjectURL(state.filePreview);
    state.filePreview = URL.createObjectURL(f);
    renderMedia();
  } });
  const genError = el("div.hint.hidden", { style: { color: "var(--color-danger)" } });
  async function generateImage() {
    const title = titleInput.value.trim();
    if (title.length < 3) { genError.textContent = t("item.gen_empty"); genError.classList.remove("hidden"); return; }
    state.generating = true; genError.classList.add("hidden"); renderMedia();
    try {
      const r = await api.post("/api/ai/image", { title, description: descInput.value.trim(), lang });
      state.generated = r; state.file = null; state.useSuggested = false; state.removeImage = false;
    } catch (err) {
      genError.textContent = t("item.gen_failed"); genError.classList.remove("hidden");
    } finally { state.generating = false; renderMedia(); }
  }
  function currentPreview() {
    if (state.file) return { src: state.filePreview, label: null };
    if (state.generated) return { src: state.generated.image_url, label: null };
    if (state.useSuggested && state.suggestedImage) return { src: state.suggestedImage, label: t("item.from_page") };
    if (state.imageUrl && !state.removeImage) return { src: state.imageUrl, label: null };
    return { src: null, label: state.suggestedImage ? null : t("item.no_image") };
  }
  function renderMedia() {
    const p = currentPreview();
    const actions = [
      el("button.btn.btn-ghost", { type: "button", onclick: () => fileInput.click() }, [icon("upload-simple"), t("item.upload")]),
      config.image_generation
        ? el("button.btn.btn-ghost", { type: "button", disabled: state.generating, onclick: generateImage }, [icon(state.generating ? "circle-notch" : "sparkle", state.generating ? { className: "ph ph-circle-notch spin" } : {}), state.generating ? t("item.generating") : t("item.generate")])
        : null,
      state.suggestedImage && !state.useSuggested && !state.file
        ? el("button.btn.btn-ghost", { type: "button", onclick: () => { state.useSuggested = true; state.removeImage = false; renderMedia(); } }, [icon("image"), t("item.use_page_photo")])
        : null,
      p.src
        ? el("button.btn.btn-ghost", { type: "button", onclick: () => { state.file = null; state.generated = null; state.useSuggested = false; if (state.imageUrl) state.removeImage = true; renderMedia(); } }, [icon("x"), t("item.remove_photo")])
        : null,
    ];
    mediaBox.replaceChildren(el("div.stack-2", { style: { alignItems: "center" } }, [thumb(p.src, "md", p.label), el("div.upload-actions", actions), genError]));
  }
  renderMedia();

  const skeleton = el("div.skeleton.hidden", [el("div.thumb-md", { className: "thumb thumb-md" }), el("div.bars", [el("div.bar"), el("div.bar"), el("div.bar")])]);
  const formBody = el("div.stack-3", [
    el("div.add-media", [
      el("div", [mediaBox, fileInput]),
      el("div.grow.stack-3", [
        field({ label: t("item.title"), input: titleInput }),
        el("div.qty-row", [el("div.field", [el("label", t("item.quantity")), qty])]),
      ]),
    ]),
    field({ label: t("item.note"), input: descInput, optional: true }),
    linkLine,
  ]);
  const error = el("div.error.hidden");
  const submitBtn = el("button.btn.btn-primary", { type: "submit" }, isEdit ? t("item.save") : t("item.add"));

  function renderLinkLine() {
    linkLine.replaceChildren(
      icon("link-simple", { style: { fontSize: "14px" } }),
      el("span", state.url ? hostOf(state.url) : ""),
      el("button.btn.btn-ghost", { type: "button", onclick: () => { linkVisible = true; applyVisibility(); linkInput.focus(); } }, state.url ? t("item.change_link") : t("item.add_link")),
    );
  }
  function applyVisibility() {
    linkField.classList.toggle("hidden", !linkVisible);
    linkLine.classList.toggle("hidden", linkVisible);
  }
  renderLinkLine();
  applyVisibility();

  let enrichSeq = 0;
  async function enrich(url) {
    const seq = ++enrichSeq;
    state.reading = true;
    reading.classList.remove("hidden"); readFail.classList.add("hidden");
    skeleton.classList.remove("hidden"); formBody.classList.add("hidden"); submitBtn.disabled = true;
    try {
      const res = await api.post("/api/ai/enrich", { url, lang });
      if (seq !== enrichSeq) return;
      state.lastEnriched = url;
      if (res.title && !state.touchedTitle) { state.title = res.title; titleInput.value = res.title; }
      if (res.description && !state.touchedDesc) { state.description = res.description; descInput.value = res.description; }
      if (res.image_url) { state.suggestedImage = res.image_url; if (!state.file && !(state.imageUrl && !state.removeImage)) state.useSuggested = true; }
      renderMedia();
    } catch (err) {
      if (seq !== enrichSeq) return;
      readFail.classList.remove("hidden");
      if (err instanceof ApiError && err.status === 401) return;
    } finally {
      if (seq === enrichSeq) {
        state.reading = false;
        reading.classList.add("hidden"); skeleton.classList.add("hidden"); formBody.classList.remove("hidden"); submitBtn.disabled = false;
        linkVisible = false; renderLinkLine(); applyVisibility();
        if (!state.title) titleInput.focus();
      }
    }
  }
  function maybeEnrich() {
    const { url, rest } = splitLinkText(linkInput.value);
    if (url && rest && !state.touchedTitle) {
      state.title = rest; titleInput.value = rest; state.touchedTitle = true;
    }
    if (url) linkInput.value = url;
    state.url = url || linkInput.value.trim();
    renderLinkLine();
    if (isUrl(state.url) && state.url !== state.lastEnriched) enrich(state.url);
  }
  linkInput.addEventListener("change", maybeEnrich);
  linkInput.addEventListener("paste", () => setTimeout(maybeEnrich, 0));
  linkInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); maybeEnrich(); } });

  const { close } = openDialog((closeDlg) => [
    el("div.add-head", [
      el("h4", isEdit ? t("item.edit") : t("item.add_to", { title: wishlist.title })),
      el("button.btn.btn-ghost.btn-icon.ml-auto", { type: "button", "aria-label": t("common.close"), onclick: closeDlg }, icon("x")),
    ]),
    el("form.stack-3", {
      onsubmit: async (e) => {
        e.preventDefault();
        if (state.reading) return;
        error.classList.add("hidden");
        state.title = titleInput.value.trim();
        state.description = descInput.value.trim();
        if (!state.title) { error.textContent = t("item.err_title"); error.classList.remove("hidden"); titleInput.focus(); return; }
        submitBtn.disabled = true;
        try {
          const payload = {
            title: state.title, description: state.description,
            url: state.url || (isEdit ? "" : null),
            quantity: state.unlimited ? null : state.quantity,
          };
          let saved;
          if (state.generated && !state.file) payload.image_path = state.generated.image_path;
          else if (state.useSuggested && state.suggestedImage && !state.file) payload.image_url = state.suggestedImage;
          if (isEdit) {
            payload.unlimited = state.unlimited;
            if (state.unlimited) delete payload.quantity;
            if (state.removeImage && !state.file && !state.useSuggested && !state.generated) payload.remove_image = true;
            saved = await api.patch(`/api/items/${item.id}`, payload);
          } else {
            saved = await api.post(`/api/wishlists/${wishlist.id}/items`, payload);
          }
          if (state.file) {
            try { saved = await api.upload(`/api/items/${saved.id}/image`, state.file); }
            catch (err) { error.textContent = t("item.err_image"); error.classList.remove("hidden"); }
          }
          closeDlg();
          onSaved(saved);
        } catch (err) {
          error.textContent = errorText(err);
          error.classList.remove("hidden");
          submitBtn.disabled = false;
        }
      },
    }, [
      linkField,
      skeleton,
      formBody,
      error,
      el("div.dialog-actions", [
        el("button.btn.btn-secondary", { type: "button", onclick: closeDlg }, t("item.cancel")),
        submitBtn,
      ]),
    ]),
  ], { wide: true });
  void close;

  if (!isEdit && isUrl(state.url)) enrich(state.url);
  else if (!state.title) (linkVisible ? linkInput : titleInput).focus();
}
