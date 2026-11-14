"""Turn spoken numbers into digits: "two thousand four" -> 2004, "twenty twenty seven" -> 2027,
"eight point four" -> 8.4, "six months" -> "6 months". Used for validation, grounding and as an LLM hint."""
from __future__ import annotations

import re

UNITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
WORDS = set(UNITS) | set(TENS) | {"hundred", "thousand", "point", "and", "dot"}


def _int_words(toks):
    """Parse a plain integer made of number words; None if not parseable."""
    total, cur, seen = 0, 0, False
    for t in toks:
        if t == "and":
            continue
        if t in UNITS:
            cur += UNITS[t]
        elif t in TENS:
            cur += TENS[t]
        elif t == "hundred":
            cur = max(cur, 1) * 100
        elif t == "thousand":
            total += max(cur, 1) * 1000
            cur = 0
        else:
            return None
        seen = True
    return total + cur if seen else None


def _convert_run(toks):
    toks = [t for t in toks if t != "and"] if "point" in toks or "dot" in toks else toks
    for sep in ("point", "dot"):
        if sep in toks:                               # eight point four -> 8.4
            i = toks.index(sep)
            whole, frac = _int_words(toks[:i]), toks[i + 1:]
            if whole is None or not frac or any(t not in UNITS or UNITS[t] > 9 for t in frac):
                return None
            return f"{whole}." + "".join(str(UNITS[t]) for t in frac)
    # year style: "twenty twenty seven", "twenty twenty-seven", "nineteen ninety nine"
    if len(toks) >= 3 and toks[0] in ("twenty", "nineteen") and "hundred" not in toks and "thousand" not in toks:
        head = 20 if toks[0] == "twenty" else 19
        tail = _int_words(toks[1:])
        if tail is not None and 0 <= tail <= 99 and (toks[1] in TENS or toks[1] in UNITS):
            return str(head * 100 + tail)
    if len(toks) >= 2 and toks[0] in ("twenty", "nineteen") and toks[1] in UNITS and toks[1] in ("oh", "zero") and len(toks) == 3:
        return str((20 if toks[0] == "twenty" else 19) * 100 + UNITS[toks[2]])
    n = _int_words(toks)
    return None if n is None else str(n)


def numberize(text: str) -> str:
    """Replace every run of number words in the text with digits (everything else untouched)."""
    if not text:
        return text or ""
    toks = list(re.finditer(r"[A-Za-z]+", text))
    out, pos, k = [], 0, 0
    while k < len(toks):
        m = toks[k]
        w = m.group().lower()
        if w not in WORDS or w in ("and", "dot", "oh"):
            k += 1
            continue
        j = k
        while j + 1 < len(toks) and toks[j + 1].group().lower() in WORDS                 and re.fullmatch(r"[\s\-]+", text[toks[j].end():toks[j + 1].start()]):
            j += 1
        run = [t.group().lower() for t in toks[k:j + 1]]
        while run and run[-1] in ("and", "dot", "oh"):      # a trailing connector is not part of the number
            run.pop(); j -= 1
        conv = _convert_run(run) if run else None
        if conv is None:
            k += 1
            continue
        out.append(text[pos:m.start()] + conv)
        pos = toks[j].end()
        k = j + 1
    out.append(text[pos:])
    return "".join(out)
