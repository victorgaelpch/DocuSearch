// Buscador web: BM25, TF-IDF, semántica e híbrida (DOC-29).
// Muestra el ranking real de GET /search, sin reordenar ni normalizar puntuaciones.
import { h, clear, announce, loading, notice } from "../dom.js";
import { api, session } from "../api.js";
import { navigate } from "../router.js";

export const METHODS = {
  bm25: { label: "BM25 (palabras clave)", short: "BM25", scale: "BM25: suma de pesos de los términos de la consulta; no tiene máximo fijo y depende del corpus." },
  tfidf: { label: "TF-IDF (palabras clave)", short: "TF-IDF", scale: "TF-IDF: similitud coseno entre vectores de términos, entre 0 y 1." },
  semantic: { label: "Semántica (por significado)", short: "Semántica", scale: "Semántica: similitud coseno entre embeddings normalizados, entre 0 y 1 (solo se muestran valores positivos)." },
  hybrid: { label: "Híbrida (BM25 + semántica)", short: "Híbrida", scale: "Híbrida: fusión por rango recíproco (RRF, k=60); valores pequeños, del orden de 0,01 a 0,03, que solo ordenan." },
};

const COLLECTIONS = {
  user: "Mis documentos",
  wikipedia_es: "Corpus de prueba: Wikipedia en español",
};

function normalizeWord(word) {
  return word.toLocaleLowerCase("es").normalize("NFD").replace(/[̀-ͯ]/g, "");
}

// Resalta en el fragmento las palabras que aparecen literalmente en la consulta.
// Es una ayuda visual: el ranking lo decide el servidor (lematización, embeddings).
export function highlightSnippet(snippet, query) {
  const terms = new Set(query.split(/[^\p{L}\p{N}]+/u).filter((w) => w.length >= 3).map(normalizeWord));
  const nodes = [];
  if (!terms.size) return [snippet];
  const parts = snippet.split(/([\p{L}\p{N}]+)/u);
  for (const part of parts) {
    if (!part) continue;
    nodes.push(terms.has(normalizeWord(part)) ? h("mark", {}, part) : part);
  }
  return nodes;
}

function readParams(query) {
  const method = METHODS[query.get("method")] ? query.get("method") : "bm25";
  const k = Math.min(100, Math.max(1, Number.parseInt(query.get("k") || "10", 10) || 10));
  const wanted = query.get("collection");
  const collection = COLLECTIONS[wanted] ? wanted : session().authenticated ? "user" : "wikipedia_es";
  return { q: (query.get("q") || "").trim(), method, k, collection, compare: query.get("compare") === "1" };
}

function searchPath(params) {
  const p = new URLSearchParams({ q: params.q, method: params.method, k: String(params.k), collection: params.collection });
  if (params.compare) p.set("compare", "1");
  return `/buscar?${p.toString()}`;
}

