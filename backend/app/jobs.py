"""Tareas de indexación en segundo plano con estado real (DOC-31).

* Un solo hilo trabajador procesa las tareas en orden: en una computadora
  personal sin GPU, dos reconstrucciones a la vez solo compiten por CPU y RAM.
* Como máximo una tarea pendiente o en curso por colección (409 si no).
* Estados: ``pending`` → ``running`` → ``succeeded`` | ``failed``. El éxito
  se informa solo cuando la tarea terminó; el progreso solo existe cuando hay
  una cifra real (documentos procesados / total), si no queda ``None``.
* Las tareas viven en memoria: reiniciar el servidor las olvida (una tarea
  interrumpida no deja índices a medias porque cada paso escribe de forma
  atómica). Para trabajos largos existe la CLI (``python -m backend.app.cli``).
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobKind(str, Enum):
    REINDEX = "reindex"  # refragmentar desde los originales y reconstruir BM25/TF-IDF
    SEMANTIC = "semantic"  # sincronizar el índice FAISS (requiere el extra semantic)
    SEMANTIC_REBUILD = "semantic_rebuild"  # reconstruir FAISS desde cero
    OCR = "ocr"  # reconocer PDF escaneados pendientes


ACTIVE = (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass
class Job:
    job_id: str
    kind: JobKind
    collection: str
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    progress: Optional[dict[str, int]] = None
    step: Optional[str] = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind.value,
            "collection": self.collection,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round((self.finished_at or time.time()) - self.started_at, 2) if self.started_at else None,
            "progress": dict(self.progress) if self.progress else None,
            "step": self.step,
            "steps": [dict(s) for s in self.steps],
            "result": self.result,
            "error": self.error,
        }


class JobConflictError(RuntimeError):
    def __init__(self, job: Job) -> None:
        super().__init__(f"ya hay una tarea {job.status.value} en {job.collection}")
        self.job = job


class JobContext:
    """Lo que ve la función de una tarea: informar paso y progreso real."""

    def __init__(self, job: Job, lock: threading.Lock) -> None:
        self._job = job
        self._lock = lock

    def step(self, text: str) -> None:
        with self._lock:
            self._close_step()
            self._job.step = text
            self._job.progress = None

    def _close_step(self) -> None:
        if self._job.step is not None:
            self._job.steps.append({"step": self._job.step, "progress": self._job.progress})

    def progress(self, done: int, total: int) -> None:
        with self._lock:
            self._job.progress = {"done": int(done), "total": int(total)}


JobFunction = Callable[[JobContext], dict[str, Any]]


class JobManager:
    """Cola de tareas con un trabajador; conserva las últimas ``history`` tareas."""

    def __init__(self, history: int = 50) -> None:
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._functions: dict[str, JobFunction] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._history = history
        self._worker = threading.Thread(target=self._run, name="docusearch-jobs", daemon=True)
        self._worker.start()

    def submit(self, kind: JobKind, collection: str, function: JobFunction) -> Job:
        with self._lock:
            for job in self._jobs.values():
                if job.collection == collection and job.status in ACTIVE:
                    raise JobConflictError(job)
            job = Job(job_id=uuid.uuid4().hex, kind=kind, collection=collection)
            self._jobs[job.job_id] = job
            self._functions[job.job_id] = function
            self._trim()
        self._queue.put(job.job_id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.as_dict() if job else None

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return [job.as_dict() for job in reversed(list(self._jobs.values()))][:limit]

    def active(self, collection: str) -> Optional[dict[str, Any]]:
        with self._lock:
            for job in self._jobs.values():
                if job.collection == collection and job.status in ACTIVE:
                    return job.as_dict()
        return None

    def wait(self, job_id: str, timeout: float = 30.0) -> Optional[dict[str, Any]]:
        """Espera a que termine (útil en pruebas y en la CLI)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            snapshot = self.snapshot(job_id)
            if snapshot is None or snapshot["status"] not in (s.value for s in ACTIVE):
                return snapshot
            time.sleep(0.02)
        return self.snapshot(job_id)

    def _trim(self) -> None:
        while len(self._jobs) > self._history:
            oldest_id, oldest = next(iter(self._jobs.items()))
            if oldest.status in ACTIVE:
                break
            del self._jobs[oldest_id]

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            with self._lock:
                job = self._jobs.get(job_id)
                function = self._functions.pop(job_id, None)
                if job is None or function is None:
                    continue
                job.status = JobStatus.RUNNING
                job.started_at = time.time()
            context = JobContext(job, self._lock)
            try:
                result = function(context)
            except Exception as exc:  # el error se informa, no se oculta
                with self._lock:
                    context._close_step()
                    job.step = None
                    job.status = JobStatus.FAILED
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.result = {"trace": traceback.format_exc(limit=3).splitlines()[-1]}
                    job.finished_at = time.time()
                continue
            with self._lock:
                context._close_step()
                job.result = result
                job.status = JobStatus.FAILED if result.get("failed") else JobStatus.SUCCEEDED
                if job.status is JobStatus.FAILED:
                    job.error = f"{len(result['failed'])} documento(s) no se pudieron procesar"
                job.finished_at = time.time()
                job.step = None
