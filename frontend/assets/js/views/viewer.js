// Visor de documentos: metadatos, texto extraído con el fragmento resaltado y
// vista previa del PDF (DOC-28). El texto se inserta siempre como nodos de
// texto, de modo que el contenido del documento nunca se interpreta como HTML.
import { h, clear, announce, formatBytes, formatDate, loading, notice } from "../dom.js";
import { api } from "../api.js";
import { SOURCE_LABELS, formatLabel, statusInfo } from "../format.js";

function pagesLabel(chunk) {
  if (!chunk || chunk.page_start == null) return null;
  return chunk.page_start === chunk.page_end ? `página ${chunk.page_start}` : `páginas ${chunk.page_start}–${chunk.page_end}`;
}

function setQuietQuery(docId, chunkId) {
  // actualiza la dirección sin volver a renderizar (replaceState no emite hashchange)
  const hash = `#/documentos/${encodeURIComponent(docId)}${chunkId ? `?chunk=${encodeURIComponent(chunkId)}` : ""}`;
  window.history.replaceState(null, "", hash);
}

function metadataList(doc) {
  const warnings = (doc.metadata && doc.metadata.warnings) || [];
  const rows = [
    ["Identificador", h("code", {}, doc.doc_id)],
    ["Archivo original", doc.original_filename],
    ["Formato", formatLabel(doc.mime_type)],
    ["Tamaño", formatBytes(doc.size_bytes)],
    ["Páginas", doc.page_count ?? "Sin paginación"],
    ["Estado", statusInfo(doc.extraction_status).label],
    ["Procedencia", SOURCE_LABELS[doc.source_type] || doc.source_type],
    ["Cargado", formatDate(doc.created_at)],
    ["SHA-256", h("code", { class: "wrap" }, doc.sha256)],
  ];
  if (warnings.length) rows.push(["Avisos", warnings.join("; ")]);
  if (doc.extraction_error) rows.push(["Error de extracción", doc.extraction_error]);
  return h("details", { class: "meta-details" },
    h("summary", {}, "Metadatos del documento"),
    h("dl", { class: "meta-grid" }, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])));
}

