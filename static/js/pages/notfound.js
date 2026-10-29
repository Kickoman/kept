import { t } from "../i18n.js";
import { el, nav } from "../ui.js";

const app = document.getElementById("app");
app.append(await nav());
app.append(el("div.empty", { style: { marginTop: "48px" } }, [
  el("h3", t("share.notfound")),
  el("p", t("share.notfound_text")),
  el("a.btn.btn-primary", { href: "/" }, t("share.home")),
]));
