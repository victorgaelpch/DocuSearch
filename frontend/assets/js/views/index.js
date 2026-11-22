// Registro de vistas. Cada vista: { path, title, nav?, requires?, render(main, params, query) }.
// requires: "user" (cualquier sesión) o "admin". Solo se listan vistas implementadas.
import home from "./home.js";
import login from "./login.js";
import help from "./help.js";
import documents from "./documents.js";
import viewer from "./viewer.js";
import search from "./search.js";

export default [home, login, help, documents, viewer, search];
