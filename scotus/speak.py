"""Turn cleaned opinion text into text a TTS voice reads naturally."""
import re

JUSTICES = """ROBERTS THOMAS ALITO SOTOMAYOR KAGAN GORSUCH KAVANAUGH BARRETT JACKSON BREYER GINSBURG KENNEDY
SCALIA STEVENS SOUTER O’CONNOR O'CONNOR REHNQUIST WHITE BLACKMUN POWELL MARSHALL BRENNAN BURGER""".split()
TITLE_WORDS = {"JUSTICE", "JUSTICES", "CHIEF", "PER", "CURIAM", "THE", "COURT"}
# acronyms that are said as words; every other all-caps acronym is spelled out
SAID_AS_WORDS = {"NAACP", "NATO", "NASA", "AIDS", "COVID", "FEMA", "OSHA", "HIPAA", "ERISA", "CERCLA", "NEPA", "SNAP",
                 "DACA", "UNESCO", "ASCII", "GIF", "JPEG", "RICO", "TARP", "AMTRAK", "FIFA", "NASCAR"}

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()

ABBREVIATIONS = [
    (r"\be\.\s?g\.,?", "for example,"),
    (r"\bi\.\s?e\.,?", "that is,"),
    (r"\b[Cc]f\.", "compare"),
    (r"\bet al\.", "and others"),
    (r"\betc\.", "et cetera"),
    (r"\bArt\.\s", "Article "),
    (r"\bArts\.\s", "Articles "),
    (r"\bAmdt\.\s", "Amendment "),
    (r"\bNo\.\s(?=\d)", "Number "),
    (r"\bNos\.\s(?=\d)", "Numbers "),
    (r"\bInc\.", "Incorporated"),
    (r"\bCorp\.", "Corporation"),
    (r"\bDept\.|\bDep[’']t", "Department"),
    (r"\bComm[’']n", "Commission"),
    (r"\bAss[’']n", "Association"),
    (r"\bGov[’']t", "Government"),
    (r"\bInt[’']l", "International"),
    (r"\bNat[’']l", "National"),
    (r"\bEnv[’']t", "Environment"),
    (r"\bAtt[’']y", "Attorney"),
    (r"\bSec[’']y", "Secretary"),
    (r"\bCir\.", "Circuit"),
    (r"§§\s*", "sections "),
    (r"§\s*", "section "),
    (r"¶¶?\s*", "paragraph "),
]


def number_words(n):
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    return str(n)


def roman_to_int(s):
    total = 0
    for i, c in enumerate(s):
        v = ROMAN[c]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    return total


def _roman_part(m):
    """"III–C" -> "Three C"; "II–C–1" -> "Two C 1"."""
    parts = re.split(r"[–—-]", m.group(0))
    head = parts[0]
    words = [number_words(roman_to_int(head)).capitalize()] if re.fullmatch(r"[IVXLC]+", head) else [head]
    return " ".join(words + parts[1:])


ROMAN_TOKEN = r"[IVXL]+(?:[–—-][A-Z0-9]+)*"


def heading(text):
    """Spoken form of a section heading like "II", "B", "III–C" or "* * *"."""
    t = text.strip()
    if re.fullmatch(r"\*\s*\*\s*\*", t):
        return ""
    if re.fullmatch(ROMAN_TOKEN, t):
        return "Part " + _roman_part(re.match(ROMAN_TOKEN, t))
    if re.fullmatch(r"[A-Z]([–—-][A-Z0-9]+)*|\d+", t):
        return "Section " + t.replace("–", " ").replace("—", " ").replace("-", " ")
    return t


def _titlecase_names(t):
    def fix(m):
        w = m.group(0)
        if w in JUSTICES or w in TITLE_WORDS:
            return w[0] + w[1:].lower() if "’" not in w and "'" not in w else w[0] + w[1] + w[2] + w[3:].lower()
        return w
    return re.sub(r"\b[A-Z][A-Z’']{1,}\b", fix, t)





def _acronyms(t):
    def fix(m):
        w = m.group(0)
        if w in SAID_AS_WORDS or w in JUSTICES or w in TITLE_WORDS:
            return w
        return ".".join(w) + "."
    return re.sub(r"\b[A-Z]{2,6}\b(?!\.)", fix, t)


def speakable(t):
    t = _titlecase_names(t)
    # "Kagan and Jackson, JJ., joined" -> "Justices Kagan and Jackson joined"; "Roberts, C. J.," -> "Chief Justice Roberts"
    t = re.sub(r"((?:[A-Z][\w’'-]+,\s+)*[A-Z][\w’'-]+,?\s+and\s+[A-Z][\w’'-]+),\s+JJ\.,?", r"Justices \1", t)
    t = re.sub(r"([A-Z][\w’'-]+),\s+C\.\s?J\.,?", r"Chief Justice \1", t)
    t = re.sub(r"([A-Z][\w’'-]+),\s+J\.,?", r"Justice \1", t)
    t = re.sub(r"(?<=[\w.])\s+v\.\s+(?=[A-Z])", " versus ", t)
    for rx, rep in ABBREVIATIONS:
        t = re.sub(rx, rep, t)
    # Roman numerals: after Part/Title/Article/etc., and anywhere they carry a dash suffix ("III–C")
    t = re.sub(rf"\b(Parts?|Titles?|Articles?|Amendments?|Clauses?|Chapters?|Section)\s+({ROMAN_TOKEN})\b",
               lambda m: m.group(1) + " " + _roman_part(re.match(ROMAN_TOKEN, m.group(2))), t)
    t = re.sub(r"\b[IVXL]+(?:[–—-][A-Z0-9]+)+\b", _roman_part, t)
    t = re.sub(r"(?<![\w–—])(\d+)\s?[–—]\s?(\d+)(?![\w–—])", r"\1 to \2", t)   # page/year ranges, not "18–2–25d"
    t = re.sub(r"(\d)-to-(\d)", r"\1 to \2", t)
    t = re.sub(r"\[sic\]", "", t)
    t = t.replace("[", "").replace("]", "")
    t = re.sub(r"\b([A-Z])\.\s(?=[A-Z]\.)", r"\1.", t)      # "U. S." -> "U.S.", "B. P. J." -> "B.P.J."
    t = _acronyms(t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()
