// Panel de evaluación (DOC-36): muestra tal cual los resultados versionados
// en evaluation/results/. Las lecturas se calculan con los p-valores del
// archivo, no se escriben a mano.
import { h, append, clear, loading, notice } from "../dom.js";
import { api } from "../api.js";

const METHOD_LABELS = { bm25: "BM25", tfidf: "TF-IDF", semantic: "Semántica", hybrid: "Híbrida" };
const METRIC_LABELS = { "recall@1": "Recall@1", "recall@5": "Recall@5", "recall@10": "Recall@10", "mrr@10": "MRR@10", "ndcg@10": "nDCG@10" };
const SUBSET_LABELS = { all: "Todas", miracl: "MIRACL", lexical: "Léxicas", paraphrase: "Paráfrasis" };

// 4 decimales: los archivos guardan 4; redondear a 3 daría cifras distintas según el lenguaje (0,7525)
const num = (v, digits = 4) => (v == null ? "—" : v.toLocaleString("es-MX", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const pval = (p) => (p === 0 ? "< 0,0001" : num(p, 4));

function metricsTable(item, subset, caption) {
  const metrics = Object.keys(METRIC_LABELS);
  const best = {};
  for (const metric of metrics) {
    best[metric] = Math.max(...item.methods.map((m) => (item.summary[m][subset] || {})[metric] ?? -1));
  }
  return h("div", { class: "table-wrap" }, h("table", {},
    h("caption", {}, caption),
    h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Método"), h("th", { scope: "col", class: "num" }, "Consultas"),
      metrics.map((m) => h("th", { scope: "col", class: "num" }, METRIC_LABELS[m])))),
    h("tbody", {}, item.methods.map((method) => {
      const row = item.summary[method][subset] || {};
      return h("tr", {}, h("th", { scope: "row" }, METHOD_LABELS[method] || method), h("td", { class: "num" }, row.queries ?? "—"),
        metrics.map((m) => h("td", { class: `num${row[m] === best[m] && item.methods.length > 1 ? " best" : ""}` }, num(row[m]))));
    }))));
}

function bars(item, metric = "ndcg@10") {
  const values = item.methods.map((m) => [m, (item.summary[m].all || {})[metric]]).filter(([, v]) => v != null);
  if (!values.length) return null;
  return h("figure", { class: "bars" },
    h("figcaption", {}, `${METRIC_LABELS[metric]} por método (todas las consultas)`),
    h("ul", {}, values.map(([m, v]) => h("li", {},
      h("span", { class: "bar-label" }, METHOD_LABELS[m] || m),
      h("span", { class: "bar-track", "aria-hidden": "true" }, h("span", { class: "bar-fill", dataset: { value: String(v) } })),
      h("span", { class: "bar-value num" }, num(v))))));
}

function significance(item) {
  const sig = item.significance;
  if (!sig) return h("p", { class: "hint" }, "Este archivo no incluye prueba de significación.");
  const base = METHOD_LABELS[sig.baseline] || sig.baseline;
  const readings = [];
  for (const method of item.methods.filter((m) => m !== sig.baseline)) {
    const ndcg = sig.comparisons.find((c) => c.method === method && c.metric === "ndcg@10");
    if (!ndcg) continue;
    const label = METHOD_LABELS[method] || method;
    readings.push(h("li", {}, ndcg.significant
      ? `${label} ${ndcg.mean_difference > 0 ? "supera" : "queda por debajo de"} ${base} en nDCG@10 de forma significativa (diferencia ${num(ndcg.mean_difference)}, p ${pval(ndcg.p_value)}).`
      : `${label} no difiere de forma significativa de ${base} en nDCG@10 (diferencia ${num(ndcg.mean_difference)}, p ${pval(ndcg.p_value)}).`));
  }
  return h("div", {},
    h("ul", { class: "readings" }, readings),
    h("details", {}, h("summary", {}, `Detalle de la prueba (${sig.test === "paired_permutation" ? "aleatorización pareada" : sig.test}, frente a ${base}, α = ${num(sig.alpha, 2)})`),
      h("div", { class: "table-wrap" }, h("table", {},
        h("caption", { class: "visually-hidden" }, "Comparaciones frente a la línea base"),
        h("thead", {}, h("tr", {}, ["Método", "Métrica", "Diferencia media", "Gana", "Pierde", "p", "¿Significativa?"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", {}, sig.comparisons.map((c) => h("tr", {},
          h("td", {}, METHOD_LABELS[c.method] || c.method), h("td", {}, METRIC_LABELS[c.metric] || c.metric),
          h("td", { class: "num" }, num(c.mean_difference, 4)), h("td", { class: "num" }, c.wins), h("td", { class: "num" }, c.losses),
          h("td", { class: "num" }, pval(c.p_value)), h("td", {}, c.significant ? "Sí" : "No"))))))));
}

