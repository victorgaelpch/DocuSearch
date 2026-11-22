// Utilidades DOM seguras (DOC-26). Todo el texto se inserta como nodos de
// texto: nunca se interpreta como HTML el contenido de documentos o de la API.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "text") el.textContent = value;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toLocaleString("es-MX", { maximumFractionDigits: 1 })} ${units[unit]}`;
}

export function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
}

export function announce(message) {
  const status = document.getElementById("status");
  if (!status) return;
  status.textContent = "";
  // un retardo mínimo para que los lectores de pantalla repitan mensajes iguales
  window.setTimeout(() => { status.textContent = message; }, 30);
}

export function notice(kind, ...content) {
  return h("div", { class: `notice notice-${kind}`, role: kind === "error" ? "alert" : "status" }, h("p", {}, ...content));
}

export function loading(text = "Cargando…") {
  return h("p", { class: "loading", role: "status" }, text);
}

export function emptyState(title, body, action) {
  return h("div", { class: "empty" }, h("h2", {}, title), h("p", {}, body), action || null);
}

// Mensaje de una sola lectura para la siguiente vista (solo en memoria).
let flashMessage = null;
export function setFlash(kind, text) { flashMessage = { kind, text }; }
export function takeFlash() { const message = flashMessage; flashMessage = null; return message; }
