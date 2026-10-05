"""The one job record every source is normalised into, plus small text and date helpers."""
from __future__ import annotations
import hashlib, html, re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

FIELDS = ["title", "company", "location", "department", "office", "employment_type", "remote", "salary",
          "posted", "updated", "description", "url", "source", "source_id"]


@dataclass
class Job:
    title: str
    company: str = ""
    location: str = ""
    department: str = ""
    office: str = ""
    employment_type: str = ""
    remote: bool | None = None
    salary: str = ""
    posted: str = ""        # ISO date (YYYY-MM-DD) the job was first published, when the source gives it
    updated: str = ""       # ISO date of the last change, falls back to posted
    description: str = ""   # plain text
    url: str = ""
    source: str = ""
    source_id: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        for f in ("title", "company", "location", "department", "office", "employment_type", "salary"):
            setattr(self, f, clean(getattr(self, f)))
        if not self.updated: self.updated = self.posted

    @property
    def key(self) -> str:
        """Same job seen on two sources (company + title + city) collapses to one row."""
        city = re.split(r"[,;/|(]", self.location or "")[0]
        raw = "|".join(norm(x) for x in (self.company, self.title, city))
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def row(self) -> dict:
        d = asdict(self); d.pop("extra")
        d["remote"] = "" if self.remote is None else ("yes" if self.remote else "no")
        return d


TAG = re.compile(r"<[^>]+>")
BLOCK = re.compile(r"(?i)</?(p|div|br|li|ul|ol|h[1-6]|tr|section)[^>]*>")
WS = re.compile(r"[ \t ]+")


def clean(s) -> str:
    if s is None: return ""
    if isinstance(s, (list, tuple)): s = ", ".join(clean(x) for x in s if x)
    return WS.sub(" ", html.unescape(str(s))).strip()


def text(h: str | None, limit: int = 20000) -> str:
    """HTML (or entity-escaped HTML, as Greenhouse sends) -> readable plain text with paragraph breaks."""
    if not h: return ""
    s = html.unescape(h) if "&lt;" in h else h
    s = BLOCK.sub("\n", s)
    s = html.unescape(TAG.sub("", s))
    s = "\n".join(WS.sub(" ", ln).strip() for ln in s.splitlines())
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:limit]


def norm(s: str) -> str:
    s = re.sub(r"(?i)\b(gmbh|ltd|limited|inc|llc|plc|pvt|corp|co)\b\.?", " ", s or "")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def iso(v) -> str:
    """Epoch seconds/ms, ISO strings, 'dd/mm/yyyy' or RFC 822 -> 'YYYY-MM-DD' (empty when unknown)."""
    if v in (None, "", 0): return ""
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            n = float(v); n = n / 1000 if n > 1e11 else n
            return datetime.fromtimestamp(n, tz=timezone.utc).date().isoformat()
        s = str(v).strip()
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m: return m.group(0)
        m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", s)
        if m: return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", s)
        if m: return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        for fmt in ("%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y"):
            try: return datetime.strptime(s, fmt).date().isoformat()
            except ValueError: pass
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:
        return ""


def money(lo=None, hi=None, cur: str = "", period: str = "") -> str:
    def f(x):
        try: return f"{float(x):,.0f}"
        except (TypeError, ValueError): return ""
    a, b = f(lo), f(hi)
    if not a and not b: return ""
    rng = f"{a} - {b}" if a and b and a != b else (a or b)
    return " ".join(x for x in (cur, rng, period) if x)
