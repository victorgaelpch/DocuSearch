// Enrutador por hash (#/ruta/:param) con gestión de foco accesible (DOC-26).
import { clear, h } from "./dom.js";
import { session } from "./api.js";

const routes = [];
let currentCleanup = null;
let firstRender = true;

export function route(pattern, view) {
  const keys = [];
  const regex = new RegExp(
    "^" + pattern.replace(/\/:([a-z_]+)/gi, (_, key) => { keys.push(key); return "/([^/]+)"; }) + "/?$",
  );
  routes.push({ pattern, regex, keys, view });
}

export function navigate(path) {
  if (window.location.hash === `#${path}`) render();
  else window.location.hash = path;
}

export function currentPath() {
  return (window.location.hash || "#/").slice(1).split("?")[0] || "/";
}

export function currentQuery() {
  const raw = (window.location.hash || "").split("?")[1] || "";
  return new URLSearchParams(raw);
}

function match(path) {
  for (const entry of routes) {
    const found = entry.regex.exec(path);
    if (found) {
      const params = {};
      entry.keys.forEach((key, index) => { params[key] = decodeURIComponent(found[index + 1]); });
      return { entry, params };
    }
  }
  return null;
}

export function isAppHash() {
  const hash = window.location.hash;
  return !hash || hash === "#" || hash.startsWith("#/");
}

export async function render() {
  // anclas internas (p. ej. #main del enlace de salto) no son rutas
  if (!isAppHash()) return;
  const main = document.getElementById("main");
  const path = currentPath();
  const found = match(path);
  if (currentCleanup) { try { currentCleanup(); } catch { /* vista anterior */ } currentCleanup = null; }
  clear(main);
  document.dispatchEvent(new CustomEvent("routechange", { detail: { path } }));
  if (!found) {
    document.title = "Página no encontrada · DocuSearch";
    main.append(h("h1", {}, "Esta página no existe"), h("p", {}, "Revise la dirección o vuelva al ", h("a", { href: "#/" }, "inicio"), "."));
    focusHeading(main);
    return;
  }
  const view = found.entry.view;
  if (view.requires && !session().authenticated) {
    const next = encodeURIComponent(path);
    window.location.replace(`#/login?next=${next}`);
    return;
  }
  if (view.requires === "admin" && session().role !== "admin") {
    document.title = "Acceso restringido · DocuSearch";
    main.append(h("h1", {}, "Acceso restringido"), h("p", {}, "Esta sección es solo para la cuenta de Administrador."));
    focusHeading(main);
    return;
  }
  document.title = `${view.title} · DocuSearch`;
  const cleanup = await view.render(main, found.params, currentQuery());
  if (typeof cleanup === "function") currentCleanup = cleanup;
  if (!main.contains(document.activeElement) || document.activeElement === main) focusHeading(main);
  else firstRender = false;
}

export function focusHeading(main) {
  // En la carga inicial el foco queda al principio del documento (enlace de
  // salto); en los cambios de vista se lleva al título para anunciarlo.
  if (firstRender) { firstRender = false; return; }
  const heading = main.querySelector("h1");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: false });
  } else {
    main.focus();
  }
}
