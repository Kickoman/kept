import { getMe } from "../api.js";
import { t } from "../i18n.js";
import { el, nav, setTitle } from "../ui.js";

const app = document.getElementById("app");
const me = await getMe();
setTitle("");
app.append(await nav());
app.append(
  el("section.hero", [
    el("h1", t("landing.title")),
    el("div.hstack", { style: { marginTop: "8px", flexWrap: "wrap" } }, [
      el("a.btn.btn-primary.btn-lg", { href: me ? "/me" : "/register" }, me ? t("nav.mylists") : t("nav.start")),
      me ? null : el("a.btn.btn-secondary.btn-lg", { href: "/login" }, t("nav.signin")),
    ]),
  ]),
);
