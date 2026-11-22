// Panel de índices y tareas de reindexación (DOC-31). Solo Administrador.
// El progreso se muestra solo cuando el servidor da una cifra real; si no,
// la barra queda indeterminada y el texto lo dice.
import { h, append, clear, announce, loading, notice } from "../dom.js";
import { api } from "../api.js";

const KINDS = {
  reindex: { label: "Reindexar", help: "Vuelve a extraer y fragmentar desde los originales y reconstruye BM25 y TF-IDF." },
  semantic: { label: "Sincronizar índice semántico", help: "Codifica solo los fragmentos nuevos o modificados (requiere el extra semantic)." },
  semantic_rebuild: { label: "Reconstruir índice semántico", help: "Codifica todos los fragmentos desde cero. Puede tardar varios minutos en CPU." },
  ocr: { label: "Reconocer PDF escaneados", help: "Aplica OCR a los documentos pendientes (requiere Tesseract con español)." },
};
const STATUS = { pending: "En cola", running: "En proceso", succeeded: "Terminada", failed: "Con errores" };
const COLLECTION_NAMES = { user: "Mis documentos", wikipedia_es: "Wikipedia en español (corpus de prueba)", miracl_es: "MIRACL español (evaluación)" };

function when(epoch) {
  return epoch ? new Date(epoch * 1000).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "medium" }) : "—";
}

function jobView(job) {
  const kind = KINDS[job.kind] ? KINDS[job.kind].label : job.kind;
  const box = h("div", { class: `job job-${job.status}`, dataset: { jobId: job.job_id } },
    h("p", { class: "job-title" }, h("strong", {}, kind), ` en ${COLLECTION_NAMES[job.collection] || job.collection}: `, h("span", { class: "job-status" }, STATUS[job.status] || job.status)));
  if (job.status === "running" || job.status === "pending") {
    const p = job.progress;
    const bar = p && p.total > 0
      ? h("progress", { max: p.total, value: p.done, "aria-label": "Avance de la tarea" })
      : h("progress", { "aria-label": "Tarea en proceso, sin medida de avance" });
    box.append(bar, h("p", { class: "hint num" },
      job.step ? `${job.step}. ` : "",
      p && p.total > 0 ? `${p.done} de ${p.total} documento(s).` : job.status === "pending" ? "Esperando a que termine otra tarea." : "Sin medida de avance para este paso."));
  }
  if (job.status === "succeeded" || job.status === "failed") {
    const r = job.result || {};
    const lines = [];
    if (r.documents !== undefined) lines.push(`${r.documents} documento(s) refragmentados, ${r.chunks} fragmento(s).`);
    if (r.index_version) lines.push(`Versión del índice léxico: ${r.index_version}.`);
    if (r.total !== undefined && r.added !== undefined) lines.push(`Índice semántico: ${r.total} vector(es); ${r.added} añadido(s), ${r.removed} retirado(s), ${r.kept} conservado(s).`);
    if (r.version && r.total !== undefined) lines.push(`Versión del índice semántico: ${r.version}.`);
    if (r.pending !== undefined) lines.push(`OCR: ${r.pending} pendiente(s), ${(r.recognized || []).length} reconocido(s), ${(r.still_pending || []).length} sin texto.`);
    if (job.duration_s != null) lines.push(`Duración: ${job.duration_s.toLocaleString("es-MX")} s.`);
    box.append(h("ul", { class: "job-result" }, lines.map((l) => h("li", {}, l))));
    if (job.error) box.append(notice("error", job.error));
    const failed = r.failed ? Object.entries(r.failed) : [];
    if (failed.length) box.append(h("ul", { class: "job-failures" }, failed.map(([id, msg]) => h("li", {}, h("code", {}, id), `: ${msg}`))));
  }
  return box;
}

function semanticCell(semantic, available) {
  if (!available) return h("span", { class: "tag tag-warn" }, "No instalada");
  if (!semantic.built) return h("span", { class: "tag" }, semantic.error || "Sin construir");
  return h("span", {},
    h("span", { class: `tag ${semantic.in_sync ? "tag-ok" : "tag-warn"}` }, semantic.in_sync ? "Sincronizado" : "Desactualizado"),
    h("span", { class: "sub num" }, `${semantic.chunks} vector(es)${semantic.pending_chunks ? `, ${semantic.pending_chunks} pendiente(s)` : ""}${semantic.stale_entries ? `, ${semantic.stale_entries} obsoleto(s)` : ""}`),
    semantic.version ? h("span", { class: "sub" }, "Versión ", h("code", {}, semantic.version)) : null);
}

