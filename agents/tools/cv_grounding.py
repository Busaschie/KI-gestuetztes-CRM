"""Abgleich der KI-Auslese mit dem Originaltext des Lebenslaufs (Grundsatz 4: nichts erfinden).

ground_positions PRÜFT nur (layoutunabhängig): Was nicht im Text steht, wird entfernt, Unsicheres als
Hinweis gemeldet. Die Struktur (welche Aufgabe zu welcher Station gehört) erkennt das Sprachmodell.

split_blocks (Zerlegung an Zeiträumen) wird für den Abgleich nicht mehr verwendet – Lebensläufe sind
zu unterschiedlich aufgebaut (siehe work/entscheidungen.md). Bleibt als Werkzeug für Analysen erhalten.
"""
import re
from dataclasses import dataclass, field

from agents.llm.schemas import ONGOING, PositionOut, normalize_date

# Nur echte Monatsnamen (DE/EN/RO, auch abgekürzt) – sonst würde z. B. "Leiter 2012" als Datum gelesen
_MONTH = r"(?:jan|jän|feb|mär|mae|mar|apr|mai|may|jun|jul|aug|sep|okt|oct|nov|dez|dec|ian|iun|iul|noi)[a-zäöüăâîșțşţ]*\.?"
_TOKEN = rf"(?:\b{_MONTH}\s+)?(?:\d{{1,2}}[./]\s*)?(?:19|20)\d{{2}}"
_END = _TOKEN + r"|present|heute|today|now|jetzt|aktuell|prezent|current|bis heute|până în prezent"
DATE_RANGE_RE = re.compile(
    rf"(?P<a>{_TOKEN})\s*(?:–|—|-|bis|to|până la)\s*(?P<b>{_END})"
    rf"|(?:seit|since|din|from)\s+(?P<s>{_TOKEN})",
    re.I,
)
PAGE_RE = re.compile(r"^(?:seite|page|pagina|pagină)\s*\d+(?:\s*(?:von|of|din|/)\s*\d+)?$", re.I)
BULLET_RE = re.compile(r"^\s*(?:[•●▪◦‣·∙■□➢➤►\-–*]|\d{1,2}[.)])\s+(.*)$")
MAX_TASKS = 8


def _norm(s) -> str:
    return re.sub(r"[^\w]+", " ", str(s or "").lower()).strip()


def _year(s) -> str:
    m = re.search(r"(19|20)\d{2}", str(s or ""))
    return m.group(0) if m else ""


def _is_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    # Länge ohne Leerzeichen – gesperrte Überschriften ("E X P E R I E N C E") sind sonst zu lang
    return bool(letters) and line.isupper() and len(re.sub(r"\s+", "", line)) <= 40


@dataclass
class Block:
    index: int  # Zeile des Zeitraums
    date_line: str
    start: str | None
    end: str | None
    is_current: bool
    header: list[str] = field(default_factory=list)  # Titel, ggf. Firma/Ort
    rest: str = ""  # Text in der Datumszeile außer dem Zeitraum (z. B. Ort)
    tasks: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.header[0] if self.header else ""

    @property
    def text(self) -> str:
        return " ".join(self.header + [self.date_line])


def parse_range(line: str):
    m = DATE_RANGE_RE.search(line)
    if not m:
        return None
    if m.group("s"):
        return normalize_date(m.group("s")), None, True, m
    a, b = normalize_date(m.group("a")), m.group("b").strip()
    current = b.lower() in ONGOING
    return a, (None if current else normalize_date(b)), current, m


def _looks_like_title(ln: str) -> bool:
    """Titel/Firma sind kurz, beginnen nicht klein und enden nicht wie ein Satz."""
    head = re.split(r"\s+[—–]\s+", ln, maxsplit=1)[0]  # Zusatz nach Gedankenstrich zählt nicht
    return len(head) <= 90 and not ln.rstrip().endswith((".", "!", "?", ";")) and not ln[:1].islower()


def _plain(ln: str) -> bool:
    """Eine Zeile, die Titel oder Firma sein kann (kein Stichpunkt, keine Überschrift, kein Zeitraum, kein Satz)."""
    return (bool(ln) and not BULLET_RE.match(ln) and not _is_heading(ln) and not parse_range(ln)
            and _looks_like_title(ln))


