"""Language detection and digit normalisation.

Reply language follows the customer (STY-4): Hindi (Devanagari),
Hinglish (Latin script with Hindi words) or English.
Devanagari digits are normalised to ASCII for parsing, but verification
values are kept as strings so leading zeros ('0783') survive.
"""
from __future__ import annotations

import re

DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

HINGLISH_MARKERS = {
    "hai", "hain", "kya", "mujhe", "mera", "meri", "kab", "kaise", "kitne",
    "chahiye", "vapas", "wala", "wali", "aaya", "gaya", "kar", "karo", "do",
    "na", "pe", "ka", "ki", "ko", "se", "mein", "aur", "nahi", "abhi",
    "rupaye", "saman", "aakhri", "theek", "achha", "shuru", "hua", "beech",
}


def normalize_digits(text: str) -> str:
    return text.translate(DEV_DIGITS)


def detect_language(text: str) -> str:
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    if len(words & HINGLISH_MARKERS) >= 2:
        return "hi-en"
    return "en"


def has_devanagari(text: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", text))


# ---------------------------------------------------------------------------
# ASR transcript normalisation (Step 4): Gnani STT output spells numbers
# out and splits some words - the practice set's asr_text column shows the
# exact failure modes: 'ele-zero zero one to' for ELE-0012, 're fund' for
# refund, 'u p i' for UPI, '...october to zero to six' for October 2026.
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "to": "2",
                "three": "3", "four": "4", "for": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "ate": "8", "nine": "9"}
_DIGIT_SEQ = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|oh|to|for|ate)"
_MONTH_RE = (r"(january|february|march|april|may|june|july|august|"
             r"september|october|november|december)")


_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}
_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
          "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def _ordinal_value(words: list[str]) -> int | None:
    if len(words) == 1:
        return _ORDINALS.get(words[0]) or _UNITS.get(words[0])
    if len(words) == 2 and words[0] in _TENS:
        u = _ORDINALS.get(words[1]) or _UNITS.get(words[1])
        if u and u < 10:
            return _TENS[words[0]] + u
    return None


def _spoken_year(words: list[str]) -> int | None:
    """'twenty twenty six' / 'twenty six' style years -> 2026."""
    if words and words[0] == "twenty":
        rest = words[1:]
        if not rest:
            return 2000
        if len(rest) == 1 and rest[0] in _TENS:
            return 2000 + _TENS[rest[0]]
        if len(rest) == 1 and rest[0] in _UNITS:
            return 2000 + _UNITS[rest[0]]
        if len(rest) == 2 and rest[0] in _TENS and rest[1] in _UNITS:
            return 2000 + _TENS[rest[0]] + _UNITS[rest[1]]
    return None


_ORDINAL_RE = (r"(?:(?:twenty|thirty)[-\s]+)?(?:first|second|third|fourth|"
               r"fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|"
               r"thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
               r"eighteenth|nineteenth|twentieth|thirtieth)")
_YEAR_SPOKEN_RE = (r"(?:twenty\s+(?:twenty|thirty|forty|fifty|sixty|seventy|"
                   r"eighty|ninety)(?:[-\s](?:one|two|three|four|five|six|"
                   r"seven|eight|nine))?|twenty\s+(?:one|two|three|four|"
                   r"five|six|seven|eight|nine))")


def _word_dates_to_digits(t: str) -> str:
    """Real STT spells dates out: 'seventeenth october twenty twenty six'
    -> '17 October 2026'. Handles day-first and month-first orders."""
    def build(day_words: str, month_name: str, year_words: str | None) -> str:
        day = _ordinal_value(day_words.lower().replace("-", " ").split())
        year = _spoken_year(year_words.lower().replace("-", " ").split()) \
            if year_words else 2026
        if day is None or year is None:
            return f"{day_words} {month_name}"
        return f"{day} {month_name} {year}"

    def repl_df(m: re.Match) -> str:
        return build(m.group(1), m.group(2), m.group(3))

    def repl_mf(m: re.Match) -> str:
        return build(m.group(2), m.group(1), m.group(3))

    t = re.sub(r"\b(" + _ORDINAL_RE + r")\s+" + _MONTH_RE +
               r"(?:\s+(" + _YEAR_SPOKEN_RE + r"))?",
               repl_df, t, flags=re.I)
    t = re.sub(r"\b" + _MONTH_RE + r"\s+(" + _ORDINAL_RE + r")" +
               r"(?:,?\s+(" + _YEAR_SPOKEN_RE + r"))?",
               repl_mf, t, flags=re.I)
    return t


