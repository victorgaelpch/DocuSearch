// Carga, importación, listado y filtrado de documentos (DOC-27).
import { h, clear, announce, emptyState, formatBytes, formatDate, loading, notice } from "../dom.js";
import { ApiError, api, isAdmin } from "../api.js";
import { navigate } from "../router.js";
import { SOURCE_LABELS, formatLabel, statusInfo } from "../format.js";

const PAGE_SIZE = 20;
const ACCEPT = ".pdf,.docx,.txt";

function statusTag(status) {
  const info = statusInfo(status);
  return h("span", { class: `tag ${info.tag}` }, info.label);
}

function uploadMessage(file, error) {
  if (error.code === "duplicate_document") {
    const existing = error.body && error.body.error && error.body.error.doc_id;
    return [`${file.name}: ya estaba cargado`, existing ? h("span", {}, " con el identificador ", h("code", {}, existing)) : null, "."];
  }
  if (error.code === "not_authenticated") return [`${file.name}: la sesión expiró; inicie sesión y vuelva a intentarlo.`];
  if (error.code === "network_error") return [`${file.name}: no hay conexión con el servidor.`];
  return [`${file.name}: ${error.message}.`];
}

function plural(count, one, many) {
  return `${count.toLocaleString("es-MX")} ${count === 1 ? one : many}`;
}

function resultLine(doc) {
  const info = statusInfo(doc.extraction_status);
  const parts = [
    h("strong", {}, doc.title), `. ${formatLabel(doc.mime_type)}, ${info.label.toLowerCase()}, `,
    `${plural(doc.word_count, "palabra", "palabras")}, ${plural(doc.chunk_count, "fragmento", "fragmentos")}. `,
    "Identificador: ", h("code", {}, doc.doc_id), ".",
  ];
  if (doc.warnings && doc.warnings.length) parts.push(h("br"), `Avisos: ${doc.warnings.join("; ")}`);
  return parts;
}

function uploadSection(onUploaded) {
  const input = h("input", { id: "files", name: "files", type: "file", multiple: true, accept: ACCEPT, "aria-describedby": "files-hint" });
  const submit = h("button", { class: "btn", type: "submit" }, "Cargar documentos");
  const results = h("ul", { class: "results-log", "aria-live": "polite" });
  const zone = h("div", { class: "dropzone" },
    h("label", { for: "files" }, "Archivos PDF, DOCX o TXT"),
    input,
    h("p", { id: "files-hint", class: "hint" }, "También puede arrastrarlos a este recuadro. Cada archivo se procesa al cargarlo: extracción de texto, OCR si es un PDF escaneado y fragmentación."),
  );
  for (const type of ["dragenter", "dragover"]) zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add("dragging"); });
  for (const type of ["dragleave", "drop"]) zone.addEventListener(type, () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    if (event.dataTransfer && event.dataTransfer.files.length) {
      input.files = event.dataTransfer.files;
      announce(`${input.files.length} archivo(s) listo(s) para cargar`);
    }
  });
  const form = h("form", { class: "sheet stack", "aria-labelledby": "upload-title" },
    h("h2", { id: "upload-title" }, "Cargar documentos"), zone, submit, results);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const files = [...input.files];
    if (!files.length) {
      clear(results).append(h("li", { class: "log-error" }, "Elija al menos un archivo."));
      input.focus();
      return;
    }
    submit.disabled = true;
    clear(results);
    let ok = 0;
    for (const file of files) {
      const line = h("li", { class: "loading" }, `Procesando ${file.name}…`);
      results.append(line);
      const body = new FormData();
      body.append("file", file, file.name);
      try {
        const doc = await api.post("/documents", { body });
        ok += 1;
        line.className = doc.extraction_status === "needs_ocr" ? "log-warn" : "log-ok";
        clear(line).append(...resultLine(doc));
      } catch (error) {
        if (!(error instanceof ApiError)) throw error;
        line.className = "log-error";
        clear(line).append(...uploadMessage(file, error));
        if (error.code === "not_authenticated") break;
      }
    }
    submit.disabled = false;
    // la selección se conserva si algo falló, para reintentar sin elegir de nuevo
    if (ok === files.length) input.value = "";
    announce(`${ok} de ${files.length} documento(s) cargado(s)`);
    if (ok) onUploaded();
  });
  return form;
}

