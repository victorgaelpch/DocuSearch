// Etiquetas legibles compartidas por las vistas (DOC-27).
export const FORMAT_LABELS = {
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (DOCX)",
  "text/plain": "Texto (TXT)",
};

export const STATUS = {
  extracted: { label: "Texto extraído", tag: "tag-ok" },
  needs_ocr: { label: "Pendiente de OCR", tag: "tag-warn" },
  pending: { label: "En proceso", tag: "" },
  empty: { label: "Sin texto", tag: "tag-warn" },
  failed: { label: "Error de lectura", tag: "tag-error" },
};

export const SOURCE_LABELS = { upload: "Carga", google_docs: "Google Docs", corpus: "Corpus" };

export function formatLabel(mime) { return FORMAT_LABELS[mime] || mime; }
export function statusInfo(status) { return STATUS[status] || { label: status, tag: "" }; }
