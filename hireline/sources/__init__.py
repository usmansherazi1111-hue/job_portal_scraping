from .ats import ATS, detect
from .feeds import FEEDS
from .keyed import KEYED
from .pages import PAGE, careers_page
from .regional import REGIONAL
from .base import Query, Source, country_code

SOURCES = {s.id: s for s in [*ATS, *REGIONAL, *FEEDS, *KEYED, PAGE]}
