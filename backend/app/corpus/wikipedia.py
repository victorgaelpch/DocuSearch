"""Corpus experimental de Wikipedia en español (DOC-05).

Flujo reproducible en tres pasos:

1. ``freeze``: a partir de ``corpus/wikipedia_es/topics.json`` (temas →
   categorías) se eligen artículos, se fija la **revisión** (``revid``) de cada
   uno y se escribe ``corpus/wikipedia_es/manifest.json`` (versionado).
2. ``build``: descarga exactamente esas revisiones mediante la API de
   MediaWiki, convierte el wikitexto a texto plano y verifica el SHA-256
   registrado. Los textos se guardan en ``data/corpus/wikipedia_es/`` (no
   versionado).
3. ``import``: carga los textos en la colección ``wikipedia_es`` del
   repositorio, separada de los documentos del usuario (``user``).

Filtros: textos vacíos, de menos de 50 palabras y duplicados (mismo
``pageid`` o mismo texto) se excluyen y se registran con su motivo.

Licencia del contenido: CC BY-SA 4.0 (Wikipedia). El manifiesto guarda la URL
de cada revisión para su atribución.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.app.nlp.normalization import clean_text

API_URL = "https://es.wikipedia.org/w/api.php"
SITE_URL = "https://es.wikipedia.org"
LICENSE = "CC BY-SA 4.0"
CONVERTER_VERSION = 1
MIN_WORDS = 50
DEFAULT_USER_AGENT = "academic-corpus-builder/0.1 (python-urllib)"
USER_AGENT_ENV = "DOCUSEARCH_WIKI_USER_AGENT"

_DROP_SECTIONS = re.compile(
    r"^(referencias|notas|bibliografía|enlaces externos|véase también|fuentes|"
    r"lecturas adicionales|notas y referencias|referencias y notas)$",
    re.IGNORECASE,
)
_NON_CONTENT_LINK = re.compile(r"^(archivo|file|imagen|image|categoría|category|anexo:)\s*:?", re.I)

JsonGetter = Callable[[dict[str, Any]], dict[str, Any]]


class WikipediaError(RuntimeError):
    """Error al consultar la API de Wikipedia."""


class ReconstructionError(RuntimeError):
    """El texto reconstruido no coincide con el manifiesto."""


# -- cliente HTTP ------------------------------------------------------------------


class WikipediaClient:
    """Cliente mínimo de la API de MediaWiki con pausas y reintentos."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval: float = 1.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        getter: Optional[JsonGetter] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._getter = getter or self._http_get
        self._sleep = sleep
        self._last_request = 0.0

    def _http_get(self, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
        request = urllib.request.Request(
            f"{API_URL}?{query}", headers={"User-Agent": self.user_agent}
        )
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            self._last_request = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    raise WikipediaError(f"HTTP {exc.code} en la API de Wikipedia") from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt * 5
                self._sleep(min(delay, 120))
            except urllib.error.URLError as exc:
                if attempt == self.max_retries:
                    raise WikipediaError(f"sin conexión con Wikipedia: {exc.reason}") from exc
                self._sleep(2**attempt * 2)
        raise WikipediaError("se agotaron los reintentos")  # pragma: no cover

    def get(self, **params: Any) -> dict[str, Any]:
        data = self._getter(params)
        if "error" in data:
            raise WikipediaError(f"error de la API: {data['error'].get('info', data['error'])}")
        return data

    def category_members(self, category: str, limit: int) -> list[dict[str, Any]]:
        """Artículos (espacio de nombres 0) de una categoría, en orden de la API."""
        members: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Categoría:{category}",
            "cmnamespace": 0,
            "cmtype": "page",
            "cmlimit": min(limit, 500),
            "cmsort": "sortkey",
        }
        while len(members) < limit:
            data = self.get(**params)
            members.extend(data.get("query", {}).get("categorymembers", []))
            if "continue" not in data:
                break
            params.update(data["continue"])
        return members[:limit]

    def latest_revisions(self, pageids: Sequence[int]) -> dict[int, dict[str, Any]]:
        """Revisión actual (contenido incluido) de hasta 50 páginas por petición."""
        result: dict[int, dict[str, Any]] = {}
        for batch in _batches(list(pageids), 50):
            data = self.get(
                action="query",
                prop="revisions",
                pageids="|".join(map(str, batch)),
                rvprop="ids|timestamp|content",
                rvslots="main",
            )
            for page in data.get("query", {}).get("pages", []):
                revisions = page.get("revisions") or []
                if revisions:
                    result[page["pageid"]] = _revision_record(page, revisions[0])
        return result

    def revisions_by_id(self, revids: Sequence[int]) -> dict[int, dict[str, Any]]:
        """Contenido de revisiones concretas (reconstrucción exacta)."""
        result: dict[int, dict[str, Any]] = {}
        for batch in _batches(list(revids), 50):
            data = self.get(
                action="query",
                prop="revisions",
                revids="|".join(map(str, batch)),
                rvprop="ids|timestamp|content",
                rvslots="main",
            )
            for page in data.get("query", {}).get("pages", []):
                for revision in page.get("revisions") or []:
                    record = _revision_record(page, revision)
                    result[record["revid"]] = record
        return result


