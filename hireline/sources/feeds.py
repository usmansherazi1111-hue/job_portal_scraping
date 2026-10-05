"""Keyword-search sources that need no key: open job APIs, RSS feeds, a public government endpoint and HN."""
from __future__ import annotations
import asyncio, base64, re
import xml.etree.ElementTree as ET
from ..model import Job, text, iso, money
from .base import Source


async def arbeitnow(net, q, cfg):
    out = []
    for page in range(1, 4):
        d = await net.json("https://www.arbeitnow.com/api/job-board-api", params={"page": page}, interval=1.0, ttl=3600)
        for j in d.get("data", []):
            out.append(Job(title=j.get("title"), company=j.get("company_name"), location=j.get("location"),
                           department=", ".join(j.get("tags") or []), employment_type=", ".join(j.get("job_types") or []),
                           remote=j.get("remote"), posted=iso(j.get("created_at")), description=text(j.get("description")),
                           url=j.get("url", ""), source="arbeitnow", source_id=j.get("slug", "")))
        if not (d.get("links") or {}).get("next"): break
    return out


async def themuse(net, q, cfg):
    params = {"page": 0, "descending": "true"}
    if q.location and q.country: params["location"] = f"{q.location.title()}, {q.country_name}"
    if cfg.get("MUSE_API_KEY"): params["api_key"] = cfg["MUSE_API_KEY"]
    out = []
    for page in range(0, 10):
        d = await net.json("https://www.themuse.com/api/public/jobs", params={**params, "page": page}, interval=0.5)
        for j in d.get("results", []):
            out.append(Job(title=j.get("name"), company=(j.get("company") or {}).get("name"),
                           location="; ".join(x.get("name", "") for x in j.get("locations") or []),
                           department=", ".join(x.get("name", "") for x in j.get("categories") or []),
                           employment_type=", ".join(x.get("name", "") for x in j.get("levels") or []),
                           posted=iso(j.get("publication_date")), description=text(j.get("contents")),
                           url=(j.get("refs") or {}).get("landing_page", ""), source="themuse", source_id=str(j.get("id", ""))))
        if page + 1 >= d.get("page_count", 0) or len([j for j in out if q.matches(j)]) >= q.limit: break
    return out


async def remoteok(net, q, cfg):
    d = await net.json("https://remoteok.com/api", interval=2.0, ttl=3600)
    out = []
    for j in d[1:] if isinstance(d, list) else []:
        out.append(Job(title=j.get("position"), company=j.get("company"), location=j.get("location") or "Remote",
                       department=", ".join(j.get("tags") or []), remote=True, salary=money(j.get("salary_min"), j.get("salary_max"), "USD"),
                       posted=iso(j.get("date") or j.get("epoch")), description=text(j.get("description")),
                       url=j.get("url", ""), source="remoteok", source_id=str(j.get("id", ""))))
    return out


async def remotive(net, q, cfg):
    params = {"limit": 300}
    if q.keywords: params["search"] = q.keywords
    d = await net.json("https://remotive.com/api/remote-jobs", params=params, interval=2.0, ttl=6 * 3600)  # they ask for <= 4 calls a day
    return [Job(title=j.get("title"), company=j.get("company_name"), location=j.get("candidate_required_location") or "Remote",
                department=j.get("category", ""), employment_type=(j.get("job_type") or "").replace("_", " "), remote=True,
                salary=j.get("salary", ""), posted=iso(j.get("publication_date")), description=text(j.get("description")),
                url=j.get("url", ""), source="remotive", source_id=str(j.get("id", ""))) for j in d.get("jobs", [])]


def _himalayas_job(j):
    return Job(title=j.get("title"), company=j.get("companyName"), location=", ".join(j.get("locationRestrictions") or []) or "Remote (worldwide)",
               department=", ".join((j.get("parentCategories") or []) or (j.get("categories") or j.get("category") or [])[:3]),
               employment_type=j.get("employmentType", ""), remote=True,
               salary=money(j.get("minSalary"), j.get("maxSalary"), j.get("currency") or "", j.get("salaryPeriod") or ""),
               posted=iso(j.get("pubDate")), description=text(j.get("description")), url=j.get("applicationLink") or j.get("guid", ""),
               source="himalayas", source_id=j.get("guid", ""))


async def himalayas(net, q, cfg):
    out = []
    params = {"sort": "recent"}
    if q.keywords: params["q"] = q.keywords
    if q.country: params["country"] = q.country.upper()
    for page in range(1, 6):
        d = await net.json("https://himalayas.app/jobs/api/search", params={**params, "page": page}, interval=1.0)
        rows = d.get("jobs", []) if isinstance(d, dict) else d
        out += [_himalayas_job(j) for j in rows]
        if len(rows) < 20 or len(out) >= q.limit: break
    return out


