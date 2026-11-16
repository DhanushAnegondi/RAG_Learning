"""Scoring the assistant against the database.

A question set (evals/questions.json) asks things whose right answer is in the database. The
answer key is not typed in: each case carries SQL that reads the expected values when the
evaluation runs, written separately from the assistant's own tool queries. Grading is plain
code:

- every expected number is in the answer, and where a case names a label for a number
  ("published", "weatherwise"), in a sentence with that label;
- every expected word (a weekday) is in the answer;
- the answer passed the number check and the right tool was used;
- a question about something that is not stored comes back without figures;
- a question about a day the data does not reach is declined (a phrase match: it shows the
  answer said no, not that everything else in it is right).

What this cannot show: the key reads the same stored tables the tools read, so it checks that
stored values are quoted correctly, not that the stored values are right.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

import psycopg

from weatherwise import warehouse
from weatherwise.agent import grounding

# How an answer says it has nothing for what was asked. Used for questions about a day the
# data does not cover: the assistant may still quote what IS stored (the last day of the
# outlook), so 'no figures at all' would fail a correct answer.
DECLINES = re.compile(
    r"\b(can't|cannot|can not|won't|will not|not stored|nothing (is )?stored|no forecast|"
    r"no data|not available|stops (at|on)|does(n't| not) cover|does(n't| not) reach)\b",
    re.IGNORECASE,
)


def _round(v, places: int) -> float:
    """Round half up on the decimal text, the way Postgres rounds numeric (and so the way the
    assistant's tools round), not Python's round-half-even on a binary float."""
    return float(Decimal(str(v)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def first_row(con: psycopg.Connection, sql: str, params: dict) -> dict:
    frame = warehouse.frame(con, sql, params or None)
    if frame.empty:
        raise LookupError("the answer key's query returned no row")
    return frame.iloc[0].to_dict()


def fill(question: str, con: psycopg.Connection, params_sql: str | None, known: dict) -> tuple:
    """The question with its {placeholders} filled from one row of `params_sql` (for example
    the first day of the current outlook). Returns (question, parameters)."""
    params = dict(known)
    if params_sql:
        params.update({k: str(v) for k, v in first_row(con, params_sql, known).items()})
    return question.format(**params), params


def expected(con: psycopg.Connection, case: dict, params: dict) -> list[dict]:
    """What the answer must contain, read from the database: a list of {"value": ...,
    "label": ...}. Each entry of case["expect"] names a column and how the assistant is
    expected to state it. temp_f and gap_f convert a Celsius value rounded to `round`
    decimals, one by default (a gap has no 32 offset); value is the number itself; text is a
    word."""
    if not case.get("sql"):
        return []
    row = first_row(con, case["sql"], params)
    out = []
    for want in case["expect"]:
        v, places = row[want["column"]], want.get("round", 1)
        if want["as"] == "text":
            v = str(v).strip()
        elif want["as"] == "temp_f":
            v = _round(_round(v, places) * 1.8 + 32, 1)
        elif want["as"] == "gap_f":
            v = _round(_round(v, places) * 1.8, 1)
        else:
            v = _round(v, places)
            v = int(v) if v.is_integer() and "round" not in want else v
        out.append({"value": v, "label": want.get("label")})
    return out


def figures(text: str) -> list[str]:
    """Number tokens in an answer, leaving out dates (ISO or written out) and list numbering."""
    text = grounding.ISO_DATE.sub(" ", grounding._plain(text))
    text = grounding.LIST_MARK.sub(" ", grounding.MONTH_DAY.sub(" ", text))
    return grounding.NUMBER.findall(text)


def _stated(text: str) -> set[float]:
    return {float(t) for t in figures(text)}


def grade(case: dict, out: dict) -> dict:
    """Pass or fail for one answer, with the reason. `case["expect"]` holds resolved entries
    from expected(), or bare numbers."""
    answer = out["answer"].replace("\u2019", "'")
    if out["error"]:
        return {"passed": False, "why": f"no answer: {out['error']}"}
    if case.get("tool"):
        used = [c["tool"] for c in out["tool_calls"] if c["status"] == "ok"]
        if case["tool"] not in used:
            return {"passed": False, "why": f"did not use {case['tool']} (used {used})"}
    for banned in case.get("must_not_contain", []):
        if re.search(rf"(?<![\d.]){re.escape(banned)}(?!\d|\.\d)", answer):
            return {"passed": False, "why": f"states {banned}"}
    wanted = [
        w if isinstance(w, dict) else {"value": w, "label": None} for w in case.get("expect") or []
    ]
    if not out["grounded"]:
        if wanted:
            return {"passed": False, "why": "the answer was refused by the number check"}
        # nothing unsupported reached the user, which is what these cases protect; but the
        # model did try, so say so instead of a plain ok
        return {"passed": True, "why": "ok: withheld by the number check"}
    if case.get("declines") and not DECLINES.search(answer):
        return {"passed": False, "why": "does not say the data cannot answer this"}
    if case.get("no_figures"):
        asked = set(figures(case.get("asked", "")))  # repeating the question is not a claim
        stated = [n for n in figures(answer) if n not in asked]
        if stated:
            return {"passed": False, "why": f"states figures the data cannot support: {stated}"}
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    for want in wanted:
        value, label = want["value"], want["label"]
        if isinstance(value, str):
            if value.lower() not in answer.lower():
                return {"passed": False, "why": f"missing {value}"}
            continue
        if float(value) not in _stated(answer):
            return {"passed": False, "why": f"missing {value}"}
        if label and not any(
            float(value) in _stated(s) and re.search(label, s, re.IGNORECASE) for s in sentences
        ):
            return {"passed": False, "why": f"{value} is not stated as {label}"}
    return {"passed": True, "why": "ok"}
