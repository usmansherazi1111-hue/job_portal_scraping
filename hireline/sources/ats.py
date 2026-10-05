"""Company job boards hosted by applicant-tracking systems. Each has an official public endpoint; one board = one employer."""
from __future__ import annotations
import asyncio, re
import xml.etree.ElementTree as ET
from ..model import Job, text, iso, money
from .base import Source


def _slug_name(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


async def greenhouse(net, q, cfg, slug):
    d = await net.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}, interval=0.5)
    try: company = (await net.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}", interval=0.5, ttl=86400)).get("name")
    except Exception: company = None
    company = company or _slug_name(slug)
    out = []
    for j in d.get("jobs", []):
        offices = j.get("offices") or []
        out.append(Job(
            title=j.get("title"), company=j.get("company_name") or company, location=(j.get("location") or {}).get("name", ""),
            department=[x.get("name") for x in j.get("departments") or []],
            office=[x.get("name") for x in offices], posted=iso(j.get("first_published")), updated=iso(j.get("updated_at")),
            description=text(j.get("content")), url=j.get("absolute_url", ""), source="greenhouse", source_id=str(j.get("id", ""))))
    return out


async def lever(net, q, cfg, slug):
    d = await net.json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, interval=0.5)
    out = []
    for j in d if isinstance(d, list) else []:
        c = j.get("categories") or {}
        body = "\n\n".join(x for x in [j.get("descriptionPlain") or text(j.get("description"))] +
                           [f"{l.get('text','')}\n{text(l.get('content'))}" for l in j.get("lists") or []] +
                           [j.get("additionalPlain") or text(j.get("additional"))] if x)
        rng = j.get("salaryRange") or {}
        out.append(Job(
            title=j.get("text"), company=_slug_name(slug), location=c.get("location") or ", ".join(c.get("allLocations") or []),
            department=c.get("department") or c.get("team") or "",
            office=" / ".join(x for x in [c.get("team") if c.get("department") else ""] + (c.get("allLocations") or [c.get("location") or ""]) if x),
            employment_type=c.get("commitment") or "",
            remote=(j.get("workplaceType") == "remote") if j.get("workplaceType") else None,
            salary=money(rng.get("min"), rng.get("max"), rng.get("currency", ""), rng.get("interval", "")),
            posted=iso(j.get("createdAt")), updated=iso(j.get("updatedAt") or j.get("createdAt")), description=body[:20000],
            url=j.get("hostedUrl", ""), source="lever", source_id=j.get("id", "")))
    return out


async def ashby(net, q, cfg, slug):
    d = await net.json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}, interval=0.5)
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False: continue
        comp = j.get("compensation") or {}
        out.append(Job(
            title=j.get("title"), company=_slug_name(slug), location=j.get("location", ""), department=j.get("department", ""),
            office=j.get("team", ""), employment_type=j.get("employmentType", ""), remote=j.get("isRemote"),
            salary=comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary") or "",
            posted=iso(j.get("publishedAt")), updated=iso(j.get("updatedAt") or j.get("publishedAt")),
            description=j.get("descriptionPlain") or text(j.get("descriptionHtml")), url=j.get("jobUrl", ""),
            source="ashby", source_id=j.get("id", "") or j.get("jobUrl", "")))
    return out


async def smartrecruiters(net, q, cfg, slug):
    out, offset = [], 0
    params = {"limit": 100}
    if q.country: params["country"] = q.country
    if q.keywords: params["q"] = q.keywords
    while len(out) < max(q.limit, 100) and offset < 1000:
        d = await net.json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={**params, "offset": offset}, interval=0.3)
        rows = d.get("content") or []
        for j in rows:
            loc = j.get("location") or {}
            out.append(Job(
                title=j.get("name"), company=(j.get("company") or {}).get("name") or _slug_name(slug),
                location=", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x),
                department=(j.get("department") or {}).get("label", ""), office=(j.get("function") or {}).get("label", ""),
                employment_type=(j.get("typeOfEmployment") or {}).get("label", ""), remote=loc.get("remote"),
                posted=iso(j.get("releasedDate")), url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                source="smartrecruiters", source_id=str(j.get("id", "")), extra={"ref": j.get("ref")}))
        offset += len(rows)
        if not rows or offset >= d.get("totalFound", 0): break
    # The list has no description; fetch details for the jobs we will actually show (bounded and paced).
    async def detail(job):
        try:
            d = await net.json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job.source_id}", interval=0.3, ttl=86400)
            secs = ((d.get("jobAd") or {}).get("sections") or {})
            job.description = "\n\n".join(text(s.get("text")) for s in secs.values() if isinstance(s, dict) and s.get("text"))
            job.url = d.get("postingUrl") or job.url
        except Exception:
            pass
    await asyncio.gather(*(detail(j) for j in out[: min(q.limit, 60)]))
    return out


