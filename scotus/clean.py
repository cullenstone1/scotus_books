"""Remove citations from opinion paragraphs so they read naturally aloud.

Approach (per paragraph):
  1. Find citation spans: eyecite for case/statute/id./supra citations, plus a few
     patterns for things eyecite doesn't cover (record cites, "post, at 5", "Pp. 3-4").
  2. Find citation-style parentheticals: "(internal quotation marks omitted)",
     "(KAGAN, J., dissenting)", "(quoting ...)", "(2014)".
  3. Split into sentences. A sentence that is nothing but citations and signal words
     ("See, e.g., Smith v. Jones, 1 U. S. 1 (1990).") is dropped whole. In any other
     sentence only the citation is removed; a case name used as part of the sentence
     ("In Carpenter v. United States, 585 U. S. 296, the Court held") is kept.

Every decision is recorded as a tagged segment so review.py can show exactly what was cut.
"""
import re
from dataclasses import dataclass

from eyecite import get_citations
from eyecite.models import FullCaseCitation, ShortCaseCitation, FullLawCitation, UnknownCitation

# --------------------------------------------------------------- patterns

DASH = "[–—-]"
BLANK = r"(?:_{2,}|[–—-]{2,})"   # page numbers not yet assigned: "598 U. S. –––" / "___ F. 4th, at ___"
NUM = rf"(?:\d+[a-z]?(?:\s*{DASH}\s*\d+[a-z]?)?|{BLANK})"
PIN_TAIL = re.compile(rf"(?:,\s*(?:and\s+)?(?:nn?\.\s*)?{NUM}(?:,\s*nn?\.\s*\d+)?)*")
YEAR_PAREN = re.compile(r"\s*\((?:[^()]*\s)?\d{4}\)")

EXTRA_CITE_RES = [
    # Id., at 5 / id. / Ibid. (eyecite misses some of these)
    re.compile(rf"\b[Ii]d\.(?:,?\s+at\s+{NUM}(?:,\s*{NUM})*(?:,\s*nn?\.\s*\d+)?)?"),
    re.compile(r"\b[Ii]bid\."),
    # supra, at 610-611 / post, at 5 / ante, at 3, n. 2 / infra, Part II
    re.compile(rf"\b(?:[Ss]upra|[Ii]nfra|[Pp]ost|[Aa]nte)(?:,\s*(?:at\s+|pp?\.\s*|nn?\.\s*|Part\s+)?{NUM}(?:,\s*(?:nn?\.\s*)?{NUM})*|\b)"),
    # briefs, record, transcripts
    re.compile(rf"\b(?:Reply\s+)?Brief\s+(?:for|of|in)\b[^;()]*?\s{NUM}(?:,\s*{NUM})*"),
    re.compile(rf"\b(?:App\.\s+to\s+Pet\.\s+for\s+Cert\.|App\.\s+to\s+Brief[^;()]*?|Pet\.\s+for\s+Cert\.|J\.\s*S\.\s+App\.|App\.|Tr\.\s+of\s+Oral\s+Arg\.|Oral\s+Arg\.\s+Tr\.|Record|Dkt\.|ECF\s+(?:Doc\.|No\.)|Doc\.)\s+(?:No\.\s+)?{NUM}(?:,\s*{NUM})*"),
    # syllabus page references: "Pp. 14-19." / "P. 7."
    re.compile(rf"\bPp?\.\s+{NUM}(?:,\s*{NUM})*"),
    # bare reporter cites eyecite didn't catch: "590 F. Supp. 3d, at 914", "598 U. S. –––", "7 Co. Rep., at 18a"
    re.compile(rf"(?:\b\d+|{BLANK})\s+(?:U\.\s?S\.?|F\.\s?(?:2d|3d|4th)|F\.\s?Supp\.?(?:\s?[23]d)?|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.)\s*,?\s+(?:at\s+)?{NUM}"),
    re.compile(rf"\b\d+\s+(?:[A-Z][A-Za-z’']*\.\s?){{1,4}}(?:\s?(?:2d|3d|4th)\s?)?,?\s+(?:at\s+)?\d+[a-z]?(?:\s*{DASH}\s*\d+[a-z]?)?"),
    # record / appendix cites: "J. S. A. Supp. 417a", "Supp. App. to Juris. Statement 174a", "App. to Pet. for Cert. 45a"
    re.compile(rf"\b(?:(?:[A-Z][a-z]*\.|to|for|of|Juris|Statement|Emergency|Application|Appendix|Motion|Stay)\s*)*"
               rf"(?:App\.|Supp\.|J\.\s?S\.|Juris\.|Pet\.|Tr\.|Dkt\.|ECF)\s*(?:(?:[A-Z][a-z]*\.|to|for|of|Juris|Statement|Emergency|Application|Appendix|Motion|Stay)\s*)*"
               rf"\d+[a-z]?(?:\s*{DASH}\s*\d+[a-z]?)?(?:,\s*\d+[a-z]?(?:\s*{DASH}\s*\d+[a-z]?)?)*"),
    # constitution: "U. S. Const., Art. I, §8, cl. 3" / "U. S. Const., Amdt. 14"
    re.compile(r"\bU\.\s?S\.\s?Const\.(?:,?\s*(?:Art\.|Amdt\.|amend\.|cl\.|§|Preamble|pmbl\.)\s*[\w]*)*"),
]
# statute/section cites: removed only when the whole sentence is citation
SOFT_CITE_RES = [
    re.compile(rf"§§?\s*[\w.()–—-]+(?:,\s*(?:\([\w]+\)|[\w.()–—-]*\d[\w.()–—-]*))*"),
    re.compile(r"\b\d+\s+U\.\s?S\.\s?C\.\s*(?:App\.\s*)?§*\s*[\w()–—-]*"),
    re.compile(r"\b\d+\s+(?:Stat\.|C\.\s?F\.\s?R\.|Fed\.\s?Reg\.)\s+[\w()–—-]+"),
]