async def jobicy(net, q, cfg):
    params = {"count": 100}
    if q.keywords: params["tag"] = q.keywords
    geo = {"us": "usa", "gb": "uk", "ca": "canada", "de": "germany", "au": "australia"}.get(q.country)
    if geo: params["geo"] = geo
    d = await net.json("https://jobicy.com/api/v2/remote-jobs", params=params, interval=2.0, ttl=3600)  # they ask for hourly polling at most
    return [Job(title=j.get("jobTitle"), company=j.get("companyName"), location=j.get("jobGeo") or "Remote",
                department=", ".join(j.get("jobIndustry") or []), employment_type=", ".join(j.get("jobType") or []), remote=True,
                salary=money(j.get("salaryMin") or j.get("annualSalaryMin"), j.get("salaryMax") or j.get("annualSalaryMax"), j.get("salaryCurrency", "")),
                posted=iso(j.get("pubDate")), description=text(j.get("jobDescription") or j.get("jobExcerpt")),
                url=j.get("url", ""), source="jobicy", source_id=str(j.get("id", ""))) for j in d.get("jobs", [])]


async def weworkremotely(net, q, cfg):
    raw = await net.fetch("https://weworkremotely.com/remote-jobs.rss", interval=2.0, ttl=3600)
    out = []
    for it in ET.fromstring(raw).iter("item"):
        g = lambda t: (it.findtext(t) or "").strip()
        company, _, title = g("title").partition(":")
        if not title: company, title = "", company
        out.append(Job(title=title, company=company, location=g("region") or "Remote", department=g("category"), remote=True,
                       employment_type=g("type"), posted=iso(g("pubDate")), description=text(g("description")),
                       url=g("link") or g("guid"), source="weworkremotely", source_id=g("guid")))
    return out


HN_ROLE = re.compile(r"(?i)engineer|developer|programmer|scientist|designer|manager|architect|analyst|lead\b|head of|director|"
                     r"\bcto\b|\bvp\b|founding|researcher|sre\b|devops|recruiter|marketer|marketing|sales|account exec|"
                     r"specialist|consultant|intern\b|technician|administrator|writer|product|data|ml\b|ai\b|frontend|backend|full.?stack|roles?\b|positions?\b")
HN_PLACE = re.compile(r"(?i)remote|onsite|on-site|hybrid|in.?office|\b(usa?|uk|eu|emea|nyc|sf|bay area|europe|canada|london|berlin|"
                      r"new york|san francisco|toronto|amsterdam|paris|worldwide|anywhere|munich|dublin|zurich|singapore|bangalore|seattle|boston|austin|"
                      r"chicago|los angeles|denver|tel aviv|stockholm|copenhagen|barcelona|madrid|lisbon|warsaw|sydney|melbourne|tokyo|"
                      r"(?-i:[A-Z]{2})\b)")


async def hackernews(net, q, cfg):
    """Latest monthly 'Ask HN: Who is hiring?' thread. Each top-level comment is one company: 'Company | Role | Location | ...'."""
    s = await net.json("https://hn.algolia.com/api/v1/search_by_date", params={"tags": "story,author_whoishiring", "query": "who is hiring"}, ttl=6 * 3600)
    story = next((h for h in s.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()), None)
    if not story: return []
    d = await net.json(f"https://hn.algolia.com/api/v1/items/{story['objectID']}", ttl=3 * 3600)
    out = []
    for c in d.get("children", []):
        body = text(c.get("text"))
        if not body: continue
        head = body.split("\n", 1)[0]
        parts = [p.strip() for p in head.split("|")]
        if len(parts) < 2: continue
        rest = [p for p in parts[1:] if p and not re.search(r"(?i)https?://|www\.|\$|€|£|^\s*(full|part).?time\s*$|^\s*(contract|intern(ship)?|visa.*)\s*$", p)]
        roles = [p for p in rest if HN_ROLE.search(p)]
        places = [p for p in rest if p not in roles and HN_PLACE.search(p)]
        loc = "; ".join(places[:2])
        if not roles:
            others = [p for p in rest if p not in places]
            if not others: continue                       # no recognisable role: skip rather than show a location as a title
            roles = others
        role = roles[0]
        out.append(Job(title=role, company=parts[0], location=loc, remote=bool(re.search(r"(?i)remote", head)) or None,
                       employment_type=next((p for p in parts if re.search(r"(?i)full.?time|part.?time|contract|intern", p)), ""),
                       salary=next((p for p in parts if re.search(r"[$€£]\s?\d", p)), ""), posted=iso(c.get("created_at")),
                       description=body, url=f"https://news.ycombinator.com/item?id={c.get('id')}", source="hackernews",
                       source_id=str(c.get("id", "")), extra={"thread": story.get("title")}))
    return out


BA = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
BA_HDR = {"X-API-Key": "jobboerse-jobsuche"}


