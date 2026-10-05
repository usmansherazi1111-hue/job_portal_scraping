"""A company's own careers page: read schema.org JobPosting (JSON-LD) and spot links to an ATS board.
Only pages robots.txt allows are fetched."""
from __future__ import annotations
import json, re
from urllib.parse import urljoin, urlsplit
from ..model import Job, text, iso, money
from .ats import detect
from .base import Source

LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
HREF = re.compile(r'href=["\']([^"\'#]+)["\']', re.I)
CAREER_WORDS = re.compile(r"(?i)career|jobs|join|vacanc|hiring|work-with-us|openings|stellen")


def _walk(o):
    if isinstance(o, list):
        for x in o: yield from _walk(x)
    elif isinstance(o, dict):
        t = o.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t): yield o
        for k in ("@graph", "itemListElement", "item", "mainEntity"):
            if k in o: yield from _walk(o[k])


def _place(p) -> str:
    out = []
    for loc in p if isinstance(p, list) else [p]:
        if not isinstance(loc, dict): continue
        a = loc.get("address") or {}
        if isinstance(a, str): out.append(a); continue
        out.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry") if isinstance(a.get("addressCountry"), str) else (a.get("addressCountry") or {}).get("name")) if x))
    return "; ".join(x for x in out if x)


def postings(html: str, base: str) -> list[Job]:
    jobs = []
    for block in LD.findall(html):
        try: data = json.loads(block.strip())
        except ValueError: continue
        for p in _walk(data):
            org = p.get("hiringOrganization") or {}
            sal = (p.get("baseSalary") or {}) if isinstance(p.get("baseSalary"), dict) else {}
            val = sal.get("value") or {}
            jobs.append(Job(
                title=p.get("title") or p.get("name"), company=org.get("name") if isinstance(org, dict) else str(org),
                location=_place(p.get("jobLocation")) or ("Remote" if p.get("jobLocationType") == "TELECOMMUTE" else ""),
                department=p.get("occupationalCategory") or p.get("industry") or "",
                employment_type=p.get("employmentType") or "", remote=True if p.get("jobLocationType") == "TELECOMMUTE" else None,
                salary=money(val.get("minValue") or val.get("value"), val.get("maxValue"), sal.get("currency", ""), val.get("unitText", "")) if isinstance(val, dict) else "",
                posted=iso(p.get("datePosted")), description=text(p.get("description")),
                url=urljoin(base, p.get("url") or "") or base, source="careerspage",
                source_id=str((p.get("identifier") or {}).get("value", "") if isinstance(p.get("identifier"), dict) else p.get("identifier") or ""),
                extra={"valid_through": iso(p.get("validThrough"))}))
    return jobs


async def careers_page(net, url: str, follow: bool = True) -> tuple[list[Job], list[tuple[str, str]]]:
    """Returns JobPostings found on the page (and on up to 3 linked career pages on the same site) plus ATS boards it links to."""
    if not re.match(r"https?://", url): url = "https://" + url
    html = (await net.fetch(url, check_robots=True, interval=1.5, ttl=6 * 3600)).decode("utf-8", "ignore")
    jobs, boards = postings(html, url), detect(html)
    if follow and not jobs and not boards:
        host = urlsplit(url).netloc
        links = []
        for h in HREF.findall(html):
            u = urljoin(url, h)
            if urlsplit(u).netloc.endswith(host.split("www.")[-1]) and CAREER_WORDS.search(urlsplit(u).path) and u not in links: links.append(u)
        boards += [b for b in detect(" ".join(HREF.findall(html))) if b not in boards]
        for u in links[:3]:
            try:
                j, b = await careers_page(net, u, follow=False)
                jobs += j; boards += [x for x in b if x not in boards]
            except Exception:
                continue
    return jobs, boards


PAGE = Source("careerspage", "Company careers pages (JSON-LD)", "page", "Any", None,
              note="Reads schema.org JobPosting on pages robots.txt allows, and follows links to ATS boards.",
              home="https://developers.google.com/search/docs/appearance/structured-data/job-posting")