function importSection(onUploaded) {
  const url = h("input", { id: "gdoc-url", name: "url", type: "url", required: true, placeholder: "https://docs.google.com/document/d/…/edit", "aria-describedby": "gdoc-hint" });
  const submit = h("button", { class: "btn btn-quiet", type: "submit" }, "Importar documento");
  const result = h("div", { "aria-live": "polite" });
  const form = h("form", { class: "sheet stack", "aria-labelledby": "import-title" },
    h("h2", { id: "import-title" }, "Importar un Google Doc público"),
    h("div", { class: "field" },
      h("label", { for: "gdoc-url" }, "Enlace del documento"), url,
      h("p", { id: "gdoc-hint", class: "hint" }, "Debe estar compartido como «cualquier persona con el enlace». Los documentos privados requieren OAuth, que aún no está disponible."),
    ),
    submit, result);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clear(result);
    if (!url.value.trim()) { url.focus(); return; }
    submit.disabled = true;
    result.append(loading("Descargando desde Google Docs…"));
    try {
      const doc = await api.post("/documents/import", { json: { url: url.value.trim() } });
      clear(result).append(h("div", { class: "notice notice-ok" }, h("p", {}, ...resultLine(doc))));
      url.value = "";
      onUploaded();
    } catch (error) {
      clear(result).append(notice("error", error.code === "duplicate_document" ? "Ese documento ya estaba importado." : error.message));
    } finally {
      submit.disabled = false;
    }
  });
  return form;
}

function readFilters(query) {
  return {
    q: query.get("q") || "",
    format: query.get("format") || "",
    status: query.get("status") || "",
    page: Math.max(1, Number.parseInt(query.get("page") || "1", 10) || 1),
  };
}

function filtersPath(filters) {
  const params = new URLSearchParams();
  for (const key of ["q", "format", "status"]) if (filters[key]) params.set(key, filters[key]);
  if (filters.page > 1) params.set("page", String(filters.page));
  const text = params.toString();
  return `/documentos${text ? `?${text}` : ""}`;
}

function filterForm(filters) {
  const q = h("input", { id: "filter-q", type: "search", name: "q", value: filters.q, maxlength: 200 });
  const select = (id, label, name, options) => {
    const el = h("select", { id, name }, options.map(([value, text]) => h("option", { value, selected: value === filters[name] }, text)));
    el.addEventListener("change", () => form.requestSubmit());
    return h("div", { class: "field" }, h("label", { for: id }, label), el);
  };
  const form = h("form", { class: "filters", "aria-label": "Filtrar documentos" },
    h("div", { class: "field" }, h("label", { for: "filter-q" }, "Nombre o título"), q),
    select("filter-format", "Formato", "format", [["", "Todos"], ["pdf", "PDF"], ["docx", "Word (DOCX)"], ["txt", "Texto (TXT)"]]),
    select("filter-status", "Estado", "status", [["", "Todos"], ["extracted", "Texto extraído"], ["needs_ocr", "Pendiente de OCR"], ["failed", "Error de lectura"]]),
    h("div", { class: "field filters-actions" }, h("button", { class: "btn btn-quiet", type: "submit" }, "Filtrar")),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    navigate(filtersPath({ q: (data.get("q") || "").trim(), format: data.get("format"), status: data.get("status"), page: 1 }));
  });
  return form;
}