SIGNAL_BEFORE = re.compile(
    r"(?:^|(?<=[\s;,(]))((?:but\s+)?see(?:\s+also|\s+generally)?(?:,?\s+e\.\s?g\.)?,?|cf\.(?:,?\s+e\.\s?g\.,?)?|compare|accord|e\.\s?g\.,|contra|with|and)\s*$",
    re.IGNORECASE,
)
CITE_GLUE = re.compile(
    r"^[\s,;]*(?:(?:summarily\s+)?(?:aff[’']d|rev[’']d|vacated|modified|cert\.\s+denied|cert\.\s+granted|overruled)"
    r"(?:\s+on\s+other\s+grounds)?(?:\s+(?:sub\s+nom\.|by))?|(?:but\s+)?see(?:\s+also)?|cf\.|accord|and|with|e\.\s?g\.)?[\s,;]*$",
    re.IGNORECASE,
)
PAREN_START = re.compile(
    r"^\s*(?:quoting|citing|holding|explaining|noting|describing|recognizing|observing|stating|rejecting|finding|"
    r"concluding|reasoning|discussing|emphasis|alterations?|internal|brackets?|footnotes?|citations?|cleaned\s+up|"
    r"per\s+curiam|plurality|majority|lead\s+opinion|opinion\s+of|en\s+banc|slip\s+op|statement\s+of|remarks\s+of|"
    r"testimony\s+of|same|similar|parenthetical|ellipsis|some\s+alterations?)\b",
    re.IGNORECASE,
)
PAREN_END = re.compile(
    r"(?:\b(?:omitted|added|in\s+original|concurring|dissenting|in\s+(?:the\s+)?judgment|in\s+part|J\.|JJ\.|C\.\s?J\.|"
    r"per\s+curiam|en\s+banc|cleaned\s+up)|\b\d{4})\s*$",
    re.IGNORECASE,
)
PAREN_CITE = re.compile(r"\d+\s+U\.\s?S\.|U\.\s?S\.,\s+at|F\.\s?\dd\b|F\.\s?4th|§\s?\d")
# words that don't count as "content" when deciding if a sentence is only citation
CITE_WORDS = set("""
see also generally cf compare with accord but contra and or e g eg i quoting citing internal quotation quotations marks
omitted alteration alterations emphasis added original brackets bracket footnote footnotes cleaned up per curiam
majority opinion plurality lead dissenting concurring judgment in part j jj c en banc aff affd aff’d aff'd rev rev’d
rev'd cert denied granted summarily vacated remanded n nn p pp at of the a id ibid supra infra post ante slip op
sub nom on other grounds by as amicus amici curiae brief for petitioner petitioners respondent respondents app pet
tr oral arg reply record dkt ecf doc no nos s u v c f d supp th ed l stat reg ct
statement rep reps sen cong globe sess annals debates h r comm hearing pt vol ch art cl
""".split())

