"""Adapters that normalise v0 (baseline) and v1 (production) to one `RunResult`.

Both packages are named `crag`, so each system must run in its own process; `V0System` puts the
baseline source on `sys.path` before the first `import crag`. Adapters never swallow a crash into a
success: if the pipeline raises, `crashed=True` and the exception text is kept. v0 has no recovery
code, so any provider fault that reaches it surfaces here.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .dataset import CORPUS_DIR, PROJECT_DIR

ABSTAIN_RE = re.compile(
    r"don'?t know|do not know|not contain|no information|cannot answer|does not provide|"
    r"doesn'?t provide|not mentioned|isn'?t (?:stated|mentioned|specified)|"
    r"not (?:stated|specified)",
    re.I,
)


@dataclass
class RunResult:
    id: str
    answer: str = ""
    retrieved_texts: list[str] = field(default_factory=list)  # rank-ordered
    context_texts: list[str] = field(default_factory=list)  # what the generator actually saw
    route: str = "local"  # local | web | abstain | local+web
    abstained: bool = False
    errors: list[str] = field(default_factory=list)
    crashed: bool = False
    exception: str | None = None
    latency_ms: float = 0.0
    llm_calls: int | None = None  # v1's logical LLM calls (v0 has no such counter)
    provider_calls: dict[str, int] = field(
        default_factory=dict
    )  # attempts per channel, both systems
    context_available: bool = True  # False: the system cannot say what the generator saw
    degraded: bool = False
    retries: int = 0


def context_texts_from(ans: Any) -> list[str] | None:
    """Texts the v1 generator actually saw, from `Answer.context` (local chunks graded relevant plus
    web chunks). None when the Answer has no such attribute: faithfulness is then unavailable. It
    must NOT fall back to `retrieved`, which includes chunks the generator never received."""
    ctx = getattr(ans, "context", None)
    if ctx is None:
        return None
    return [c.text if hasattr(c, "text") else str(c.get("text", "")) for c in ctx]


class System(Protocol):
    name: str

    def prepare(self) -> None: ...
    def run(self, qid: str, question: str) -> RunResult: ...
    def describe(self) -> dict[str, Any]: ...


def code_provenance(path: Path | str, src: Path | str) -> dict[str, Any]:
    """HEAD commit, whether the code under test has uncommitted changes, and a content hash of its
    .py files (the hash is what pins the code that actually ran, since HEAD alone may not)."""
    h = hashlib.sha256()
    for f in sorted(Path(src).rglob("*.py")):
        h.update(f.relative_to(src).as_posix().encode("utf-8"))
        h.update(hashlib.sha256(f.read_bytes()).digest())
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--", "."],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        dirty: bool | None = bool(out.stdout.strip())
    except Exception:
        dirty = None
    return {"commit": git_commit(path), "dirty": dirty, "src_tree_hash": h.hexdigest()}


def git_commit(path: Path | str) -> str:
    """HEAD commit of the repo containing `path` ('unknown' if git is unavailable)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


