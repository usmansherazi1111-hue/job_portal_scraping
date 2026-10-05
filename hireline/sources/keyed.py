"""Official APIs that need a free key (Reed, USAJOBS, Adzuna, Jooble) and the Canada Job Bank open-data CSV."""
from __future__ import annotations
import csv, re
from urllib.parse import quote_plus
import httpx
from ..model import Job, text, iso, money
from .base import Source

ADZUNA_COUNTRIES = {"gb", "us", "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "in", "it", "mx", "nl", "nz", "pl", "sg", "za"}


async def reed(net, q, cfg):
    if q.country and q.country != "gb": return []
    out, skip = [], 0
    while len(out) < q.limit:
        params = {"keywords": q.keywords, "resultsToTake": 100, "resultsToSkip": skip}
        if q.location: params["locationName"] = q.location
        d = await net.json("https://www.reed.co.uk/api/1.0/search", params=params, auth=(cfg["REED_API_KEY"], ""), interval=0.5)
        rows = d.get("results", [])
        out += [Job(title=j.get("jobTitle"), company=j.get("employerName"), location=j.get("locationName"),
                    salary=money(j.get("minimumSalary"), j.get("maximumSalary"), j.get("currency") or "GBP"),
                    posted=iso(j.get("date")), description=text(j.get("jobDescription")), url=j.get("jobUrl", ""),
                    source="reed", source_id=str(j.get("jobId", "")), extra={"expires": iso(j.get("expirationDate"))}) for j in rows]
        skip += len(rows)
        if len(rows) < 100 or skip >= d.get("totalResults", 0): break
    return out


async def usajobs(net, q, cfg):
    if q.country and q.country != "us": return []
    params = {"ResultsPerPage": min(max(q.limit, 25), 500)}
    if q.keywords: params["Keyword"] = q.keywords
    if q.location: params["LocationName"] = q.location
    if q.days: params["DatePosted"] = min(q.days, 60)
    hdr = {"Host": "data.usajobs.gov", "User-Agent": cfg["USAJOBS_EMAIL"], "Authorization-Key": cfg["USAJOBS_API_KEY"]}
    d = await net.json("https://data.usajobs.gov/api/search", params=params, headers=hdr, interval=0.5)
    out = []
    for it in (d.get("SearchResult") or {}).get("SearchResultItems", []):
        m = it.get("MatchedObjectDescriptor") or {}
        pay = (m.get("PositionRemuneration") or [{}])[0]
        det = ((m.get("UserArea") or {}).get("Details") or {})
        out.append(Job(title=m.get("PositionTitle"), company=m.get("OrganizationName"), location=m.get("PositionLocationDisplay"),
                       department=m.get("DepartmentName", ""), office=m.get("OrganizationName", ""),
                       employment_type=", ".join(x.get("Name", "") for x in m.get("PositionSchedule") or []),
                       salary=money(pay.get("MinimumRange"), pay.get("MaximumRange"), "USD", pay.get("Description", "")),
                       posted=iso(m.get("PublicationStartDate")), description=text(det.get("JobSummary") or m.get("QualificationSummary")),
                       url=m.get("PositionURI", ""), source="usajobs", source_id=str(m.get("PositionID", "")),
                       extra={"closes": iso(m.get("ApplicationCloseDate"))}))
    return out


async def adzuna(net, q, cfg):
    cc = q.country or "gb"
    if cc not in ADZUNA_COUNTRIES: return []
    out = []
    for page in range(1, 1 + max(1, min(5, (q.limit + 49) // 50))):   # free tier: 250 calls/day, so few pages
        params = {"app_id": cfg["ADZUNA_APP_ID"], "app_key": cfg["ADZUNA_APP_KEY"], "results_per_page": 50, "content-type": "application/json"}
        if q.keywords: params["what"] = q.keywords
        if q.location: params["where"] = q.location
        if q.days: params["max_days_old"] = q.days
        d = await net.json(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/{page}", params=params, interval=2.5, ttl=6 * 3600)
        rows = d.get("results", [])
        out += [Job(title=j.get("title"), company=(j.get("company") or {}).get("display_name"),
                    location=(j.get("location") or {}).get("display_name"), department=(j.get("category") or {}).get("label", ""),
                    employment_type=" ".join(x for x in (j.get("contract_time"), j.get("contract_type")) if x).replace("_", " "),
                    salary=money(j.get("salary_min"), j.get("salary_max")), posted=iso(j.get("created")),
                    description=text(j.get("description")), url=j.get("redirect_url", ""), source="adzuna", source_id=str(j.get("id", "")))
                for j in rows]
        if len(rows) < 50: break
    return out


async def jooble(net, q, cfg):
    body = {"keywords": q.keywords, "location": q.location or (q.country_name if q.country else ""), "page": "1"}
    d = await net.json(f"https://jooble.org/api/{cfg['JOOBLE_API_KEY']}", method="POST", body=body, interval=2.0, ttl=12 * 3600)  # 500 calls per key, ever
    return [Job(title=j.get("title"), company=j.get("company"), location=j.get("location"), employment_type=j.get("type", ""),
                salary=j.get("salary", ""), posted=iso(j.get("updated")), description=text(j.get("snippet")),
                url=j.get("link", ""), source="jooble", source_id=str(j.get("id", "")), extra={"via": j.get("source")})
            for j in d.get("jobs", [])]


def _col(header: list[str], *names) -> int | None:
    for n in names:
        for i, h in enumerate(header):
            if n in h.lower(): return i
    return None


async def jobbank(net, q, cfg):
    """Latest monthly CSV from open.canada.ca (Open Government Licence - Canada). Streamed and filtered on the fly."""
    if q.country and q.country != "ca": return []
    pkg = await net.json("https://open.canada.ca/data/api/action/package_show", params={"id": "ea639e28-c0fc-48bf-b5dd-b8899bd43072"}, ttl=86400)
    res = [r for r in (pkg.get("result") or {}).get("resources", []) if (r.get("format") or "").upper() == "CSV" and "-en-" in (r.get("url") or "")]
    if not res: return []
    res.sort(key=lambda r: r.get("last_modified") or r.get("created") or "", reverse=True)
    url = res[0]["url"]
    path = net_data_dir() / ("jobbank_" + re.sub(r"[^\w.-]", "_", url.rsplit("/", 1)[-1]))
    if not path.exists():   # one download per monthly file, then read from disk
        tmp = path.with_suffix(".part")
        async with net._client().stream("GET", url, timeout=httpx.Timeout(300, connect=15)) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                async for chunk in r.aiter_bytes(): f.write(chunk)
        tmp.replace(path)
    head = path.read_bytes()[:4]
    enc = "utf-16" if head[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    out = []
    with open(path, encoding=enc, errors="ignore", newline="") as f:
        first = f.readline()
        delim = "\t" if first.count("\t") > first.count(",") else ","
        header = next(csv.reader([first], delimiter=delim))
        ix = {k: _col(header, *v) for k, v in {"title": ("job title", "title"), "company": ("employer", "business name"),
              "city": ("city",), "prov": ("province",), "date": ("first posting", "date posted", "posting date"),
              "noc": ("noc21 code name", "noc 2016 code name", "noc"), "sal": ("salary condition detail", "salary", "wage"),
              "type": ("employment type", "employment term"), "id": ("snapshot id", "job bank", "id")}.items()}
        na = lambda v: "" if v.upper() in ("NA", "N/A") else v
        for row in csv.reader(f, delimiter=delim):
            g = lambda k: na(row[ix[k]].strip()) if ix.get(k) is not None and ix[k] < len(row) else ""
            title, city = g("title"), g("city")
            j = Job(title=title[:1].upper() + title[1:], company=g("company"), location=", ".join(x for x in (city, g("prov"), "Canada") if x),
                    department=g("noc"), employment_type=g("type"), salary=g("sal"), posted=iso(g("date")),
                    url="https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring=" + quote_plus(title) +
                        ("&locationstring=" + quote_plus(city) if city else ""),
                    source="jobbank", source_id=g("id"))
            if j.title and q.matches(j):
                out.append(j)
                if len(out) >= q.limit * 3: break
    return out


def net_data_dir():
    from ..net import DATA
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA


KEYED = [
    Source("reed", "Reed.co.uk", "search", "UK", reed, needs=("REED_API_KEY",), note="Free key from reed.co.uk/developers.", signup="https://www.reed.co.uk/developers/jobseeker",
           home="https://www.reed.co.uk/developers/jobseeker"),
    Source("usajobs", "USAJOBS", "search", "US federal", usajobs, needs=("USAJOBS_API_KEY", "USAJOBS_EMAIL"),
           note="Free key from developer.usajobs.gov; User-Agent must be your email.", signup="https://developer.usajobs.gov/apirequest/", home="https://developer.usajobs.gov/guides/authentication"),
    Source("adzuna", "Adzuna", "search", "19 countries", adzuna, needs=("ADZUNA_APP_ID", "ADZUNA_APP_KEY"), ttl=6 * 3600, interval=2.5,
           note="Free tier 250 calls/day; 'Jobs by Adzuna' attribution; commercial use needs a licence.", signup="https://developer.adzuna.com/signup", home="https://developer.adzuna.com/docs/terms_of_service"),
    Source("jooble", "Jooble", "search", "70+ countries", jooble, needs=("JOOBLE_API_KEY",), ttl=12 * 3600, interval=2.0,
           note="Covers 70+ countries incl. Pakistan, UAE, Saudi Arabia. Free key has 500 requests; results are cached 12 h to save them.", signup="https://jooble.org/api/about", home="https://jooble.org/api/about"),
    Source("jobbank", "Job Bank Canada (open data)", "search", "Canada", jobbank, ttl=86400, default=False,
           note="Monthly statistics snapshot (46 MB, downloaded once a month): titles, city, wage and NOC occupation only, no employer name or description. Open Government Licence - Canada.", home="https://open.canada.ca/data/en/dataset/ea639e28-c0fc-48bf-b5dd-b8899bd43072"),
]