function formatScore(score) {
  return score.toLocaleString("es-MX", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

function resultItem(hit, query, canOpen) {
  const pages = hit.page_start == null ? "sin paginación" : hit.page_start === hit.page_end ? `página ${hit.page_start}` : `páginas ${hit.page_start}–${hit.page_end}`;
  const href = `#/documentos/${encodeURIComponent(hit.doc_id)}?chunk=${encodeURIComponent(hit.chunk_id)}`;
  return h("li", { class: "hit" },
    h("div", { class: "hit-rank num", "aria-hidden": "true" }, String(hit.rank)),
    h("div", { class: "hit-body" },
      h("h3", {}, canOpen ? h("a", { href }, hit.title) : hit.title),
      h("p", { class: "hit-snippet" }, ...highlightSnippet(hit.snippet, query)),
      h("p", { class: "hit-meta num" },
        h("span", {}, `Posición ${hit.rank}`), h("span", {}, `Puntuación ${formatScore(hit.score)}`),
        h("span", {}, hit.original_filename), h("span", {}, pages))));
}

function resultsBlock(data, params, canOpen) {
  const method = METHODS[data.method];
  const header = h("div", { class: "results-head" },
    h("h2", {}, method.short),
    h("p", { class: "num" }, `${data.total} resultado(s) en ${data.took_ms.toLocaleString("es-MX")} ms`));
  if (!data.results.length) {
    return h("section", { class: "results", "aria-label": `Resultados ${method.short}` }, header,
      h("div", { class: "empty" }, h("h2", {}, "Sin resultados"),
        h("p", {}, data.method === "bm25" || data.method === "tfidf"
          ? "Ningún fragmento contiene los términos de la consulta. Pruebe otras palabras o la búsqueda semántica o híbrida."
          : "Ningún fragmento se parece lo suficiente a la consulta. Pruebe con otras palabras.")));
  }
  return h("section", { class: "results", "aria-label": `Resultados ${method.short}` }, header,
    h("ol", { class: "hits" }, data.results.map((hit) => resultItem(hit, params.q, canOpen))));
}

function errorBlock(error, method) {
  if (error.code === "semantic_unavailable") {
    return h("div", { class: "notice notice-warn", role: "alert" },
      h("p", {}, `La búsqueda ${METHODS[method].short.toLowerCase()} no está disponible en este servidor: ${error.message}.`),
      h("p", {}, "Instale el extra opcional con ", h("code", {}, 'python -m pip install -e ".[semantic]"'), " o use BM25, que funciona sin él."));
  }
  if (error.code === "not_authenticated") return notice("error", "Inicie sesión para buscar en sus documentos.");
  return notice("error", error.message);
}

async function runSearch(params) {
  return api.get("/search", { query: { q: params.q, method: params.method, k: params.k, collection: params.collection } });
}

export default {
  path: "/buscar",
  title: "Buscar",
  nav: { label: "Buscar", order: 15 },
  async render(main, _params, query) {
    const params = readParams(query);
    const authed = session().authenticated;
    if (params.q) document.title = `${params.q} · Buscar · DocuSearch`;

    const q = h("input", { id: "q", name: "q", type: "search", value: params.q, maxlength: 500, required: true, autocomplete: "off", "aria-describedby": "q-error" });
    const qError = h("p", { id: "q-error", class: "field-error", hidden: true });
    const method = h("select", { id: "method", name: "method" },
      Object.entries(METHODS).map(([value, m]) => h("option", { value, selected: value === params.method }, m.label)));
    const k = h("input", { id: "k", name: "k", type: "number", min: 1, max: 100, value: params.k, inputmode: "numeric" });
    const collection = h("select", { id: "collection", name: "collection" },
      Object.entries(COLLECTIONS)
        .filter(([value]) => authed || value !== "user")
        .map(([value, label]) => h("option", { value, selected: value === params.collection }, label)));
    const compare = h("input", { id: "compare", name: "compare", type: "checkbox", checked: params.compare });
    const form = h("form", { class: "search-form sheet", role: "search", "aria-label": "Buscar en documentos", novalidate: true },
      h("div", { class: "field search-q" }, h("label", { for: "q" }, "Consulta en español"), h("div", { class: "search-row" }, q, h("button", { class: "btn", type: "submit" }, "Buscar")), qError),
      h("div", { class: "search-options" },
        h("div", { class: "field" }, h("label", { for: "method" }, "Método"), method),
        h("div", { class: "field" }, h("label", { for: "k" }, "Resultados"), k),
        h("div", { class: "field" }, h("label", { for: "collection" }, "Colección"), collection),
        h("div", { class: "field check" }, compare, h("label", { for: "compare" }, "Comparar con BM25"))));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = q.value.trim();
      if (!text) {
        qError.textContent = "Escriba una consulta.";
        qError.hidden = false;
        q.setAttribute("aria-invalid", "true");
        q.focus();
        return;
      }
      const kValue = Number.parseInt(k.value, 10);
      if (!(kValue >= 1 && kValue <= 100)) {
        qError.textContent = "El número de resultados debe estar entre 1 y 100.";
        qError.hidden = false;
        k.focus();
        return;
      }
      navigate(searchPath({ q: text, method: method.value, k: kValue, collection: collection.value, compare: compare.checked }));
    });

    main.append(h("header", { class: "page-head" }, h("h1", {}, "Buscar"),
      h("p", {}, authed ? "Busque en sus documentos o en el corpus de prueba. Cada resultado abre el documento en el fragmento encontrado." : "Sin sesión solo puede buscar en el corpus público de prueba. Inicie sesión para buscar en sus documentos.")), form);

    const output = h("div", { class: "search-output", "aria-live": "polite" });
    main.append(output);
    if (!params.q) return;

    const canOpen = authed;
    const methods = params.compare && params.method !== "bm25" ? [params.method, "bm25"] : [params.method];
    output.append(loading(params.method === "semantic" || params.method === "hybrid" ? "Buscando… la primera búsqueda semántica carga el modelo y puede tardar." : "Buscando…"));
    const settled = await Promise.allSettled(methods.map((m) => runSearch({ ...params, method: m })));
    clear(output);
    let indexEmpty = false;
    if (settled.some((r) => r.status === "fulfilled" && !r.value.total)) {
      // distinguir "sin coincidencias" de "colección sin documentos indexados"
      try {
        const info = await api.get("/search/index", { query: { collection: params.collection } });
        indexEmpty = info.chunks === 0;
      } catch { /* se muestra el estado sin coincidencias */ }
    }
    if (indexEmpty) {
      output.append(h("div", { class: "empty" }, h("h2", {}, "Esta colección no tiene documentos indexados"),
        h("p", {}, params.collection === "user"
          ? "Cargue documentos en la sección Documentos; se indexan al cargarlos."
          : "Importe el corpus de prueba con python -m backend.app.cli corpus import (ver docs/corpus.md).")));
      announce("La colección no tiene documentos indexados");
      return;
    }
    const blocks = settled.map((result, i) => (result.status === "fulfilled" ? resultsBlock(result.value, params, canOpen) : errorBlock(result.reason, methods[i])));
    output.append(h("div", { class: methods.length > 1 ? "compare-grid" : "" }, blocks));
    const used = methods.map((m) => h("li", {}, METHODS[m].scale));
    output.append(h("details", { class: "score-help" }, h("summary", {}, "Cómo leer la puntuación"),
      h("p", {}, "Cada método usa su propia escala, así que las puntuaciones de métodos distintos no se comparan entre sí: compare posiciones. La calidad medida de cada método está en docs/evaluacion.md."),
      h("ul", {}, used)));
    const ok = settled.filter((r) => r.status === "fulfilled").map((r) => r.value.total);
    announce(ok.length ? `${ok[0]} resultado(s) para «${params.q}»` : "La búsqueda no se pudo completar");
  },
};