function detailRow(doc, columns) {
  const warnings = (doc.metadata && doc.metadata.warnings) || [];
  const chunking = (doc.metadata && doc.metadata.chunking) || null;
  const items = [
    ["Identificador", h("code", {}, doc.doc_id)],
    ["Archivo original", doc.original_filename],
    ["SHA-256", h("code", { class: "wrap" }, doc.sha256)],
    ["Páginas", doc.page_count ?? "—"],
    ["Idioma", doc.language],
    ["Procedencia", doc.source_uri && doc.source_uri.startsWith("https://docs.google.com/") ? h("span", {}, SOURCE_LABELS[doc.source_type] || doc.source_type, ": ", h("a", { href: doc.source_uri, rel: "noopener noreferrer", target: "_blank" }, "enlace original")) : (SOURCE_LABELS[doc.source_type] || doc.source_type)],
    ["Fragmentación", chunking ? `${chunking.chunk_size} palabras con traslape de ${chunking.overlap}` : "—"],
    ["Actualizado", formatDate(doc.updated_at)],
  ];
  if (doc.extraction_error) items.push(["Error de extracción", doc.extraction_error]);
  if (warnings.length) items.push(["Avisos", warnings.join("; ")]);
  return h("tr", { class: "detail-row", hidden: true },
    h("td", { colspan: columns },
      h("dl", { class: "meta-grid" }, items.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
      h("p", {}, h("a", { class: "btn btn-quiet btn-small", href: `/documents/${doc.doc_id}/download` }, "Descargar original"))));
}

function documentTable(data) {
  const columns = 6;
  const body = h("tbody");
  for (const doc of data.items) {
    const detail = detailRow(doc, columns);
    const toggle = h("button", { class: "btn btn-quiet btn-small", type: "button", "aria-expanded": "false", "aria-label": `Detalles de ${doc.title}` }, "Detalles");
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      detail.hidden = !open;
    });
    const warnings = (doc.metadata && doc.metadata.warnings) || [];
    body.append(
      h("tr", {},
        h("th", { scope: "row" }, doc.title, h("span", { class: "sub" }, doc.original_filename)),
        h("td", {}, formatLabel(doc.mime_type)),
        h("td", { class: "num" }, formatBytes(doc.size_bytes)),
        h("td", { class: "num" }, formatDate(doc.created_at)),
        h("td", {}, statusTag(doc.extraction_status), warnings.length ? h("span", { class: "sub" }, `${warnings.length} aviso(s)`) : null),
        h("td", {}, toggle)),
      detail);
  }
  return h("div", { class: "table-wrap" },
    h("table", {},
      h("caption", { class: "visually-hidden" }, "Documentos cargados"),
      h("thead", {}, h("tr", {}, ["Documento", "Formato", "Tamaño", "Cargado", "Estado", ""].map((t, i) => h("th", { scope: "col" }, i === 5 ? h("span", { class: "visually-hidden" }, "Acciones") : t)))),
      body));
}

function pager(data, filters) {
  const first = data.total ? data.offset + 1 : 0;
  const last = data.offset + data.items.length;
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  return h("nav", { class: "pager", "aria-label": "Páginas de documentos" },
    h("p", { class: "num" }, `Mostrando ${first}–${last} de ${data.total}`),
    filters.page > 1 ? h("a", { class: "btn btn-quiet btn-small", href: `#${filtersPath({ ...filters, page: filters.page - 1 })}` }, "Anterior") : null,
    filters.page < pages ? h("a", { class: "btn btn-quiet btn-small", href: `#${filtersPath({ ...filters, page: filters.page + 1 })}` }, "Siguiente") : null);
}

export default {
  path: "/documentos",
  title: "Documentos",
  nav: { label: "Documentos", order: 20 },
  requires: "user",
  async render(main, _params, query) {
    const filters = readFilters(query);
    const listArea = h("section", { "aria-labelledby": "list-title" });
    const refresh = () => load();
    main.append(h("header", { class: "page-head" },
      h("h1", {}, "Documentos"),
      h("p", {}, isAdmin() ? "Cargue archivos, revise el resultado de la extracción y abra cada documento." : "Documentos disponibles para consulta. Solo el Administrador puede cargarlos.")));
    if (isAdmin()) main.append(h("div", { class: "grid-2 uploads" }, uploadSection(refresh), importSection(refresh)));
    main.append(listArea);

    async function load() {
      clear(listArea).append(h("h2", { id: "list-title" }, "Listado"), filterForm(filters), loading("Cargando documentos…"));
      try {
        const data = await api.get("/documents", { query: {
          limit: PAGE_SIZE, offset: (filters.page - 1) * PAGE_SIZE, order: "newest",
          q: filters.q, format: filters.format, status: filters.status,
        } });
        listArea.lastChild.remove();
        const filtered = filters.q || filters.format || filters.status;
        if (!data.total && !filtered) {
          listArea.append(emptyState("Aún no hay documentos", isAdmin() ? "Cargue un PDF, DOCX o TXT con el formulario de arriba." : "Cuando el Administrador cargue documentos aparecerán aquí."));
        } else if (!data.items.length) {
          listArea.append(emptyState("Ningún documento coincide", "Pruebe con otro nombre o quite los filtros.", h("a", { class: "btn btn-quiet", href: "#/documentos" }, "Quitar filtros")));
        } else {
          listArea.append(documentTable(data), pager(data, filters));
        }
      } catch (error) {
        listArea.lastChild.remove();
        listArea.append(notice("error", error.message));
      }
    }
    await load();
  },
};
