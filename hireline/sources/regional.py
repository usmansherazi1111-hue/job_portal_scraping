"""Location-aware job search that needs no key: Workable's public job search (all employers hosting on Workable, every
country) and Rozee.pk (Pakistan). Both are paced, cached and fetched only where robots.txt allows."""
from __future__ import annotations
import re
from urllib.parse import quote
from ..model import Job, text, iso, clean
from .base import Source
from .pages import postings


def _place(*parts) -> str:
    return ", ".join(p for p in parts if p)


async def workablejobs(net, q, cfg):
    """jobs.workable.com/api/v1/jobs: server-side keyword + location search with full descriptions."""
    params = {"query": q.keywords}
    where = _place(q.location.title(), q.country_name if q.country else "")
    if where: params["location"] = where
    out, token = [], None
    for _ in range(10):
        d = await net.json("https://jobs.workable.com/api/v1/jobs", params={**params, **({"pageToken": token} if token else {})},
                           interval=1.0, ttl=3600)
        for j in d.get("jobs", []):
            loc = j.get("location") or {}
            places = [x for x in (j.get("locations") or []) if x and x != "TELECOMMUTE"]
            body = "\n\n".join(x for x in (text(j.get("description")), text(j.get("requirementsSection")),
                                           text(j.get("benefitsSection"))) if x)
            dept = j.get("department") or ""
            out.append(Job(
                title=j.get("title"), company=(j.get("company") or {}).get("title"),
                location=_place(loc.get("city"), loc.get("subregion"), loc.get("countryName")) or "; ".join(places),
                department="" if dept.lower() == "all published jobs" else dept, office="; ".join(places[:3]),
                employment_type=j.get("employmentType") or "", remote=(j.get("workplace") == "remote") if j.get("workplace") else None,
                posted=iso(j.get("created")), updated=iso(j.get("updated")), description=body[:20000], url=j.get("url", ""),
                source="workablejobs", source_id=j.get("id", ""), extra={"workplace": j.get("workplace")}))
        token = d.get("nextPageToken")
        if not token or len(out) >= max(q.limit * 2, 40): break
    return out


# ---------------------------------------------------------------- Rozee.pk
ROZEE = "https://www.rozee.pk"
ROZEE_GAP = 2.0          # measured: 1 req/s draws HTTP 429, one every 2 s does not
ROZEE_DETAILS = 8        # full pages fetched per search; the rest are fetched when a job is opened
CARD = re.compile(r'<div class="job border-bottom')
CITY_OPT = re.compile(r'<option value="(\d+)"\s*>\s*([^<]{2,40}?)\s*</option>')
DETAIL_ROW = re.compile(r"\|([A-Z][A-Za-z ]{2,30}):\|([^|]{1,120})")


def _rozee_cards(html: str) -> list[Job]:
    out = []
    for chunk in CARD.split(html)[1:]:
        chunk = chunk.split('<div class="clearfix"></div> <div class="job border-bottom')[0][:6000]
        m = re.search(r'<h3[^>]*title="([^"]*)"[^>]*>\s*<a[^>]*href="([^"?]+)', chunk)
        if not m: continue
        title, href = m.group(1), m.group(2)
        url = "https:" + href if href.startswith("//") else href
        cname = re.search(r'(?s)<div class="cname[^"]*">(.*?)</div>', chunk)
        anchors = [clean(re.sub(r"<[^>]+>", "", a)) for a in re.findall(r"(?s)<a[^>]*>(.*?)</a>", cname.group(1))] if cname else []
        company = anchors[0] if anchors else ""
        place = ", ".join(a for a in anchors[1:] if a)
        snip = re.search(r'(?s)<div class="jbody[^"]*">\s*<bdi[^>]*>(.*?)</bdi>', chunk)
        date = re.search(r'(?s)title="Posted On"[^>]*>.*?</i>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})', chunk)
        exp = re.search(r'(?s)title="Experience"[^>]*>\s*([^<]+?)\s*<', chunk)
        jid = re.search(r"-jobs-(\d+)", url)
        out.append(Job(title=title, company=company, location=place, description=text(snip.group(1)) if snip else "",
                       posted=iso(date.group(1)) if date else "", url=url, source="rozee", source_id=jid.group(1) if jid else url,
                       extra={"experience": exp.group(1).strip()} if exp else {}))
    return out