class V0System:
    """The original graph, imported from a read-only worktree. `src_path` is the `src` directory."""

    name = "v0"

    def __init__(
        self,
        src_path: Path | str,
        persist_dir: Path | str | None = None,
        corpus_dir: Path | str = CORPUS_DIR,
    ):
        self.src = Path(src_path).resolve()
        self.persist_dir = str(persist_dir or tempfile.mkdtemp(prefix="crag_v0_"))
        self.corpus_dir = str(corpus_dir)
        self._graph: Any = None

    def prepare(self) -> None:
        if "crag" in sys.modules:
            raise RuntimeError("crag already imported; run v0 and v1 in separate processes")
        sys.path.insert(0, str(self.src))
        os.environ["CRAG_PERSIST_DIR"] = self.persist_dir
        os.environ["CRAG_CORPUS_DIR"] = self.corpus_dir
        import crag

        if not Path(crag.__file__).resolve().is_relative_to(self.src):
            raise RuntimeError(f"imported crag from {crag.__file__}, expected under {self.src}")

    def build(self) -> None:
        """Ingest into the fresh temp store (call AFTER chaos.install: embeddings are fakes)."""
        import crag.ingest
        from crag.graph import build_graph

        crag.ingest.build_index(self.corpus_dir, self.persist_dir)
        self._graph = build_graph()

    def reset(self) -> None:
        """v0 keeps no state between questions."""

    def run(self, qid: str, question: str) -> RunResult:
        res = RunResult(id=qid)
        start = time.perf_counter()
        try:
            state = self._graph.invoke({"question": question, "steps": []})
        except Exception as exc:
            res.crashed, res.exception = True, f"{type(exc).__name__}: {exc}"[:300]
        else:
            res.answer = str(state.get("generation") or "")
            docs = state.get("documents", [])
            res.retrieved_texts = [d.page_content for d in docs]
            grades = state.get("grades") or []
            kept = [d for d, g in zip(docs, grades, strict=False) if g] if grades else list(docs)
            res.context_texts = [d.page_content for d in kept + list(state.get("web_results", []))]
            res.route = "web" if "web_search" in state.get("steps", []) else "local"
            res.abstained = bool(ABSTAIN_RE.search(res.answer))
        res.latency_ms = round((time.perf_counter() - start) * 1000.0, 1)
        return res

    def describe(self) -> dict[str, Any]:
        from crag.config import get_settings

        s = get_settings()
        return {
            **code_provenance(self.src, self.src),
            "llm_model": s.llm_model,
            "embed_model": s.embed_model,
            "top_k": s.top_k,
            "grader_model": s.llm_model,
        }


class V1System:
    """The production pipeline (`crag.pipeline.answer`). Needs `corrective-rag/src` importable."""

    name = "v1"

    def __init__(
        self,
        settings: Any = None,
        persist_dir: Path | str | None = None,
        corpus_dir: Path | str = CORPUS_DIR,
        **overrides: Any,
    ):
        self._settings = settings
        self._overrides = {
            "persist_dir": str(persist_dir or tempfile.mkdtemp(prefix="crag_v1_")),
            "corpus_dir": str(corpus_dir),
            "trace_dir": tempfile.mkdtemp(prefix="crag_v1_trace_"),
            **overrides,
        }

    def prepare(self) -> None:
        src = str(PROJECT_DIR / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from crag.config import Settings

        if self._settings is None:
            self._settings = Settings(_env_file=None, **self._overrides)

    def build(self) -> None:
        from crag.ingest import build_index

        build_index(self._settings, rebuild=True)
        self.reset()  # the web circuit breaker is module state; start every run closed

    def reset(self) -> None:
        """Between sweep points: close the web circuit breaker (module state in v1)."""
        try:
            from crag.nodes.web_search import reset_breaker

            reset_breaker()
        except ImportError:
            pass

    def run(self, qid: str, question: str) -> RunResult:
        from crag.pipeline import answer

        res = RunResult(id=qid)
        start = time.perf_counter()
        try:
            a = answer(question, settings=self._settings)
        except Exception as exc:
            res.crashed, res.exception = True, f"{type(exc).__name__}: {exc}"[:300]
        else:
            res.answer = a.answer or ""
            res.retrieved_texts = [
                c.text if hasattr(c, "text") else str(c.get("text", "")) for c in a.retrieved
            ]
            ctx = context_texts_from(a)
            res.context_available = ctx is not None
            res.context_texts = ctx or []
            res.route, res.abstained = a.route, bool(a.abstained)
            res.errors = list(a.errors)
            res.llm_calls = int(a.llm_calls)
            res.degraded, res.retries = bool(a.degraded), int(a.retries)
        res.latency_ms = round((time.perf_counter() - start) * 1000.0, 1)
        return res

    def describe(self) -> dict[str, Any]:
        s = self._settings
        return {
            **code_provenance(PROJECT_DIR / "src", PROJECT_DIR / "src"),
            "llm_model": s.llm_model,
            "embed_model": s.embed_model,
            "top_k": s.top_k,
            "grader_model": s.grader_model,
            "fallback_models": list(s.fallback_models),
        }