def _batches(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _revision_record(page: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
    content = revision.get("slots", {}).get("main", {}).get("content", "")
    return {
        "pageid": page["pageid"],
        "title": page["title"],
        "revid": revision["revid"],
        "timestamp": revision.get("timestamp"),
        "wikitext": content,
    }


# -- conversión de wikitexto -----------------------------------------------------


def wikitext_to_text(wikitext: str) -> str:
    """Texto plano del cuerpo del artículo (sin plantillas, tablas ni referencias)."""
    import mwparserfromhell

    code = mwparserfromhell.parse(wikitext or "")
    # Cortar desde secciones finales sin contenido (Referencias, Enlaces externos...).
    for heading in code.filter_headings(recursive=False):
        if _DROP_SECTIONS.match(heading.title.strip_code().strip()):
            index = code.index(heading)
            del code.nodes[index:]
            break
    for template in code.filter_templates(recursive=False):
        _safe_remove(code, template)
    for tag in code.filter_tags(recursive=True):
        if str(tag.tag).lower() in {"ref", "references", "gallery", "table", "math", "score", "timeline"}:
            _safe_remove(code, tag)
    for link in code.filter_wikilinks(recursive=True):
        if _NON_CONTENT_LINK.match(str(link.title).strip()):
            _safe_remove(code, link)
    text = code.strip_code(normalize=True, collapse=True)
    text = re.sub(r"\{\|.*?\|\}", " ", text, flags=re.DOTALL)  # tablas residuales
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line and not line.startswith(("{|", "|", "!")))
    return clean_text(text)


def _safe_remove(code: Any, node: Any) -> None:
    try:
        code.remove(node)
    except ValueError:
        pass


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized_hash(text: str) -> str:
    return text_sha256(re.sub(r"\s+", " ", text.lower()).strip())


def revision_url(revid: int) -> str:
    return f"{SITE_URL}/w/index.php?oldid={revid}"


# -- freeze / build ----------------------------------------------------------------


@dataclass(frozen=True)
class TopicSpec:
    topic: str
    categories: tuple[str, ...]
    max_articles: int


def load_topics(path: Path) -> tuple[list[TopicSpec], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    per_topic = int(data.get("articles_per_topic", 40))
    specs = [
        TopicSpec(t["topic"], tuple(t["categories"]), int(t.get("max_articles", per_topic)))
        for t in data["topics"]
    ]
    return specs, data


def freeze(
    client: WikipediaClient,
    topics_path: Path,
    manifest_path: Path,
    texts_dir: Path,
    *,
    min_words: int = MIN_WORDS,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Selecciona artículos, fija sus revisiones y escribe el manifiesto."""
    import mwparserfromhell

    specs, topics_data = load_topics(topics_path)
    articles: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    seen_texts: dict[str, str] = {}
    texts_dir.mkdir(parents=True, exist_ok=True)

    for spec in specs:
        candidates: list[dict[str, Any]] = []
        for category in spec.categories:
            candidates.extend(client.category_members(category, spec.max_articles * 2))
        kept = 0
        pageids = []
        for member in candidates:
            if member["pageid"] in seen_pages:
                excluded.append({"title": member["title"], "topic": spec.topic, "reason": "duplicate_page"})
                continue
            seen_pages.add(member["pageid"])
            pageids.append(member["pageid"])
        revisions = client.latest_revisions(pageids)
        for pageid in pageids:
            if kept >= spec.max_articles:
                break
            record = revisions.get(pageid)
            if record is None:
                excluded.append({"pageid": pageid, "topic": spec.topic, "reason": "no_revision"})
                continue
            text = wikitext_to_text(record["wikitext"])
            reason = _exclusion_reason(record, text, seen_texts, min_words)
            if reason:
                excluded.append({"title": record["title"], "topic": spec.topic, "reason": reason})
                continue
            seen_texts[_normalized_hash(text)] = record["title"]
            (texts_dir / f"{record['pageid']}.txt").write_text(text, encoding="utf-8")
            articles.append(
                {
                    "title": record["title"],
                    "pageid": record["pageid"],
                    "revid": record["revid"],
                    "timestamp": record["timestamp"],
                    "topic": spec.topic,
                    "words": len(text.split()),
                    "sha256": text_sha256(text),
                    "url": revision_url(record["revid"]),
                }
            )
            kept += 1
        log(f"{spec.topic}: {kept} artículos")

    manifest = {
        "name": "wikipedia_es",
        "source": SITE_URL,
        "api": API_URL,
        "license": LICENSE,
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "converter": {
            "version": CONVERTER_VERSION,
            "mwparserfromhell": mwparserfromhell.__version__,
        },
        "filters": {"min_words": min_words, "dedupe": ["pageid", "normalized_text"], "empty": True},
        "topics_config": topics_data,
        "articles": articles,
        "excluded": excluded,
        "stats": compute_stats(articles, excluded),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _exclusion_reason(
    record: dict[str, Any], text: str, seen_texts: dict[str, str], min_words: int
) -> Optional[str]:
    wikitext = record["wikitext"].lstrip().lower()
    if wikitext.startswith(("#redirección", "#redirect")):
        return "redirect"
    if not text.strip():
        return "empty"
    if len(text.split()) < min_words:
        return f"short<{min_words}"
    if _normalized_hash(text) in seen_texts:
        return "duplicate_text"
    return None


def build(
    client: WikipediaClient,
    manifest_path: Path,
    texts_dir: Path,
    *,
    strict: bool = True,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Reconstruye los textos del manifiesto descargando las revisiones fijadas."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    texts_dir.mkdir(parents=True, exist_ok=True)
    by_revid = {a["revid"]: a for a in manifest["articles"]}
    records = client.revisions_by_id(list(by_revid))
    mismatched, missing = [], []
    for revid, article in by_revid.items():
        record = records.get(revid)
        if record is None:
            missing.append(article["title"])
            continue
        text = wikitext_to_text(record["wikitext"])
        if text_sha256(text) != article["sha256"]:
            mismatched.append(article["title"])
            if strict:
                continue
        (texts_dir / f"{article['pageid']}.txt").write_text(text, encoding="utf-8")
    report = {
        "articles": len(by_revid),
        "written": len(by_revid) - len(missing) - (len(mismatched) if strict else 0),
        "missing": missing,
        "hash_mismatch": mismatched,
    }
    log(json.dumps(report, ensure_ascii=False))
    if strict and (missing or mismatched):
        raise ReconstructionError(
            f"{len(missing)} revisiones no disponibles y {len(mismatched)} con hash distinto"
        )
    return report


def compute_stats(articles: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    words = [a["words"] for a in articles]
    by_topic = Counter(a["topic"] for a in articles)
    return {
        "articles": len(articles),
        "by_topic": dict(sorted(by_topic.items())),
        "words_total": sum(words),
        "words_mean": round(sum(words) / len(words), 1) if words else 0,
        "words_min": min(words) if words else 0,
        "words_max": max(words) if words else 0,
        "excluded": dict(sorted(Counter(e["reason"] for e in excluded).items())),
    }


def iter_corpus_texts(manifest_path: Path, texts_dir: Path) -> Iterable[tuple[dict[str, Any], str]]:
    """Pares (artículo del manifiesto, texto) verificando el hash."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for article in manifest["articles"]:
        path = texts_dir / f"{article['pageid']}.txt"
        if not path.is_file():
            raise FileNotFoundError(
                f"falta {path.name}; ejecute: python -m backend.app.cli corpus build"
            )
        text = path.read_text(encoding="utf-8")
        if text_sha256(text) != article["sha256"]:
            raise ReconstructionError(f"hash distinto para {article['title']}")
        yield article, text