async def workable(net, q, cfg, slug):
    d = await net.json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"}, interval=1.5, ttl=3600)
    company = d.get("name") or _slug_name(slug)
    out = []
    for j in d.get("jobs", []):
        locs = j.get("locations") or []
        place = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x) or \
                "; ".join(", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in locs)
        out.append(Job(
            title=j.get("title"), company=company, location=place, department=j.get("department", ""), office=j.get("function", ""),
            employment_type=j.get("employment_type", ""), remote=j.get("telecommuting"), posted=iso(j.get("published_on")),
            updated=iso(j.get("created_at") or j.get("published_on")), description=text(j.get("description")),
            url=j.get("url") or j.get("shortlink", ""), source="workable", source_id=j.get("shortcode", "")))
    return out


async def personio(net, q, cfg, slug):
    out = []
    for host in (f"https://{slug}.jobs.personio.de", f"https://{slug}.jobs.personio.com"):
        try:
            raw = await net.fetch(f"{host}/xml", params={"language": "en"}, interval=0.5, tries=2)   # unknown names answer 429; do not hammer
            break
        except Exception:
            raw = None
    if not raw: raise LookupError("no Personio feed for this name")
    root = ET.fromstring(raw)
    for p in root.iter("position"):
        g = lambda tag: (p.findtext(tag) or "").strip()
        desc = "\n\n".join(f"{(jd.findtext('name') or '').strip()}\n{text(jd.findtext('value'))}" for jd in p.iter("jobDescription"))
        offices = [g("office")] + [o.text.strip() for o in p.iter("additionalOffice") if o.text]
        out.append(Job(
            title=g("name"), company=g("subcompany") or _slug_name(slug), location=", ".join(x for x in offices if x),
            department=g("department"), office=g("office"), employment_type=" ".join(x for x in (g("employmentType"), g("schedule")) if x),
            posted=iso(g("createdAt")), description=desc.strip(), url=f"{host}/job/{g('id')}", source="personio", source_id=g("id")))
    return out


async def recruitee(net, q, cfg, slug):
    d = await net.json(f"https://{slug}.recruitee.com/api/offers/", interval=0.5)
    out = []
    for j in d.get("offers", []):
        out.append(Job(
            title=j.get("title"), company=j.get("company_name") or _slug_name(slug),
            location=j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x),
            department=j.get("department", ""), office=j.get("city", ""), employment_type=j.get("employment_type_code", ""),
            remote=j.get("remote"), posted=iso(j.get("published_at") or j.get("created_at")), updated=iso(j.get("updated_at")),
            description="\n\n".join(x for x in (text(j.get("description")), text(j.get("requirements"))) if x),
            url=j.get("careers_url", ""), source="recruitee", source_id=str(j.get("id", ""))))
    return out


ATS = [
    Source("greenhouse", "Greenhouse", "board", "Global", greenhouse, home="https://docs.greenhouse.io/job-board.html"),
    Source("lever", "Lever", "board", "Global", lever, home="https://github.com/lever/postings-api"),
    Source("ashby", "Ashby", "board", "Global", ashby, home="https://developers.ashbyhq.com/docs/public-job-posting-api"),
    Source("smartrecruiters", "SmartRecruiters", "board", "Global", smartrecruiters, home="https://developers.smartrecruiters.com/docs/endpoints"),
    Source("workable", "Workable", "board", "Global", workable, interval=1.5, note="Public careers widget feed; keep request volume low.",
           home="https://apply.workable.com"),
    Source("personio", "Personio", "board", "Europe", personio, home="https://developer.personio.de/v1.0/reference/get_xml"),
    Source("recruitee", "Recruitee", "board", "Europe", recruitee, home="https://docs.recruitee.com/reference/intro-to-careers-site-api"),
]

# URL patterns that reveal which ATS a careers link belongs to, and the board name inside it.
PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([\w-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)"),
    ("workable", r"apply\.workable\.com/([\w-]+)"),
    ("workable", r"([\w-]+)\.workable\.com"),
    ("personio", r"([\w-]+)\.jobs\.personio\.(?:de|com)"),
    ("recruitee", r"([\w-]+)\.recruitee\.com"),
]
SKIP_SLUGS = {"www", "api", "apply", "embed", "jobs", "careers", "j", "v1"}


def detect(url_or_text: str) -> list[tuple[str, str]]:
    found = []
    for ats, pat in PATTERNS:
        for m in re.finditer(pat, url_or_text, re.I):
            slug = m.group(1).strip("/").lower()
            if slug not in SKIP_SLUGS and (ats, slug) not in found: found.append((ats, slug))
    return found