def split_blocks(text: str) -> list[Block]:
    # Seitenzeilen ("Seite 3 von 4") entfernen, damit Seitenumbrüche Stationen nicht zerreißen
    # Leerzeilen verwerfen (pdfminer setzt sie zwischen Textblöcke)
    lines = [ln for ln in (x.strip() for x in text.splitlines()) if ln and not PAGE_RE.match(ln)]
    blocks = []
    for i, line in enumerate(lines):
        parsed = parse_range(line)
        if not parsed or BULLET_RE.match(line):  # Zeitraum in einem Stichpunkt ist keine Station
            continue
        start, end, current, m = parsed
        rest = (line[: m.start()] + " " + line[m.end():]).strip(" |,;–-—()\t")
        blocks.append(Block(i, line, start, end, current, rest=rest))

    # Kopfzeilen bestimmen. Zwei Layouts:
    #  A) Titel (und "Firma, Ort") ÜBER der Datumszeile; Rest der Datumszeile = Ort
    #  B) Titel IN der Datumszeile ("Technischer Leiter 2012 – 2017"), Firma in der Zeile DARUNTER
    above_counts, consumed = [], []
    for k, b in enumerate(blocks):
        prev_end = blocks[k - 1].index + consumed[k - 1] if k else -1
        header, j = [], b.index - 1
        while j > prev_end and len(header) < 2 and _plain(lines[j]):
            header.insert(0, lines[j])
            j -= 1
        used_below = 0
        if header:
            b.header = header
        elif b.rest and _looks_like_title(b.rest):
            b.header, b.rest = [b.rest], ""
            j = b.index + 1
            while j < len(lines) and not lines[j]:
                j += 1
            nxt = blocks[k + 1].index if k + 1 < len(blocks) else len(lines)
            if j < nxt and _plain(lines[j]) and not lines[j].startswith("("):
                b.header.append(lines[j])
                used_below = j - b.index
        above_counts.append(len(header))
        consumed.append(used_below)

    for k, b in enumerate(blocks):
        stop = (blocks[k + 1].index - above_counts[k + 1]) if k + 1 < len(blocks) else len(lines)
        tasks = []
        for ln in lines[b.index + 1 + consumed[k]: stop]:
            if not ln:
                continue
            if _is_heading(ln):
                break
            m = BULLET_RE.match(ln)
            if m:
                tasks.append(m.group(1).strip())
            elif tasks and not ln.startswith("("):
                tasks[-1] = f"{tasks[-1]} {ln}"  # Zeilenumbruch innerhalb eines Stichpunkts
            else:
                tasks.append(ln)  # z. B. "(concurrent with Master's degree)"
        b.tasks = tasks[:MAX_TASKS]
    return blocks


def _in_text(value, ntext: str) -> bool:
    v = _norm(value)
    return bool(v) and v in ntext


def ground_positions(positions: list[PositionOut], text: str, education_keys: list[str]) -> tuple[list[PositionOut], list[str]]:
    """Prüft die ausgelesenen Stationen gegen den Text – unabhängig vom Layout des Lebenslaufs.

    Es wird nichts aus dem Layout zusammengebaut oder umsortiert. Entfernt wird nur, was nachweislich
    nicht im Text steht (erfundene Station, Firma oder Aufgabe); alles Unsichere wird als Hinweis gemeldet.
    """
    ntext = _norm(text)
    if not ntext:
        return positions, []
    years = set(re.findall(r"(?:19|20)\d{2}", text))
    notes, result = [], []
    for p in positions:
        label = p.title or p.company or "?"
        title_ok, company_ok = _in_text(p.title, ntext), _in_text(p.company, ntext)
        if not title_ok and not company_ok:
            notes.append(f"Station „{label}“ steht nicht im Lebenslauf – entfernt")
            continue
        if p.company and not company_ok:
            notes.append(f"„{label}“: Firma „{p.company}“ steht nicht im Text – entfernt")
            p.company = None
        if p.title and not title_ok:
            notes.append(f"„{label}“: Titel „{p.title}“ steht so nicht im Text – bitte prüfen")
        for value in (p.start, p.end):
            y = _year(value)
            if y and y not in years:
                notes.append(f"„{label}“: Jahr {y} steht nicht im Text – bitte prüfen")
        kept = [t for t in p.tasks if _token_overlap(t, ntext) >= 0.5]
        if len(kept) < len(p.tasks):
            notes.append(f"„{label}“: {len(p.tasks) - len(kept)} Aufgabe(n) nicht im Text belegt – entfernt")
        p.tasks = kept
        result.append(p)
    notes += _unassigned_ranges(result, text, education_keys)
    return result, notes


def _unassigned_ranges(positions: list[PositionOut], text: str, education_keys: list[str]) -> list[str]:
    """Zeiträume im Text, deren Startjahr zu keiner Station passt und die nicht bei einer Ausbildung stehen."""
    starts = {_year(p.start) for p in positions if p.start}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    notes = []
    for i, ln in enumerate(lines):
        parsed = parse_range(ln)
        if not parsed or BULLET_RE.match(ln) or _year(parsed[0]) in starts:
            continue
        context = _norm(" ".join(lines[max(i - 2, 0): i + 2]))
        if any(k and k in context for k in education_keys):
            continue
        notes.append(f"Zeitraum keiner Station zugeordnet: „{ln[:80]}“ – bitte prüfen")
    return notes


def _token_overlap(task: str, ntext: str) -> float:
    """Anteil der Wortpaare der Aufgabe, die genau so im Text stehen (einzelne Wörter reichen nicht:
    "Managed travel and calendars" wäre sonst belegt, nur weil "managed" und "calendars" vorkommen)."""
    words = _norm(task).split()
    if len(words) < 2:
        return 1.0 if words and f" {words[0]} " in f" {ntext} " else 0.0
    padded = f" {ntext} "
    pairs = [f" {a} {b} " for a, b in zip(words, words[1:])]
    return sum(1 for pr in pairs if pr in padded) / len(pairs)
