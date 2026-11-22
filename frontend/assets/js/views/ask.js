// Preguntas con respuestas citadas (DOC-39). La respuesta se muestra como
// texto; solo las citas [S#] devueltas por el servidor se convierten en
// enlaces al fragmento real. Sin modelo configurado, se ofrece el buscador.
import { h, append, clear, announce, loading, notice } from "../dom.js";
import { api } from "../api.js";
import { navigate } from "../router.js";

const STATUS_TEXT = {
  insufficient_evidence: "El modelo indicó que los fragmentos recuperados no contienen información suficiente para responder.",
  unsupported: "El modelo respondió sin citar ninguno de los fragmentos recuperados, así que la respuesta se descartó. Revise los fragmentos directamente.",
  no_evidence: "No se encontró ningún fragmento relacionado con la pregunta, así que no se generó respuesta.",
};

function pages(c) {
  if (c.page_start == null) return "";
  return c.page_start === c.page_end ? `, página ${c.page_start}` : `, páginas ${c.page_start}–${c.page_end}`;
}

function sourceHref(c) {
  return `#/documentos/${encodeURIComponent(c.doc_id)}?chunk=${encodeURIComponent(c.chunk_id)}`;
}

function answerWithLinks(answer, citations) {
  const byMarker = new Map(citations.map((c) => [c.marker, c]));
  const nodes = [];
  for (const part of answer.split(/(\[S\d{1,3}\])/)) {
    const marker = part.match(/^\[(S\d{1,3})\]$/);
    const citation = marker && byMarker.get(marker[1]);
    if (citation) nodes.push(h("a", { href: sourceHref(citation), class: "cite", "aria-label": `Fuente ${marker[1]}: ${citation.title}${pages(citation)}` }, part));
    else if (part) nodes.push(part);
  }
  return nodes;
}

function sourceList(items, label) {
  return h("ol", { class: "sources", "aria-label": label }, items.map((c) => h("li", { value: Number(c.marker.slice(1)) },
    h("a", { href: sourceHref(c) }, `[${c.marker}] ${c.title}`), h("span", { class: "sub" }, `${c.original_filename}${pages(c)}`),
    h("p", { class: "hit-snippet" }, c.snippet))));
}

function feedbackBox(result) {
  const box = h("div", { class: "feedback", role: "group", "aria-label": "¿Le resultó útil la respuesta?" }, h("span", {}, "¿Le resultó útil?"));
  for (const [rating, label] of [["util", "Sí"], ["no_util", "No"]]) {
    const button = h("button", { class: "btn btn-quiet btn-small", type: "button" }, label);
    button.addEventListener("click", async () => {
      try {
        await api.post("/ask/feedback", { json: { rating, status: result.status, citations: result.citations.length } });
        clear(box).append(h("span", {}, "Gracias. Se registró la opinión, sin el texto de la pregunta."));
      } catch (error) {
        clear(box).append(notice("error", error.message));
      }
    });
    box.append(button);
  }
  return box;
}

function resultView(result) {
  const parts = [];
  if (result.status === "answered") {
    parts.push(
      h("div", { class: "notice notice-warn" }, h("p", {}, result.disclaimer)),
      h("section", { class: "sheet answer", "aria-labelledby": "answer-title" },
        h("h2", { id: "answer-title" }, "Respuesta"),
        h("p", { class: "answer-text" }, ...answerWithLinks(result.answer, result.citations)),
        h("h3", {}, "Fuentes citadas"),
        sourceList(result.citations, "Fuentes citadas")),
    );
    if (result.invalid_citations) {
      parts.push(notice("warn", `Se quitaron ${result.invalid_citations} cita(s) a fuentes que no se recuperaron.`));
    }
  } else {
    parts.push(notice("warn", STATUS_TEXT[result.status] || "Sin respuesta."));
  }
  if (result.sources.length) {
    parts.push(h("details", { class: "score-help" }, h("summary", {}, `Fragmentos recuperados (${result.sources.length}, método ${result.retrieval.method.toUpperCase()})`),
      sourceList(result.sources, "Fragmentos recuperados")));
  }
  const timing = [`Recuperación: ${result.retrieval.took_ms.toLocaleString("es-MX")} ms`];
  if (result.generation) timing.push(`generación: ${(result.generation.took_ms / 1000).toLocaleString("es-MX", { maximumFractionDigits: 1 })} s con ${result.generation.model}`);
  parts.push(h("p", { class: "hint num" }, `${timing.join("; ")}.`));
  if (result.generation) parts.push(feedbackBox(result));
  return parts;
}

