// Cliente de la API en el mismo origen (DOC-26).
// La sesión viaja en una cookie HttpOnly que JavaScript no puede leer; el
// token CSRF se guarda solo en memoria (nunca en localStorage).

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  constructor(status, code, message, body = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

const state = { session: { authenticated: false, auth_configured: false }, listeners: new Set() };

export function session() { return state.session; }
export function isAdmin() { return state.session.authenticated && state.session.role === "admin"; }
export function onSessionChange(listener) { state.listeners.add(listener); return () => state.listeners.delete(listener); }

function setSession(next) {
  state.session = next;
  for (const listener of state.listeners) listener(next);
}

const NETWORK_MESSAGE = "No hay conexión con el servidor de DocuSearch. Compruebe que sigue en marcha en esta computadora.";

export async function request(method, path, { json, body, query, signal } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  const headers = { Accept: "application/json" };
  let payload = body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(json);
  }
  if (UNSAFE.has(method) && state.session.csrf_token) headers["X-CSRF-Token"] = state.session.csrf_token;
  let response;
  try {
    response = await fetch(url, { method, headers, body: payload, credentials: "same-origin", signal, cache: "no-store" });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", NETWORK_MESSAGE);
  }
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json().catch(() => null) : null;
  if (!response.ok) {
    const err = data && data.error ? data.error : null;
    const detail = data && Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : null;
    const apiError = new ApiError(
      response.status,
      err ? err.code : `http_${response.status}`,
      err ? err.message : detail || `Error ${response.status} del servidor`,
      data,
    );
    if (response.status === 401 && state.session.authenticated && path !== "/auth/login") {
      setSession({ authenticated: false, auth_configured: state.session.auth_configured, expired: true });
    }
    throw apiError;
  }
  return data;
}

export const api = {
  get: (path, options) => request("GET", path, options),
  post: (path, options) => request("POST", path, options),
  patch: (path, options) => request("PATCH", path, options),
  delete: (path, options) => request("DELETE", path, options),
};

export async function refreshSession() {
  try {
    setSession(await api.get("/auth/me"));
  } catch (error) {
    setSession({ authenticated: false, auth_configured: false, unreachable: error.code === "network_error" });
  }
  return state.session;
}

export async function login(username, password) {
  const data = await api.post("/auth/login", { json: { username, password } });
  setSession(data);
  return data;
}

export async function logout() {
  try {
    await api.post("/auth/logout");
  } finally {
    setSession({ authenticated: false, auth_configured: state.session.auth_configured });
  }
}
