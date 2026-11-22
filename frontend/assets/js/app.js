// Arranque de la interfaz web de DocuSearch (DOC-26).
import { h, clear, announce } from "./dom.js";
import { isAdmin, logout, onSessionChange, refreshSession, session } from "./api.js";
import { currentPath, navigate, render, route } from "./router.js";
import views from "./views/index.js";

for (const view of views) route(view.path, view);

function visible(view) {
  if (!view.nav) return false;
  if (view.requires === "admin") return isAdmin();
  if (view.requires) return session().authenticated;
  return true;
}

function renderNav() {
  const list = document.getElementById("nav-list");
  clear(list);
  const path = currentPath();
  const items = views.filter(visible).sort((a, b) => a.nav.order - b.nav.order);
  for (const view of items) {
    const active = view.path === "/" ? path === "/" : path === view.path || path.startsWith(`${view.path}/`);
    list.append(h("li", {}, h("a", { href: `#${view.path}`, "aria-current": active ? "page" : null }, view.nav.label)));
  }
}

function renderSession() {
  const box = document.getElementById("session");
  clear(box);
  const current = session();
  if (current.authenticated) {
    box.append(
      h("span", {}, "Sesión: ", h("strong", {}, current.username)),
      h("span", { class: "role" }, current.role === "admin" ? "Administrador" : "Usuario de consulta"),
      h("button", {
        class: "btn btn-quiet btn-small", type: "button",
        onclick: async () => { await logout(); announce("Sesión cerrada"); navigate("/"); },
      }, "Cerrar sesión"),
    );
  } else if (currentPath() !== "/login") {
    box.append(h("a", { class: "btn btn-small", href: "#/login" }, "Iniciar sesión"));
  }
}

function setupNavToggle() {
  const toggle = document.querySelector(".nav-toggle");
  const nav = document.getElementById("nav");
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("open", open);
  });
  document.addEventListener("routechange", () => {
    toggle.setAttribute("aria-expanded", "false");
    nav.classList.remove("open");
  });
}

async function start() {
  setupNavToggle();
  await refreshSession();
  let wasAuthenticated = session().authenticated;
  onSessionChange((current) => {
    renderNav();
    renderSession();
    if (wasAuthenticated && !current.authenticated && current.expired) {
      navigate(`/login?next=${encodeURIComponent(currentPath())}`);
    }
    wasAuthenticated = current.authenticated;
  });
  document.addEventListener("routechange", () => { renderNav(); renderSession(); });
  window.addEventListener("hashchange", render);
  renderNav();
  renderSession();
  await render();
}

start();