export default {
  path: "/documentos/:id",
  title: "Documento",
  requires: "user",
  async render(main, params, query) {
    const docId = params.id;
    main.append(loading("Abriendo documento…"));
    let doc;
    let content;
    try {
      [doc, content] = await Promise.all([api.get(`/documents/${encodeURIComponent(docId)}`), api.get(`/documents/${encodeURIComponent(docId)}/text`)]);
    } catch (error) {
      clear(main).append(h("h1", {}, "No se pudo abrir el documento"),
        notice("error", error.status === 404 || error.status === 422 ? "El documento no existe o fue eliminado." : error.message),
        h("p", {}, h("a", { href: "#/documentos" }, "Volver a documentos")));
      return;
    }
    clear(main);
    document.title = `${doc.title} · DocuSearch`;
    const isPdf = doc.mime_type === "application/pdf";
    const chunks = content.chunks;
    const requested = query.get("chunk");
    let index = Math.max(0, chunks.findIndex((c) => c.chunk_id === requested));
    if (requested && !chunks.some((c) => c.chunk_id === requested)) index = -1;

    main.append(
      h("p", { class: "crumbs" }, h("a", { href: "#/documentos" }, "Documentos")),
      h("header", { class: "page-head viewer-head" },
        h("h1", {}, doc.title),
        h("p", {}, `${doc.original_filename}, ${formatLabel(doc.mime_type)}, ${formatBytes(doc.size_bytes)}`, doc.page_count ? `, ${doc.page_count} página(s)` : ""),
        h("p", { class: "actions" }, h("a", { class: "btn btn-quiet btn-small", href: `/documents/${encodeURIComponent(doc.doc_id)}/download` }, "Descargar original"))),
    );
    if (requested && index === -1) {
      main.append(notice("warn", "El fragmento indicado ya no existe en este documento (puede que se haya reindexado). Se muestra el texto completo."));
      index = 0;
    }
    if (doc.extraction_status === "needs_ocr") {
      main.append(notice("warn", "Este PDF está escaneado y todavía no tiene texto reconocido, así que no aparece en las búsquedas. Instale Tesseract con el idioma español y ejecute ", h("code", {}, "python -m backend.app.cli ocr"), ". Mientras tanto puede verlo o descargarlo."));
    }
    main.append(metadataList(doc));

    // Selector de vista: texto o PDF
    const textPanel = h("section", { id: "panel-text", "aria-label": "Texto extraído" });
    const pdfPanel = h("section", { id: "panel-pdf", "aria-label": "Vista previa del PDF", hidden: true });
    const textButton = h("button", { type: "button", class: "seg", "aria-pressed": "true", "aria-controls": "panel-text" }, "Texto extraído");
    const pdfButton = isPdf ? h("button", { type: "button", class: "seg", "aria-pressed": "false", "aria-controls": "panel-pdf" }, "Vista del PDF") : null;
    const show = (which) => {
      const pdf = which === "pdf";
      textPanel.hidden = pdf;
      pdfPanel.hidden = !pdf;
      textButton.setAttribute("aria-pressed", String(!pdf));
      if (pdfButton) pdfButton.setAttribute("aria-pressed", String(pdf));
      if (pdf) loadPdf();
    };
    textButton.addEventListener("click", () => show("text"));
    if (pdfButton) pdfButton.addEventListener("click", () => show("pdf"));
    if (isPdf) main.append(h("div", { class: "segmented", role: "group", "aria-label": "Forma de ver el documento" }, textButton, pdfButton));

    // Panel de texto con el fragmento resaltado
    const position = h("p", { class: "chunk-position num", "aria-live": "polite" });
    const prev = h("button", { type: "button", class: "btn btn-quiet btn-small" }, "Fragmento anterior");
    const next = h("button", { type: "button", class: "btn btn-quiet btn-small" }, "Fragmento siguiente");
    const textBox = h("div", { class: "doc-text", tabindex: "0", role: "document", "aria-label": `Texto de ${doc.title}` });
    const paint = (focusMark) => {
      clear(textBox);
      const chunk = chunks[index];
      if (!chunk) { textBox.append(content.text); return; }
      const mark = h("mark", { id: "hl" }, content.text.slice(chunk.char_start, chunk.char_end));
      textBox.append(content.text.slice(0, chunk.char_start), mark, content.text.slice(chunk.char_end));
      const pages = pagesLabel(chunk);
      position.textContent = `Fragmento ${chunk.ordinal + 1} de ${chunks.length}${pages ? `, ${pages}` : ""}`;
      prev.disabled = index === 0;
      next.disabled = index === chunks.length - 1;
      mark.scrollIntoView({ block: "center", behavior: "auto" });
      if (focusMark) announce(position.textContent);
    };
    prev.addEventListener("click", () => { index -= 1; setQuietQuery(doc.doc_id, chunks[index].chunk_id); paint(true); });
    next.addEventListener("click", () => { index += 1; setQuietQuery(doc.doc_id, chunks[index].chunk_id); paint(true); });

    if (!content.text) {
      textPanel.append(h("div", { class: "empty" }, h("h2", {}, "Sin texto extraído"),
        h("p", {}, isPdf ? "Use la vista del PDF o descargue el original." : "El archivo no contiene texto extraíble.")));
    } else {
      textPanel.append(h("div", { class: "chunk-nav" }, position, prev, next), textBox);
    }

    // Panel PDF: se carga solo cuando se abre
    let pdfLoaded = false;
    const loadPdf = () => {
      if (pdfLoaded) return;
      pdfLoaded = true;
      const chunk = chunks[index];
      const page = Number.parseInt(query.get("page") || "", 10) || (chunk && chunk.page_start) || 1;
      pdfPanel.append(
        h("p", { class: "hint" }, `Se abre en la página ${page}. Si la vista previa no aparece, su navegador no muestra PDF incrustados: use «Descargar original».`),
        h("iframe", { class: "pdf-frame", title: `Vista previa de ${doc.title}`, src: `/documents/${encodeURIComponent(doc.doc_id)}/content#page=${page}` }));
    };

    main.append(textPanel, pdfPanel);
    if (content.text) paint(false);
    if (isPdf && (!content.text || query.get("view") === "pdf")) show("pdf");
  },
};