export default {
  path: "/indices",
  title: "Índices",
  nav: { label: "Índices", order: 40 },
  requires: "admin",
  async render(main) {
    let timer = null;
    const tracked = new Set();
    const panel = h("section", { "aria-labelledby": "collections-title" });
    const jobsArea = h("section", { "aria-labelledby": "jobs-title", "aria-live": "polite" });
    main.append(
      h("header", { class: "page-head" }, h("h1", {}, "Índices"),
        h("p", {}, "Estado de cada colección y tareas de reindexación. Las búsquedas siguen respondiendo con el índice anterior mientras se reconstruye uno nuevo.")),
      panel, jobsArea,
      h("section", { "aria-labelledby": "cli-title" },
        h("h2", { id: "cli-title" }, "Respaldo por terminal"),
        h("p", {}, "Si el panel no responde o falta un componente opcional, las mismas tareas se pueden ejecutar con el servidor detenido:"),
        h("pre", { class: "code" }, h("code", {}, "python -m backend.app.cli reindex --collection user\npython -m backend.app.cli semantic-index --collection user\npython -m backend.app.cli ocr --collection user"))),
    );

    async function startJob(collection, kind, button) {
      button.disabled = true;
      try {
        const job = await api.post(`/admin/indexes/${encodeURIComponent(collection)}/jobs`, { json: { kind } });
        tracked.add(job.job_id);
        announce(`${KINDS[kind].label}: tarea iniciada`);
        await refresh();
      } catch (error) {
        button.disabled = false;
        panel.prepend(notice("error", error.code === "job_running" ? "Ya hay una tarea en curso en esa colección; espere a que termine." : error.message));
      }
    }

    function collectionCard(info, available) {
      const busy = Boolean(info.active_job);
      const actions = Object.entries(KINDS)
        .filter(([kind]) => kind !== "ocr" || info.needs_ocr > 0)
        .map(([kind, meta]) => {
          const button = h("button", { class: "btn btn-quiet btn-small", type: "button", disabled: busy || ((kind === "semantic" || kind === "semantic_rebuild") && !available), title: meta.help }, meta.label);
          button.addEventListener("click", () => startJob(info.collection, kind, button));
          return h("li", {}, button, h("span", { class: "hint" }, meta.help));
        });
      return h("article", { class: "sheet collection" },
        h("h3", {}, COLLECTION_NAMES[info.collection] || info.collection),
        h("dl", { class: "meta-grid" },
          h("dt", {}, "Documentos"), h("dd", { class: "num" }, String(info.documents)),
          h("dt", {}, "Fragmentos"), h("dd", { class: "num" }, String(info.chunks)),
          h("dt", {}, "Pendientes de OCR"), h("dd", { class: "num" }, String(info.needs_ocr)),
          h("dt", {}, "Índice léxico"), h("dd", {}, info.lexical ? h("span", {}, `${info.lexical.methods.map((m) => ({ bm25: "BM25", tfidf: "TF-IDF" })[m] || m).join(" y ")}, versión `, h("code", {}, info.lexical.version)) : "Reconstruyéndose"),
          h("dt", {}, "Índice semántico"), h("dd", {}, semanticCell(info.semantic, available))),
        busy ? h("p", { class: "hint" }, "Hay una tarea en curso en esta colección.") : null,
        h("ul", { class: "job-actions" }, actions));
    }

    async function refresh() {
      let data;
      try {
        data = await api.get("/admin/indexes");
      } catch (error) {
        clear(panel).append(notice("error", error.message));
        return;
      }
      append(clear(panel), [h("h2", { id: "collections-title" }, "Colecciones"),
        h("p", { class: "hint" }, `Modelo de embeddings: ${data.embedding_model.name} (revisión ${data.embedding_model.revision.slice(0, 8)}). Se ejecuta una tarea a la vez para no saturar la CPU ni la memoria.`),
        data.semantic_available ? null : notice("warn", "La búsqueda semántica no está instalada en este servidor. BM25 y TF-IDF funcionan; instale el extra con python -m pip install -e \".[semantic]\"."),
        h("div", { class: "grid-2" }, data.collections.map((c) => collectionCard(c, data.semantic_available)))]);
      for (const job of data.recent_jobs) if (job.status === "pending" || job.status === "running") tracked.add(job.job_id);
      clear(jobsArea).append(h("h2", { id: "jobs-title" }, "Tareas recientes"),
        data.recent_jobs.length ? h("div", { class: "jobs" }, data.recent_jobs.map(jobView)) : h("p", { class: "hint" }, "Todavía no se ha ejecutado ninguna tarea desde que se inició el servidor."));
      // se sigue consultando mientras cualquier tarea o tarjeta indique trabajo en curso
      const active = data.recent_jobs.some((j) => j.status === "pending" || j.status === "running")
        || data.collections.some((c) => c.active_job);
      window.clearTimeout(timer);
      if (active) timer = window.setTimeout(refresh, 1000);
      else for (const job of data.recent_jobs) {
        if (tracked.has(job.job_id)) { tracked.delete(job.job_id); announce(`Tarea ${STATUS[job.status].toLowerCase()}`); }
      }
    }

    panel.append(loading("Consultando el estado de los índices…"));
    await refresh();
    return () => window.clearTimeout(timer);
  },
};