async def rozee_detail(net, job: Job):
    """The job page's schema.org JobPosting gives the full description, dates and address; the details table adds the rest."""
    if job.extra.get("detailed"): return
    try:
        html = (await net.fetch(job.url, check_robots=True, interval=ROZEE_GAP, ttl=86400)).decode("utf-8", "ignore")
    except Exception:
        return
    job.extra["detailed"] = True
    ld = postings(html, job.url)
    if ld:
        p = ld[0]
        job.description = p.description or job.description
        job.posted = p.posted or job.posted
        job.location = p.location or job.location
        if p.employment_type and p.employment_type.upper() != "OTHER": job.employment_type = p.employment_type.replace("_", " ").title()
        job.salary = p.salary or job.salary
        job.extra.update({k: v for k, v in p.extra.items() if v})
    i = html.find("Job Details")
    if i > 0:
        block = re.sub(r"(?s)<script.*?</script>", "", html[i:i + 9000])
        flat = re.sub(r"(\|\s*)+", "|", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", block)))
        rows = {k.strip().lower(): v.strip() for k, v in DETAIL_ROW.findall(flat)}
        job.department = clean(rows.get("functional area") or rows.get("department") or rows.get("industry") or job.department)
        job.office = clean(rows.get("job location", "")) or job.office
        if not job.employment_type: job.employment_type = clean(rows.get("job type", ""))
        for k in ("career level", "minimum education", "total positions", "job shift", "minimum experience", "maximum experience"):
            if rows.get(k): job.extra[k.replace(" ", "_")] = clean(rows[k])


async def rozee(net, q, cfg):
    if q.country and q.country != "pk": return []
    kw = quote(q.keywords.strip() or "all", safe="")
    base = f"{ROZEE}/job/jsearch/q/{kw}"
    first = (await net.fetch(base, check_robots=True, interval=ROZEE_GAP, ttl=1800)).decode("utf-8", "ignore")
    if q.location:
        cities = {name.strip().lower(): cid for cid, name in CITY_OPT.findall(first)}
        cid = next((cities[c] for c in q.city_words() if c in cities), None)
        if not cid: return []                              # Rozee has no such city: nothing local to return
        base = f"{base}/fc/{cid}"
        first = (await net.fetch(base, check_robots=True, interval=ROZEE_GAP, ttl=1800)).decode("utf-8", "ignore")
    out = _rozee_cards(first)
    page = 20
    while len(out) < q.limit and page <= 80:
        html = (await net.fetch(f"{base}/?fpn={page}", check_robots=True, interval=ROZEE_GAP, ttl=1800)).decode("utf-8", "ignore")
        cards = _rozee_cards(html)
        if not cards: break
        out += cards; page += 20
    out = [j for j in out if q.place_ok(j)][: q.limit]
    for j in out: j.extra["kw_by_source"] = True      # Rozee searched the full posting; the card only has a snippet
    # Full details for the first jobs, one at a time at Rozee's pace; the rest load when opened in the app.
    for j in out[:ROZEE_DETAILS]: await rozee_detail(net, j)
    return out


REGIONAL = [
    Source("workablejobs", "Workable job search", "search", "Global, by city", workablejobs, ttl=3600, interval=1.0,
           note="Public search over every employer that hosts jobs on Workable. Paced at 1 request/s; robots.txt allows /api.",
           home="https://jobs.workable.com"),
    Source("rozee", "Rozee.pk", "search", "Pakistan", rozee, ttl=1800, interval=ROZEE_GAP,
           note="Pakistan's largest job site. Search and job pages only (robots.txt allows them), 1 request per 2 s. Full text for the "
                "first 8 jobs per search; any other job loads its full text when you open it.", home="https://www.rozee.pk"),
]