ABBREV = set("""
v vs co corp inc ltd bros no nos nat int dept gov govt comm assn app supp cir ct st stat rev reg fed pub mr mrs ms dr jr sr
gen atty prof art cl ch pt cf ed ann tr pet dist div admin cong sess doc rep envt indus mfg mun natl sec serv sys tel transp
univ am bd cty hosp ins dev elec fin hous mgmt educ corr crim civ prac proc evid const amdt amend sup super cal fla tex
va pa ill mich wash ga ala ariz ark colo conn del haw ind kan ky la md me minn miss mo mont neb nev okla ore wis wyo vt
tenn n nn p pp e g i al jj rel sen hon gov adm capt lt col cmdr ofc messrs jan feb mar apr jun jul aug sep sept oct nov dec
""".split())
SIGNAL_START = re.compile(r"^\s*(?:(?:But\s+)?See(?:\s+also|\s+generally)?(?:,\s+e\.\s?g\.)?|Cf\.|Compare|Accord|E\.\s?g\.|Contra)[\s,]")
CITE_HINT = re.compile(r"\d|\b(?:[Ii]d\.|[Ii]bid\.|supra|infra|post|ante)\b")
SENT_END = re.compile(r"[.?!][”’\")\]]*\s+(?=[A-Z“‘\"(§\[\d_–—])")


@dataclass
class Span:
    start: int
    end: int
    name_end: int = -1      # for case citations: end of the case name we may keep
    soft: bool = False      # statute cites: only removed with a whole citation sentence
    kind: str = "cite"


# ------------------------------------------------------------- finding spans

def _extend(text, end):
    """Extend a citation end over pin cites, year parentheticals and trailing parentheticals."""
    while True:
        m = PIN_TAIL.match(text, end)
        if m and m.end() > end:
            end = m.end()
        m = YEAR_PAREN.match(text, end)
        if m:
            end = m.end()
            continue
        # explanatory parentheticals directly after a cite: (holding ...), (KAGAN, J., dissenting)
        m = re.match(r"\s*\(", text[end:])
        if m:
            close = _balanced(text, end + m.end() - 1)
            if close is not None:
                end = close
                continue
        return end


def _balanced(text, open_idx):
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


NAME_CONNECTORS = {"of", "the", "and", "for", "de", "ex", "rel.", "re", "on", "to", "a", "an", "&", "v.", "et", "al.", "la", "von", "van", "der"}
NAME_STOP = {"See", "Cf.", "Compare", "But", "Accord", "In", "As", "And", "Also", "Under", "Following", "Like", "Unlike",
             "After", "Before", "Since", "Because", "Then", "Thus", "So", "Here", "There", "Our", "We", "This", "That",
             "Both", "Neither", "Contra", "Id.", "With", "E.", "g.,", "see", "cf."}


def _case_name_start(text, end):
    """Start of a "Party v. Party" name that ends just before `end`, or None."""
    window_start = max(0, end - 160)
    vs = [m for m in re.finditer(r"\sv\.\s", text[window_start:end])]
    if not vs:
        return None
    defendant = text[window_start + vs[-1].end():end]
    if re.search(r"[;:“”\"()]|\.\s+[A-Z][a-z]+\s+[a-z]", defendant):
        return None
    vpos = window_start + vs[-1].start()
    start = vpos
    for tok in reversed(list(re.finditer(r"\S+", text[max(0, vpos - 100):vpos]))):
        word = tok.group(0)
        if word in NAME_STOP or re.search(r"[;:“”\"(),]$|^[“\"(]", word):
            break
        if not (word[0].isupper() or word in NAME_CONNECTORS):
            break
        start = max(0, vpos - 100) + tok.start()
    return start if start < vpos else None


