"""The number check: every number in an answer must come from a tool result, a tool argument
or the user's own words. Enforced in code after the model answers, not only asked for.

Deliberately strict. A number the model works out itself (a sum, a unit conversion, a rounded
value) is rejected even when it is right, because nothing here can tell a correct sum from an
invented figure. Tools return the derived values the assistant is expected to quote.

What it does not do: it reads digits, not meaning. It cannot tell that a supported number is
attached to the wrong day, it ignores the sign, and it does not look at words.
"""

import re

ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
LIST_MARK = re.compile(r"(?m)^\s*\d+[.)]\s")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?(?!\.\d)"
MONTH_DAY = re.compile(rf"\b{_MONTH}\s+{_DAY}\b|\b{_DAY}\s+{_MONTH}\b", re.IGNORECASE)


def _plain(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,756 -> 1756


def _written(m: re.Match) -> tuple[int, int]:
    """(month, day) of a date written out, e.g. 'Nov 15' or '15 November'."""
    month, day = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return MONTHS.index(month.lower()[:3]) + 1, int(day)


def source_numbers(sources: list[str]) -> tuple[set[float], set[tuple[int, int]]]:
    """Numbers and ISO dates found in the sources. Of a date, only the year counts as a number;
    its month and day support a date written out ("Nov 15"), never a bare 15. A date the
    user wrote out ("December 25") is a source for that date too."""
    values, dates, days = set(), set(), set()
    for text in sources:
        text = _plain(text)
        for y, m, d in ISO_DATE.findall(text):
            dates.add((int(y), int(m), int(d)))
            days.add((int(m), int(d)))
            values.add(float(y))
        days.update(_written(m) for m in MONTH_DAY.finditer(text) if 1 <= _written(m)[1] <= 31)
        values.update(float(n) for n in NUMBER.findall(ISO_DATE.sub(" ", text)))
    return values, dates, days


def unsupported(answer: str, sources: list[str]) -> list[str]:
    """Numbers and dates in the answer that no source contains, in order of appearance. A whole
    number must match a source number exactly; a number written with decimals is supported by
    a source number that rounds to it."""
    values, dates, month_days = source_numbers(sources)
    text = _plain(answer)
    bad = ["-".join(d) for d in ISO_DATE.findall(text) if tuple(map(int, d)) not in dates]
    text = ISO_DATE.sub(" ", text)

    def written_date(m: re.Match) -> str:
        month, day = _written(m)
        if not 1 <= day <= 31:
            return m.group(0)  # "may 70": not a date, leave the number to be checked
        if (month, day) not in month_days:
            bad.append(m.group(0))
        return " "

    text = LIST_MARK.sub(" ", MONTH_DAY.sub(written_date, text))
    for token in NUMBER.findall(text):
        decimals = len(token.partition(".")[2])
        slack = 0.5 * 10**-decimals + 1e-9 if decimals else 1e-9
        if not any(abs(v - float(token)) <= slack for v in values) and token not in bad:
            bad.append(token)
    return bad