def _ba_job(j) -> Job:
    """v6 list item ('ergebnisliste'); older v4 items ('stellenangebote') are read too."""
    if "stellenangebotsTitel" in j or "stellenlokationen" in j:
        locs = [(x.get("adresse") or {}) for x in j.get("stellenlokationen") or []]
        a = locs[0] if locs else {}
        ref = j.get("referenznummer") or j.get("refnr", "")
        lo, hi = j.get("gehaltsspanneVon"), j.get("gehaltsspanneBis")
        return Job(title=j.get("stellenangebotsTitel") or j.get("hauptberuf"), company=j.get("firma"),
                   location=", ".join(x for x in (a.get("ort"), (a.get("region") or "").replace("_", " ").title(), "Germany") if x),
                   department=j.get("hauptberuf", ""), office="; ".join(x.get("ort", "") for x in locs[1:4] if x.get("ort")),
                   employment_type="Full-time" if j.get("arbeitszeitVollzeit") else "",
                   remote=True if j.get("homeofficemoeglich") else None,
                   salary=money(lo, hi, "EUR", "per year" if j.get("verguetungsangabe") == "JAHRESGEHALT" else ""),
                   posted=iso(j.get("datumErsteVeroeffentlichung") or (j.get("veroeffentlichungszeitraum") or {}).get("von")),
                   updated=iso(j.get("aenderungsdatum")), url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
                   source="arbeitsagentur", source_id=ref)
    o = j.get("arbeitsort") or {}
    ref = j.get("refnr", "")
    return Job(title=j.get("titel") or j.get("beruf"), company=j.get("arbeitgeber"),
               location=", ".join(x for x in (o.get("ort"), o.get("region"), o.get("land")) if x), department=j.get("beruf", ""),
               posted=iso(j.get("aktuelleVeroeffentlichungsdatum")), updated=iso(j.get("modifikationsTimestamp")),
               url=j.get("externeUrl") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}", source="arbeitsagentur", source_id=ref)


async def arbeitsagentur(net, q, cfg):
    if q.country and q.country != "de": return []
    params = {"angebotsart": 1, "size": min(max(q.limit, 25), 100), "page": 1}
    if q.keywords: params["was"] = q.keywords
    if q.location: params["wo"] = q.location
    d = await net.json(f"{BA}/v6/jobs", params=params, headers=BA_HDR, interval=1.0)
    out = [_ba_job(j) for j in (d.get("ergebnisliste") or d.get("stellenangebote") or [])]
    # The list has no description: read it from the details endpoint for the first jobs (bounded, paced, cached a day).
    async def detail(job):
        try:
            ref = base64.b64encode(job.source_id.encode()).decode()
            dj = await net.json(f"{BA}/v4/jobdetails/{ref}", headers=BA_HDR, interval=0.5, ttl=86400)
            job.description = text(dj.get("stellenangebotsBeschreibung") or "") or job.description
        except Exception:
            pass
    sem = asyncio.Semaphore(3)
    async def one(j):
        async with sem: await detail(j)
    await asyncio.gather(*(one(j) for j in out[: min(q.limit, 25)]))
    return out


FEEDS = [
    Source("arbeitnow", "Arbeitnow", "search", "Europe (DE)", arbeitnow, filters_locally=True, ttl=3600,
           note="Free public API; link back to arbeitnow.com.", home="https://www.arbeitnow.com/blog/job-board-api"),
    Source("themuse", "The Muse", "search", "US / global", themuse, filters_locally=True,
           note="500 req/hour without a key, 3,600 with a free key.", home="https://www.themuse.com/developers/api/v2"),
    Source("remoteok", "Remote OK", "search", "Remote", remoteok, filters_locally=True, ttl=3600, interval=2.0,
           note="Link back to Remote OK and name it as the source.", home="https://remoteok.com/api"),
    Source("remotive", "Remotive", "search", "Remote", remotive, ttl=6 * 3600, interval=2.0,
           note="Credit Remotive, 24 h delay, max ~4 calls a day; terms forbid using its jobs to collect emails.", home="https://remotive.com/remote-jobs/api"),
    Source("himalayas", "Himalayas", "search", "Remote", himalayas,
           note="Link back and credit Himalayas; do not resubmit jobs to other boards.", home="https://himalayas.app/api"),
    Source("jobicy", "Jobicy", "search", "Remote", jobicy, ttl=3600, interval=2.0,
           note="Last 7 days only; keep Jobicy as source; poll hourly at most.", home="https://jobicy.com/jobs-rss-feed"),
    Source("weworkremotely", "We Work Remotely", "search", "Remote", weworkremotely, filters_locally=True, ttl=3600, interval=2.0,
           note="RSS; attribute links back to We Work Remotely.", home="https://weworkremotely.com/remote-job-rss-feed"),
    Source("hackernews", "Hacker News: Who is hiring", "search", "Global tech", hackernews, filters_locally=True, ttl=3 * 3600,
           note="Parsed from free-text comments; check each row.", home="https://github.com/HackerNews/API"),
    Source("arbeitsagentur", "Bundesagentur fur Arbeit", "search", "Germany", arbeitsagentur,
           note="Public endpoint documented by bund.dev, not an official API. No description in the list view.", home="https://github.com/bundesAPI/jobsuche-api"),
]
