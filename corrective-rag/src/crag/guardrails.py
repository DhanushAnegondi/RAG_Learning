"""Input validation, prompt-injection hygiene for context, and citation checking.

Retrieved and web text is untrusted. It is wrapped in `<doc id="N" ...>` blocks and the system
prompt tells the model to treat it as data. `format_context` also neutralises a closing `</doc`
tag inside the text so a document cannot break out of its block.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from langchain_core.documents import Document

_CITE_GROUP_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def validate_question(question: str, max_chars: int) -> str:
    """Strip and validate user input. Raises ValueError (the only error `answer()` raises)."""
    if not isinstance(question, str):
        raise ValueError("question must be a string")
    q = question.strip()
    if not q:
        raise ValueError("question must not be empty")
    if len(q) > max_chars:
        raise ValueError(f"question is too long ({len(q)} > {max_chars} characters)")
    return q


def _attr(value: object) -> str:
    return str(value or "").replace('"', "'").replace("\n", " ")[:200]


_CLOSER_RE = re.compile(r"<\s*/\s*doc", re.I)


def escape_doc_text(text: str) -> str:
    """Neutralise any closing `</doc` (any case, any inner whitespace) in untrusted text.

    One helper for every place document text enters a prompt (grader, generator), so a document
    cannot close its own block and smuggle instructions outside it."""
    return _CLOSER_RE.sub(lambda _m: "<\\/doc", text)


def format_context(docs: Sequence[Document]) -> str:
    """Number documents from 1 and wrap each in a `<doc>` block."""
    blocks = []
    for i, d in enumerate(docs, start=1):
        body = escape_doc_text(d.page_content)
        blocks.append(
            f'<doc id="{i}" source="{_attr(d.metadata.get("source"))}" '
            f'section="{_attr(d.metadata.get("section"))}">\n{body}\n</doc>'
        )
    return "\n\n".join(blocks)


def _ids(group: str) -> list[int]:
    return [int(x) for x in group.split(",")]


def check_citations(text: str, n_docs: int) -> tuple[list[int], list[int]]:
    """Return (valid cited ids, invalid cited ids), each unique and in order of appearance.

    Valid means 1..n_docs, i.e. a document that was actually in the prompt."""
    cited: list[int] = []
    invalid: list[int] = []
    for m in _CITE_GROUP_RE.finditer(text):
        for cid in _ids(m.group(1)):
            bucket = cited if 1 <= cid <= n_docs else invalid
            if cid not in bucket:
                bucket.append(cid)
    return cited, invalid


def strip_invalid_citations(text: str, n_docs: int) -> str:
    """Remove `[N]` markers that point at no document; keep the valid ones."""

    def fix(m: re.Match[str]) -> str:
        keep = [i for i in _ids(m.group(2)) if 1 <= i <= n_docs]
        return f"{m.group(1)}[{', '.join(map(str, keep))}]" if keep else ""

    return re.sub(r"( ?)" + _CITE_GROUP_RE.pattern, fix, text)