function resultSection(item) {
  const human = item.annotation === "humana";
  const facts = [
    ["Archivo", h("code", {}, item.file)],
    ["Anotación", human ? "Humana (juicios de relevancia independientes)" : "Propia del equipo, sin revisión humana independiente"],
    ["Fecha", item.date || "No registrada"],
    ["Corpus", item.corpus || item.collection],
    ["Consultas", item.queries ?? "—"],
    ["Fragmentos indexados", item.chunks ?? "—"],
    ["Límites", item.limits || "—"],
  ];
  const subsets = item.subsets.filter((s) => s !== "all" && s !== "miracl");
  return h("section", { class: `evaluation ${item.primary ? "primary" : ""}`, "aria-labelledby": `eval-${item.id}` },
    h("h2", { id: `eval-${item.id}` }, item.title),
    human ? null : notice("warn", "Resultado secundario: consultas y relevancias escritas por el equipo. Úselo como apoyo, no como la medición principal."),
    h("dl", { class: "meta-grid" }, facts.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
    bars(item),
    metricsTable(item, "all", "Métricas con todas las consultas (la mejor de cada columna, en negrita)"),
    subsets.map((s) => h("details", {}, h("summary", {}, `Solo consultas: ${SUBSET_LABELS[s] || s}`), metricsTable(item, s, `Consultas ${SUBSET_LABELS[s] || s}`))),
    h("h3", {}, "Significación estadística"),
    significance(item));
}

export default {
  path: "/evaluacion",
  title: "Evaluación",
  nav: { label: "Evaluación", order: 50 },
  async render(main) {
    main.append(h("header", { class: "page-head" }, h("h1", {}, "Evaluación del buscador"),
      h("p", {}, "Resultados medidos y versionados en el repositorio (evaluation/results/). Se muestran tal cual; reproducirlos requiere los comandos de docs/evaluacion.md.")));
    const area = h("div", {});
    main.append(area);
    area.append(loading("Leyendo resultados…"));
    let data;
    try {
      data = await api.get("/evaluation");
    } catch (error) {
      clear(area).append(notice("error", error.message));
      return;
    }
    clear(area);
    if (!data.items.length) {
      area.append(h("div", { class: "empty" }, h("h2", {}, "No hay resultados de evaluación"), h("p", {}, "Ejecute python -m backend.app.cli evaluate con --output evaluation/results/… para generar uno.")));
      return;
    }
    const [primary, ...rest] = data.items;
    area.append(resultSection(primary));
    if (rest.length) {
      append(area, [h("h2", {}, "Otros resultados"),
        rest.map((item) => h("details", { class: "evaluation-more" }, h("summary", {}, item.title), resultSection(item)))]);
    }
    // ancho de las barras según el valor real (CSS custom property, sin estilos en línea en el HTML)
    for (const fill of area.querySelectorAll(".bar-fill")) fill.style.setProperty("--value", fill.dataset.value);
  },
};