def find_cites(text):
    spans = []
    try:
        cites = get_citations(text)
    except Exception:
        cites = []
    for c in cites:
        s, e = c.span()
        if isinstance(c, UnknownCitation):   # eyecite takes the sentence's period too: "§2(a)."
            e = s + len(text[s:e].rstrip(".,;"))
        fs = c.full_span()[0] if hasattr(c, "full_span") else s
        fs = min(fs, s)
        # eyecite's full_span end can run past several sentences to a later parenthetical,
        # so find the end ourselves: pin cites, year and explanatory parentheticals.
        end = _extend(text, e)
        if isinstance(c, (FullLawCitation, UnknownCitation)):
            # UnknownCitation is a bare "§1401(a)" or "¶3"; like statutes, it can be part of the sentence
            # ("Initially enacted in 1940, §1401(a) of Title 8 provides...")
            spans.append(Span(fs, end, soft=True))
        elif isinstance(c, (FullCaseCitation, ShortCaseCitation)):
            if fs == s:
                comma = len(text[:s].rstrip(" ,"))
                named = _case_name_start(text, comma) if text[comma:s].strip() == "," else None
                if named is not None:
                    fs = named
            name_end = fs + len(text[fs:s].rstrip(" ,")) if fs < s else fs
            spans.append(Span(fs, end, name_end=name_end))
        else:
            spans.append(Span(min(s, fs), end))
    for rx in EXTRA_CITE_RES:
        for m in rx.finditer(text):
            spans.append(Span(m.start(), _extend(text, m.end())))
    for rx in SOFT_CITE_RES:
        for m in rx.finditer(text):
            end = m.start() + len(m.group(0).rstrip(".,;"))   # not the sentence's period: "§2(a)."
            spans.append(Span(m.start(), _extend(text, end), soft=True))
    return _merge(text, spans)


def _merge(text, spans):
    spans.sort(key=lambda sp: (sp.start, -sp.end))
    out = []
    for sp in spans:
        if out:
            last = out[-1]
            if sp.start <= last.end or CITE_GLUE.match(text[last.end:sp.start]) and sp.start - last.end < 40:
                if sp.end > last.end:
                    last.end = sp.end
                last.soft = last.soft and sp.soft
                continue
        out.append(Span(sp.start, sp.end, sp.name_end, sp.soft, sp.kind))
    return out


def find_parens(text, cites):
    """Top-level parentheticals that read as citation apparatus, outside citation spans."""
    out = []
    i = 0
    while i < len(text):
        if text[i] == "(":
            close = _balanced(text, i)
            if close is None:
                break
            inner = text[i + 1:close - 1]
            inside_cite = any(c.start <= i < c.end for c in cites)
            if not inside_cite and (PAREN_START.search(inner) or PAREN_END.search(inner) or PAREN_CITE.search(inner)):
                out.append(Span(i, close, kind="paren"))
            i = close
        else:
            i += 1
    return out


def split_sentences(text):
    bounds, start = [], 0
    for m in SENT_END.finditer(text):
        before = re.search(r"(\S+?)[.?!][”’\")\]]*$", text[start:m.end()].rstrip())
        tok = before.group(1).lstrip("(“‘[") if before else ""
        abbrev = (len(tok) == 1 and tok.isalpha()) or tok.lower() in ABBREV or re.fullmatch(r"([A-Za-z]\.)+[A-Za-z]", tok)
        if text[m.start()] == "." and abbrev and not re.search(r"[”’\")]", m.group(0)):
            continue
        bounds.append((start, m.end()))
        start = m.end()
    if start < len(text):
        bounds.append((start, len(text)))
    return bounds


# ------------------------------------------------------------- cleaning

def _content_words(s):
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z’']*", s) if w.lower().strip("’'") not in CITE_WORDS]
    # what's left of a citation sentence is often just a case name ("Calvin's Case,"): no lowercase prose words
    if len(words) <= 8 and all(w[0].isupper() or w in NAME_CONNECTORS for w in words) and not re.search(r"[“”\"]", s):
        return []
    return words


def _strip_parens(s):
    prev = None
    while prev != s:
        prev, s = s, re.sub(r"\([^()]*\)", "", s)
    return s


def _few_lowercase(s, limit=1):
    lower = [w for w in re.findall(r"\b[a-z][a-z’']*", s)
             if w not in CITE_WORDS and w not in NAME_CONNECTORS and w not in {"at", "in", "and", "or", "with"}]
    return len(lower) <= limit


def _source_only(sentence):
    """A short sentence with a page/volume number and (almost) no lowercase prose:
    "Cong. Globe, 39th Cong., 1st Sess., 2891 (Sen. Howard)." / "2 Elliot's Debates 24." """
    bare = _strip_parens(sentence)
    if len(bare) > 250 or not re.search(r"\d", bare) or re.search(r"[“”\"]", bare):
        return False
    return _few_lowercase(bare)


ATTRIB_RE = re.compile(r"[”’],?\s+(?P<src>[A-Z\d](?:[^“”;()]|\([^()]*\))*?\d(?:[^“”;()]|\([^()]*\))*?)(?=,\s+(?:and|but|or|which|who|so|because|while|as|the|it|we|that)\b|;|\.\s|\.$|—|$)")


