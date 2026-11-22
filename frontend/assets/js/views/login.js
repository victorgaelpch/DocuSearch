import { h, announce } from "../dom.js";
import { ApiError, login, session } from "../api.js";
import { navigate } from "../router.js";

function safeNext(query) {
  const next = query.get("next") || "/";
  // solo rutas internas de la aplicación
  return /^\/[\w\-/%]*$/.test(next) && !next.startsWith("//") ? next : "/";
}

export default {
  path: "/login",
  title: "Iniciar sesión",
  render(main, _params, query) {
    const current = session();
    const next = safeNext(query);
    main.append(h("header", { class: "page-head" }, h("h1", {}, "Iniciar sesión")));
    if (current.authenticated) {
      main.append(h("p", {}, "Ya inició sesión como ", h("strong", {}, current.username), ". ", h("a", { href: `#${next}` }, "Continuar")));
      return;
    }
    if (current.expired) {
      main.append(h("div", { class: "notice notice-warn", role: "alert" }, h("p", {}, "Su sesión expiró. Vuelva a iniciar sesión para continuar.")));
    }
    if (!current.auth_configured && !current.unreachable) {
      main.append(h("div", { class: "notice notice-warn" }, h("p", {}, "No hay cuentas configuradas en este servidor. Consulte la ", h("a", { href: "#/ayuda" }, "ayuda"), " para crear la cuenta de Administrador.")));
    }
    const error = h("div", { id: "login-error", class: "notice notice-error", role: "alert", hidden: true });
    const username = h("input", { id: "username", name: "username", type: "text", autocomplete: "username", required: true, maxlength: 64, spellcheck: "false", autocapitalize: "none" });
    const password = h("input", { id: "password", name: "password", type: "password", autocomplete: "current-password", required: true, maxlength: 1024, "aria-describedby": "login-error" });
    const submit = h("button", { class: "btn", type: "submit" }, "Iniciar sesión");
    const form = h("form", { class: "sheet form-narrow", novalidate: true },
      h("div", { class: "field" }, h("label", { for: "username" }, "Usuario"), username),
      h("div", { class: "field" }, h("label", { for: "password" }, "Contraseña"), password),
      error,
      submit,
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.hidden = true;
      if (!username.value.trim() || !password.value) {
        error.textContent = "Escriba el usuario y la contraseña.";
        error.hidden = false;
        (username.value.trim() ? password : username).focus();
        return;
      }
      submit.disabled = true;
      submit.textContent = "Comprobando…";
      try {
        await login(username.value.trim(), password.value);
        password.value = "";
        announce("Sesión iniciada");
        navigate(next);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "No se pudo iniciar sesión.";
        error.textContent = err.code === "invalid_credentials" ? "Usuario o contraseña incorrectos." : message;
        error.hidden = false;
        password.value = "";
        password.focus();
      } finally {
        submit.disabled = false;
        submit.textContent = "Iniciar sesión";
      }
    });
    main.append(form);
  },
};
