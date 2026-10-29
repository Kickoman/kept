import { api, ApiError } from "../api.js";
import { t } from "../i18n.js";
import { el, errorText, field, icon, langSwitch, themeSwitch } from "../ui.js";

export function authPage({ mode }) {
  const app = document.getElementById("app");
  app.className = "page-center";
  const isRegister = mode === "register";
  const params = new URLSearchParams(location.search);
  const next = params.get("next") && params.get("next").startsWith("/") ? params.get("next") : "/me";

  const username = el("input.input", { id: "username", autocomplete: "username", required: true, minLength: isRegister ? 3 : 1, maxLength: 64, style: { minHeight: "40px" } });
  const password = el("input.input", { id: "password", type: "password", autocomplete: isRegister ? "new-password" : "current-password", required: true, minLength: isRegister ? 8 : 1, style: { minHeight: "40px" } });
  const displayName = el("input.input", { id: "display_name", autocomplete: "name", required: true, maxLength: 80, style: { minHeight: "40px" } });
  const error = el("div.error.hidden");
  const submit = el("button.btn.btn-primary.btn-block.btn-lg", { type: "submit" }, isRegister ? t("auth.register_btn") : t("auth.login_btn"));

  const form = el("form.auth-card", {
    onsubmit: async (e) => {
      e.preventDefault();
      error.classList.add("hidden");
      submit.disabled = true;
      try {
        const body = { username: username.value.trim(), password: password.value };
        if (isRegister) body.display_name = displayName.value.trim();
        await api.post(`/api/auth/${isRegister ? "register" : "login"}`, body, { silent401: true });
        location.href = next;
      } catch (err) {
        let msg = errorText(err);
        if (err instanceof ApiError) {
          if (err.status === 401) msg = t("auth.err_credentials");
          if (err.status === 409) msg = t("auth.err_taken");
        }
        error.textContent = msg;
        error.classList.remove("hidden");
        submit.disabled = false;
      }
    },
  }, [
    el("a.nav-brand", { href: "/" }, [icon("bookmark-simple"), t("brand")]),
    el("h3", isRegister ? t("auth.register_title") : t("auth.login_title")),
    next.startsWith("/w/") ? el("div.banner", [icon("gift"), t("auth.claim_hint")]) : null,
    isRegister ? field({ label: t("auth.display_name"), input: displayName, hint: t("auth.display_hint") }) : null,
    field({ label: t("auth.username"), input: username, hint: isRegister ? t("auth.username_hint") : null }),
    field({ label: t("auth.password"), input: password, hint: isRegister ? t("auth.password_hint") : null }),
    error,
    submit,
    el("div.hstack", { style: { justifyContent: "space-between" } }, [
      el("a", { href: (isRegister ? "/login" : "/register") + location.search, style: { fontSize: "13px" } }, isRegister ? t("auth.to_login") : t("auth.to_register")),
      el("div.hstack", { style: { gap: "2px" } }, [themeSwitch(), langSwitch()]),
    ]),
  ]);
  app.append(form);
  (isRegister ? displayName : username).focus();
}