MONTH_DAY = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b")


def _reads_as_prose(src):
    """A sentence that only looks like a source: "On January 20, 2025, President Trump issued Executive Order No."
    / "Secretary of State Hamilton Fish agreed." A past-tense verb or a calendar date outside parentheses."""
    bare = _strip_parens(src)
    verbs = [w for w in re.findall(r"\b[a-z]{3,}ed\b", bare) if w not in CITE_WORDS]
    return bool(verbs or MONTH_DAY.search(bare))


def find_attributions(text):
    """Sources cited right after a quotation, mid-sentence: '...law,” 1 H. Tucker, Commentaries 57-58, and ...'"""
    out = []
    for m in ATTRIB_RE.finditer(text):
        src = m.group("src")
        if len(src) < 200 and _few_lowercase(_strip_parens(src)) and not _reads_as_prose(src):
            out.append(Span(m.start("src"), _extend(text, m.end("src"))))
    return out


PAGE_RE = re.compile(rf",\s+pp?\.\s+{NUM}(?:,\s*{NUM})*")
# "3 Writings of Abraham Lincoln 55" / "2 Life and Writings of Frederick Douglass 259, 415, 424"
VOLUME_CITE = rf"\d+\s+[A-Z][^;:“”()\d]*?\s{NUM}(?:,\s*{NUM})*(?=[;.]|,\s|$)"
SEE_VOLUME_RE = re.compile(rf"(?<=[,;]\s)(?:but\s+)?see(?:\s+also|\s+generally)?,?\s+({VOLUME_CITE})")
CHAINED_RE = re.compile(rf";\s+(?:(?:but\s+)?see(?:\s+also)?,?\s+)?(?:{VOLUME_CITE}|(?:\d+\s+)?[A-Z][^;:“”()]*?,\s+pp?\.\s+{NUM}(?:,\s*{NUM})*)")


def find_treatises(text):
    """Books and articles cited by author, title and page: "F. Wharton, Conflict of Laws §10, p. 35" /
    "2 Lincoln, The Constitutional History of New York ... 1905, p. 152". Walks back from ", p. N" over
    comma-separated parts with no lowercase prose, stopping at a quotation, ";" or "("."""
    out = []
    for m in PAGE_RE.finditer(text):
        start, parts, end = m.start(), 0, m.start()
        while True:
            comma = text.rfind(",", 0, end)
            stop = max(text.rfind(c, 0, start) for c in ";()“”\"")
            begin = max(comma, stop) + 1
            ends = list(re.finditer(r"[a-z]{2,}[.?!][”’]?\s+", text[begin:start]))   # a sentence end, not "F."
            if ends:
                begin, stop = begin + ends[-1].end(), comma + 1
            part = text[begin:start].strip()
            signal = re.match(r"(?:but\s+)?(?:see(?:\s+also|\s+generally)?(?:,\s+e\.\s?g\.,?)?|cf\.|accord|compare)\s+(?=[A-Z\d])", part)
            if signal:   # "see D. Potter, ...": the signal goes too (clean_paragraph removes it with the cite)
                begin += text[begin:start].index(part) + signal.end()
                part, stop = part[signal.end():], comma + 1
            if not part or re.search(r"[“”\"]", part) or not part[0].isupper() and not part[0].isdigit() \
                    or not _few_lowercase(part, 0):
                break
            start, parts, end = begin + (len(text[begin:start]) - len(text[begin:start].lstrip())), parts + 1, comma
            if comma < stop or comma < 0:
                break
        if parts >= 2:
            out.append(Span(start, _extend(text, m.end())))
    for m in SEE_VOLUME_RE.finditer(text):
        if _few_lowercase(m.group(1), 0):
            out.append(Span(m.start(1), _extend(text, m.end())))
    # sources strung together with ";" after one we found: "…, p. 281; 3 Writings of Abraham Lincoln 55"
    for sp in out:
        while (m := CHAINED_RE.match(text, sp.end)) and _few_lowercase(m.group(0), 0):
            sp.end = _extend(text, m.end())
    return out


