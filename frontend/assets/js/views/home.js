import { h } from "../dom.js";
import { session } from "../api.js";

export default {
  path: "/",
  title: "Inicio",
  nav: { label: "Inicio", order: 10 },
  render(main) {
    const current = session();
    const intro = h("header", { class: "page-head" },
      h("h1", {}, "Busque dentro de sus documentos"),
      h("p", {}, "DocuSearch extrae el texto de archivos PDF, Word y de texto, lo divide en fragmentos y lo ordena por relevancia para consultas en español. Todo se procesa en esta computadora."),
    );
    const steps = h("ol", { class: "steps" },
      h("li", {}, h("strong", {}, "Cargue"), " archivos PDF, DOCX o TXT (los PDF escaneados pasan por OCR si Tesseract está instalado)."),
      h("li", {}, h("strong", {}, "Busque"), " con palabras clave (BM25, TF-IDF) o por significado (semántica e híbrida, si el modelo está instalado)."),
      h("li", {}, h("strong", {}, "Abra el origen"), ": cada resultado indica el documento, la página y el fragmento encontrado."),
    );
    let state;
    if (current.unreachable) {
      state = h("div", { class: "notice notice-error", role: "alert" }, h("p", {}, "No hay conexión con el servidor de DocuSearch. Inícielo con ", h("code", {}, "python -m uvicorn backend.app.main:app"), " y recargue la página."));
    } else if (current.authenticated) {
      state = h("div", { class: "notice notice-ok" }, h("p", {}, "Sesión iniciada como ", h("strong", {}, current.username), current.role === "admin" ? " (Administrador)." : " (Usuario de consulta)."));
    } else if (!current.auth_configured) {
      state = h("div", { class: "notice notice-warn" },
        h("p", {}, "Todavía no hay una cuenta de Administrador. Genere el hash de una contraseña con ", h("code", {}, "python -m backend.app.cli hash-password"), ", guárdelo en la variable ", h("code", {}, "DOCUSEARCH_ADMIN_PASSWORD_HASH"), " y reinicie el servidor."),
        h("p", {}, h("a", { href: "#/ayuda" }, "Ver instrucciones de configuración")),
      );
    } else {
      state = h("div", { class: "notice" }, h("p", {}, "Sus documentos son privados. ", h("a", { href: "#/login" }, "Inicie sesión"), " para consultarlos."));
    }
    main.append(intro, state, h("h2", {}, "Cómo funciona"), steps);
  },
};