def _cardinals_to_digits(t: str) -> str:
    """Standalone cardinal words -> digits ('fourteen' -> 14,
    'twenty six' -> 26) so 'Kestrel Book fourteen' matches the catalog."""
    tens = r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    unit = r"(?:one|two|three|four|five|six|seven|eight|nine)"
    small = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
             r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
             r"eighteen|nineteen)")

    def repl(m: re.Match) -> str:
        words = m.group(0).lower().replace("-", " ").split()
        if len(words) == 2 and words[0] in _TENS:
            u = _UNITS.get(words[1])
            if u is not None and u < 10:
                return str(_TENS[words[0]] + u)
        if len(words) == 1:
            # NB: _UNITS["zero"] is 0, which is falsy — must test for None,
            # not truthiness, or 'zero' survives and breaks digit runs.
            v = _TENS.get(words[0])
            if v is None:
                v = _UNITS.get(words[0])
            if v is not None:
                return str(v)
            return words[0]
        return m.group(0)
    t = re.sub(r"\b" + tens + r"[-\s]" + unit + r"\b", repl, t, flags=re.I)
    # not when hyphenated into a compound word ('One-piece Swimsuit')
    t = re.sub(r"\b(?:" + tens + r"|" + small + r")\b(?![-])", repl, t, flags=re.I)
    return t


def normalize_asr(text: str) -> str:
    t = text
    t = re.sub(r"\bre\s+fund\b", "refund", t, flags=re.I)
    t = re.sub(r"\bu\s+p\s+i\b", "UPI", t, flags=re.I)
    t = re.sub(r"\bkurtha\b", "kurta", t, flags=re.I)


    def sku_repl(m: re.Match) -> str:
        words = re.split(r"[-\s]+", m.group(2).strip())
        digits = "".join(_DIGIT_WORDS[w.lower()] for w in words)
        return f"{m.group(1).upper()}-{digits}"
    t = re.sub(r"\b(ele|bks|fsh|hom|bty|gro|inr|dgt)[-\s]("
               + _DIGIT_SEQ + r"(?:[-\s]+" + _DIGIT_SEQ + r"){3})\b",
               sku_repl, t, flags=re.I)

    def year_repl(m: re.Match) -> str:
        words = re.split(r"[-\s]+", m.group(2).strip())
        if len(words) != 4:
            return m.group(0)
        digits = "".join(_DIGIT_WORDS[w.lower()] for w in words)
        return f"{m.group(1)} {digits}"
    year_pattern = (_MONTH_RE + r"\s+((" + _DIGIT_SEQ + r"[-\s]+){3}"
                    + _DIGIT_SEQ + r")")
    t = re.sub(year_pattern, year_repl, t, flags=re.I)
    # fully spelled dates and cardinal words (real STT output) come last,
    # after the SKU pattern above has consumed digit-word sequences
    t = _word_dates_to_digits(t)
    t = _cardinals_to_digits(t)
    # spaced single digits from STT ('8 7 5 2', '2 6 2 9 5 0 1 5') -> joined
    t = re.sub(r"\b\d(?: \d){1,7}\b", lambda m: m.group(0).replace(" ", ""), t)
    # generic spelled digit runs from real STT ('two six two nine five zero
    # one five' -> '26295015', 'eight seven five two' -> '8752'). Runs of
    # 4+ digit-words only, so ordinary words like 'one' or 'for' are safe.
    # Runs after the SKU/year/date rules above, which already consumed
    # their own digit-word sequences.
    def digit_run_repl(m: re.Match) -> str:
        return "".join(_DIGIT_WORDS[w.lower()] for w in m.group(0).split())
    t = re.sub(r"\b(?:" + _DIGIT_SEQ + r"(?:\s+" + _DIGIT_SEQ + r"){3,})\b",
               digit_run_repl, t, flags=re.I)
    return t