def clean_paragraph(text):
    """Return a list of (segment, tag) covering text; tag None means kept."""
    cites = _merge(text, find_cites(text) + find_attributions(text) + find_treatises(text))
    parens = find_parens(text, cites)
    removals = []   # (start, end, tag)

    for s0, s1 in split_sentences(text):
        in_sent = [c for c in cites + parens if c.start < s1 and c.end > s0]
        if not in_sent and not SIGNAL_START.match(text[s0:s1]) and not _source_only(text[s0:s1]):
            continue
        leftover, pos = [], s0
        for c in sorted(in_sent, key=lambda c: c.start):
            leftover.append(text[pos:max(pos, c.start)])
            pos = max(pos, min(c.end, s1))
        leftover.append(text[pos:s1])
        hard = [c for c in in_sent if not c.soft]
        sentence = text[s0:s1]
        if (SIGNAL_START.match(sentence) and CITE_HINT.search(sentence)) or _source_only(sentence):
            removals.append((s0, s1, "sentence"))
            continue
        if len(_content_words("".join(leftover))) < 2 and (hard or not _content_words("".join(leftover))):
            removals.append((s0, s1, "sentence"))
            continue
        for c in in_sent:
            if c.soft:
                continue
            start, end = max(c.start, s0), min(c.end, s1)
            if c.end > s1:   # the span ran past a real sentence end ("…7 Cranch 116. Expounding"): keep the period
                m = re.search(r"(?<=[\d)\]])[.?!]\s*$", text[s0:s1])
                end = min(end, s0 + m.start()) if m else end
            if c.kind == "paren":
                removals.append((start, end, "paren"))
                continue
            before = text[s0:start]
            sig = SIGNAL_BEFORE.search(before)
            attribution = re.search(r"[,.]?[”’\"],?\s*$", before)
            keep_name = c.name_end > start and not sig and not attribution
            if keep_name:
                start = c.name_end
            elif sig:
                start = s0 + sig.start(1)
            # swallow the comma that set the citation off: "officials,” id., at 303, and" -> "officials,” and"
            if not keep_name and re.search(r",[”’\"]?\s*$", text[s0:start]):
                m = re.match(r",", text[end:])
                if m:
                    end += 1
            removals.append((start, end, "signal" if sig else "cite"))

    return _segments(text, removals)


def _segments(text, removals):
    removals.sort()
    segs, pos = [], 0
    for s, e, tag in removals:
        if e <= pos:
            continue
        s = max(s, pos)
        if s > pos:
            segs.append((text[pos:s], None))
        segs.append((text[s:e], tag))
        pos = e
    if pos < len(text):
        segs.append((text[pos:], None))
    return segs


def join_kept(segments):
    """Concatenate kept segments, keeping a space where a removal swallowed one."""
    out = ""
    for seg, tag in segments:
        if tag is not None:
            continue
        if out and seg and not out[-1].isspace() and not seg[0].isspace() and not re.match(r"[,.;:?!)\]”’]", seg):
            out += " "
        out += seg
    return out


def tidy(t):
    t = re.sub(r"\.\s\.\s\.", "…", t)                     # ". . ." ellipsis
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\s+([,.;:?!])", r"\1", t)
    t = re.sub(r"([,;:])\s*(?=[,.;:])", "", t)          # ", ." -> "."  "; ," -> ","
    t = re.sub(r",([”’\"]),", r",\1", t)                 # ,”, -> ,”
    t = re.sub(r",([”’\"])\.", r".\1", t)               # ,”. -> .”
    t = re.sub(r",([”’\"])\s*;", r"\1;", t)             # ,”; -> ”;
    t = re.sub(r",([”’\"])\s*—", r"\1—", t)              # ,” — -> ”—
    t = re.sub(r"\.\s*\.(?!\s*\.)", ".", t)
    t = re.sub(r"([.?!][”’'\s]*[”’])\.", r"\1", t)        # .’ ”. -> .’ ”              # stray double period (but keep ". . .")
    t = re.sub(r"^[\s,;:]+", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def clean_text(text):
    return tidy(join_kept(clean_paragraph(text)))


def clean_doc(doc):
    """Add cleaned text (and the tagged segments) to every paragraph of an extracted doc."""
    for sec in doc["sections"]:
        for p in sec["paragraphs"]:
            if p["type"] == "heading":
                p["clean"] = p["text"]
                continue
            p["segments"] = clean_paragraph(p["text"])
            p["clean"] = tidy(join_kept(p["segments"]))
    return doc


if __name__ == "__main__":
    import sys
    from .extract import extract
    d = clean_doc(extract(sys.argv[1]))
    for sec in d["sections"]:
        print(f"######## {sec['title']}\n")
        for p in sec["paragraphs"]:
            if p["clean"]:
                print(p["clean"] + "\n")
