from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from ..model import Job

COUNTRY_NAMES = {
    "gb": "United Kingdom", "us": "United States", "de": "Germany", "pk": "Pakistan", "ae": "United Arab Emirates",
    "sa": "Saudi Arabia", "qa": "Qatar", "in": "India", "ca": "Canada", "au": "Australia", "fr": "France", "nl": "Netherlands",
    "es": "Spain", "it": "Italy", "ie": "Ireland", "sg": "Singapore", "za": "South Africa", "at": "Austria", "ch": "Switzerland",
    "be": "Belgium", "pl": "Poland", "br": "Brazil", "mx": "Mexico", "nz": "New Zealand", "se": "Sweden", "dk": "Denmark",
    "no": "Norway", "fi": "Finland", "pt": "Portugal", "tr": "Turkey", "eg": "Egypt", "kw": "Kuwait", "om": "Oman", "bh": "Bahrain",
}
ALIASES = {"uk": "gb", "england": "gb", "usa": "us", "uae": "ae", "dubai": "ae", "ksa": "sa"}

# Extra words that identify a country inside a free-text location (major cities, states, short forms).
COUNTRY_WORDS = {
    "pk": ["pakistan", "lahore", "karachi", "islamabad", "rawalpindi", "faisalabad", "multan", "peshawar", "quetta", "sialkot",
           "gujranwala", "hyderabad, sindh", "punjab, pk", "sindh", "khyber"],
    "gb": ["united kingdom", "uk", "england", "scotland", "wales", "northern ireland", "london", "manchester", "birmingham",
           "edinburgh", "glasgow", "leeds", "bristol", "cambridge", "oxford", "great britain"],
    "us": ["united states", "usa", "u.s.", "new york", "san francisco", "seattle", "austin", "boston", "chicago", "los angeles",
           "remote - us", "remote-us", "denver", "atlanta", "washington, dc"],
    "ae": ["united arab emirates", "uae", "dubai", "abu dhabi", "sharjah"],
    "sa": ["saudi arabia", "ksa", "riyadh", "jeddah", "dammam", "khobar"],
    "de": ["germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart"],
    "in": ["india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad, india", "pune", "chennai", "gurgaon", "gurugram", "noida"],
    "ca": ["canada", "toronto", "vancouver", "montreal", "ottawa", "calgary"],
    "au": ["australia", "sydney", "melbourne", "brisbane", "perth"],
    "nl": ["netherlands", "amsterdam", "rotterdam", "utrecht", "the hague"],
    "fr": ["france", "paris", "lyon"], "ie": ["ireland", "dublin"], "sg": ["singapore"], "es": ["spain", "madrid", "barcelona"],
    "qa": ["qatar", "doha"],
}
# Remote-job regions a country belongs to (used only when the user asks to include remote jobs open to the country).
REGIONS = {
    "pk": ["asia", "south asia", "apac", "emea", "middle east"], "in": ["asia", "south asia", "apac"],
    "ae": ["emea", "middle east", "mena", "gcc"], "sa": ["emea", "middle east", "mena", "gcc"], "qa": ["emea", "middle east", "mena", "gcc"],
    "gb": ["europe", "emea", "eu"], "de": ["europe", "emea", "eu"], "fr": ["europe", "emea", "eu"], "nl": ["europe", "emea", "eu"],
    "ie": ["europe", "emea", "eu"], "es": ["europe", "emea", "eu"], "us": ["americas", "north america", "us"], "ca": ["americas", "north america"],
    "au": ["apac", "oceania"], "sg": ["apac", "asia"],
}
ANYWHERE = re.compile(r"(?i)\b(anywhere|worldwide|global|remote\s*\(worldwide\)|world)\b")
CITY_ALIASES = {"bangalore": ["bengaluru"], "bengaluru": ["bangalore"], "gurgaon": ["gurugram"], "munich": ["münchen"],
                "cologne": ["köln"], "new york": ["nyc", "new york city"], "islamabad": ["rawalpindi/islamabad"]}


def _has(hay: str, word: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", hay) is not None


def country_code(s: str) -> str:
    s = (s or "").strip().lower()
    if not s: return ""
    if s in ALIASES: return ALIASES[s]
    if len(s) == 2: return s
    for k, v in COUNTRY_NAMES.items():
        if v.lower() == s: return k
    return ""


@dataclass
class Query:
    keywords: str = ""
    location: str = ""          # city or free text
    country: str = ""           # ISO-2, e.g. "gb"
    limit: int = 100            # per source
    days: int = 0               # only jobs posted in the last N days (0 = any)
    remote: bool = False        # also keep remote jobs open to the chosen country/region (worldwide, EMEA, ...)
    boards: list = field(default_factory=list)   # [(ats, slug)] for company boards
    pages: list = field(default_factory=list)    # careers page URLs (JSON-LD JobPosting)

    @property
    def words(self) -> list[str]:
        return [w for w in re.split(r"[\s,]+", self.keywords.lower()) if len(w) > 1]

    @property
    def country_name(self) -> str:
        return COUNTRY_NAMES.get(self.country, self.country.upper())

    def matches(self, j: Job) -> bool:
        """Applied to every source: each keyword must appear in title/department/company/description, and the job
        must be in the chosen city/country (see place_ok)."""
        if self.words and not j.extra.get("kw_by_source"):
            hay = f"{j.title} {j.department} {j.company} {j.description[:6000]}".lower()
            if not all(w in hay for w in self.words): return False
        return self.place_ok(j)

    def city_words(self) -> list[str]:
        c = self.location.strip().lower()
        return [c] + CITY_ALIASES.get(c, []) if c else []

    def country_words(self) -> list[str]:
        if not self.country: return []
        return [self.country_name.lower()] + COUNTRY_WORDS.get(self.country, [])

    def place_ok(self, j: Job) -> bool:
        """Strict by default: with a city, the job's location must name that city; with only a country, it must name
        the country (or one of its main cities). Remote jobs that are open worldwide or to the country's region
        are kept only when `remote` is on."""
        if not (self.location or self.country): return True
        loc = f"{j.location} ; {j.office}".lower()
        if self.location:
            if any(_has(loc, w) for w in self.city_words()): return True
        elif any(_has(loc, w) for w in self.country_words()) or (self.country and re.search(rf"\b{self.country.upper()}\b", f"{j.location} {j.office}")):
            return True
        if self.remote and (j.remote or "remote" in loc or ANYWHERE.search(loc)):
            if ANYWHERE.search(loc) or not loc.strip(" ;") or loc.strip(" ;") == "remote": return True
            if any(_has(loc, w) for w in self.country_words() + REGIONS.get(self.country, [])): return True
        return False


@dataclass
class Source:
    id: str
    name: str
    group: str                      # "board" (company ATS), "search" (keyword search), "page" (careers page)
    region: str
    run: Callable[..., Awaitable[list[Job]]]
    needs: tuple = ()               # settings keys (free API keys) required
    ttl: float = 1800               # seconds a response is reused from the cache
    interval: float = 1.0           # min seconds between requests to the host
    filters_locally: bool = False   # True when the source has no server-side keyword search
    note: str = ""                  # terms / attribution the user must follow
    home: str = ""
    signup: str = ""                # where to get the free key, for sources that need one
    default: bool = True            # ticked for new users