export default {
  path: "/preguntar",
  title: "Preguntar",
  nav: { label: "Preguntar", order: 17 },
  requires: "user",
  async render(main) {
    main.append(h("header", { class: "page-head" }, h("h1", {}, "Preguntar a los documentos"),
      h("p", {}, "Un modelo de lenguaje local responde usando solo los fragmentos recuperados y cita cada uno. Es una función opcional: la búsqueda funciona sin ella.")));
    const statusArea = h("div", {}, loading("Comprobando el modelo local…"));
    main.append(statusArea);
    let status;
    try {
      status = await api.get("/ask/status");
    } catch (error) {
      clear(statusArea).append(notice("error", error.message));
      return;
    }
    clear(statusArea);

    const question = h("textarea", { id: "question", rows: 3, maxlength: 500, required: true, "aria-describedby": "question-hint" });
    const collection = h("select", { id: "ask-collection" }, h("option", { value: "user" }, "Mis documentos"), h("option", { value: "wikipedia_es" }, "Corpus de prueba: Wikipedia en español"));
    const method = h("select", { id: "ask-method" }, h("option", { value: "hybrid" }, "Híbrida (recomendada)"), h("option", { value: "bm25" }, "BM25"), h("option", { value: "semantic" }, "Semántica"));
    const error = h("p", { class: "field-error", role: "alert", hidden: true });
    const submit = h("button", { class: "btn", type: "submit" }, "Preguntar");
    const searchInstead = h("button", { class: "btn btn-quiet", type: "button" }, "Buscar en su lugar");
    const form = h("form", { class: "sheet search-form", novalidate: true, "aria-label": "Hacer una pregunta" },
      h("div", { class: "field" }, h("label", { for: "question" }, "Pregunta"), question,
        h("p", { id: "question-hint", class: "hint" }, "Ejemplo: ¿qué abastece de agua potable a las ciudades?"), error),
      h("div", { class: "search-options" },
        h("div", { class: "field" }, h("label", { for: "ask-collection" }, "Colección"), collection),
        h("div", { class: "field" }, h("label", { for: "ask-method" }, "Recuperación"), method)),
      h("p", { class: "actions" }, submit, searchInstead));
    const output = h("div", { "aria-live": "polite" });

    searchInstead.addEventListener("click", () => {
      const q = question.value.trim();
      navigate(q ? `/buscar?q=${encodeURIComponent(q)}&method=bm25&k=10&collection=${collection.value}` : "/buscar"); // BM25 funciona siempre
    });

    if (!status.configured || status.reachable === false || status.model_available === false) {
      const reason = !status.configured
        ? "No hay un modelo local configurado en este servidor."
        : status.reachable === false ? `El modelo local no responde (${status.detail || "Ollama detenido"}).`
          : `El modelo ${status.model} no está descargado en Ollama (ollama pull ${status.model}).`;
      main.append(h("div", { class: "notice notice-warn", role: "status" },
        h("p", {}, reason, " Mientras tanto puede usar el buscador, incluida la búsqueda semántica o híbrida."),
        h("p", {}, "Configuración: docs/rag.md (Ollama en 127.0.0.1; los documentos no salen de esta computadora).")));
      if (!status.configured) {
        submit.disabled = true;
      }
    }
    main.append(form, output);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.hidden = true;
      const text = question.value.trim();
      if (text.length < 3) {
        error.textContent = "Escriba una pregunta de al menos 3 caracteres.";
        error.hidden = false;
        question.focus();
        return;
      }
      submit.disabled = true;
      clear(output).append(loading("Recuperando fragmentos y generando la respuesta… en CPU puede tardar un minuto."));
      try {
        const result = await api.post("/ask", { json: { question: text, collection: collection.value, method: method.value, k: 5 } });
        append(clear(output), resultView(result));
        announce(result.status === "answered" ? `Respuesta con ${result.citations.length} fuente(s)` : "Sin respuesta respaldada");
      } catch (err) {
        clear(output).append(notice("error", err.code === "rag_busy" ? "Ya se está generando otra respuesta; espere unos segundos." : err.message));
      } finally {
        submit.disabled = !status.configured;
      }
    });
  },
};
