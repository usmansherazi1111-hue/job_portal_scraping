import asyncio, io, json, os, tempfile
from pathlib import Path
import httpx, pytest

os.environ["HIRELINE_DATA"] = tempfile.mkdtemp()
from hireline import demo, export                      # noqa: E402
from hireline.engine import Run, execute, parse_targets  # noqa: E402
from hireline.model import Job, iso, text              # noqa: E402
from hireline.net import Net, Blocked                  # noqa: E402
from hireline.sources import SOURCES, Query            # noqa: E402

SEARCH = [s.id for s in SOURCES.values() if s.group == "search"]


def run_search(q, sources=(), targets=(), cfg=None):
    async def go():
        net = Net(cache_path=Path(tempfile.mkdtemp()) / "c.sqlite", transport=demo.transport())
        r = Run(q, list(sources), list(targets))
        await execute(r, net, cfg if cfg is not None else demo.DEMO_KEYS)
        await net.close()
        return r
    return asyncio.run(go())


def test_counts():
    assert len(SEARCH) == 16 and len([s for s in SOURCES.values() if s.group == "board"]) == 7
    assert len(SOURCES) == 24


@pytest.mark.parametrize("sid", SEARCH)
def test_every_search_source_parses(sid):
    r = run_search(Query(limit=50), [sid])
    st = r.status[sid]
    assert st["state"] == "done", st
    assert r.jobs, sid
    j = r.jobs[0]
    assert j.title and j.url.startswith("http") and j.source == sid
    assert j.company or sid == "hackernews"


@pytest.mark.parametrize("ats", ["greenhouse", "lever", "ashby", "smartrecruiters", "workable", "personio", "recruitee"])
def test_every_board_parses(ats):
    r = run_search(Query(limit=50), [], [f"{ats}:acme"])
    assert r.status[f"{ats}:acme"]["state"] == "done", r.status
    j = r.jobs[0]
    assert j.title and j.company and j.location and j.url and j.posted, j
    assert j.description, f"{ats} description empty"


def test_greenhouse_fields_quality():
    r = run_search(Query(limit=50), [], ["greenhouse:acme"])
    j = next(j for j in r.jobs if j.title == "Senior Python Engineer")
    assert (j.company, j.location, j.department, j.office) == ("Acme Inc", "London, United Kingdom", "Engineering", "London HQ")
    assert j.posted == "2026-09-20" and j.updated == "2026-10-01"
    assert "<" not in j.description and "Python, SQL" in j.description


def test_autodetect_name_and_careers_page():
    r = run_search(Query(limit=50), [], ["acme", "https://www.acme-example.com/careers"])
    found = {k for k in r.status if k.startswith(("greenhouse:", "lever:", "ashby:"))}
    assert {"greenhouse:acme", "lever:acme", "ashby:acme"} <= found
    assert r.status["detect:acme"]["state"] == "done"
    titles = {j.title for j in r.jobs}
    assert "Office Manager" in titles            # JSON-LD on the careers page
    assert "Senior Python Engineer" in titles    # Greenhouse board linked from the careers page


def test_unknown_company_reports_clearly():
    r = run_search(Query(), [], ["nosuchco"])
    assert r.status["detect:nosuchco"]["state"] == "error"


def test_keyword_and_country_filter_and_dedupe():
    r = run_search(Query(keywords="python", country="gb", limit=50), SEARCH)
    assert r.jobs
    for j in r.jobs:
        assert "python" in f"{j.title} {j.description} {j.department}".lower()
    keys = [j.key for j in r.jobs]
    assert len(keys) == len(set(keys))
    # country-scoped sources skip other countries without calling out
    assert r.status["usajobs"]["kept"] == 0 and r.status["arbeitsagentur"]["kept"] == 0
    # strict place: every kept job is located in the UK (no "Europe, UK"/"Anywhere" remote rows unless asked for)
    for j in r.jobs:
        assert any(w in j.location.lower() for w in ("united kingdom", "london", "uk", "leeds", "manchester")), j.location
        assert "anywhere" not in j.location.lower()


def test_city_search_is_strict():
    r = run_search(Query(keywords="python", location="Lahore", country="pk", limit=50), SEARCH)
    assert r.jobs and all("lahore" in j.location.lower() for j in r.jobs), [(j.source, j.location) for j in r.jobs]
    srcs = {j.source for j in r.jobs}
    assert {"workablejobs", "rozee"} <= srcs
    roz = next(j for j in r.jobs if j.source == "rozee")
    assert roz.description.startswith("We need a Python") and roz.posted == "2026-10-02" and roz.department == "Software & Web Development"
    assert r.status["remotive"]["kept"] == 0 and r.status["weworkremotely"]["kept"] == 0   # remote-anywhere jobs are not in Lahore


def test_remote_toggle_adds_remote_jobs():
    strict = run_search(Query(keywords="python", country="gb", limit=50), ["weworkremotely", "jobicy"])
    loose = run_search(Query(keywords="python", country="gb", limit=50, remote=True), ["weworkremotely", "jobicy"])
    # "UK, Europe" (jobicy) is open to UK residents and stays; "Anywhere in the World" (WWR) only comes with the toggle
    assert {j.source for j in strict.jobs} == {"jobicy"} and {j.source for j in loose.jobs} == {"weworkremotely", "jobicy"}


def test_limit_reports_found_matched_kept():
    r = run_search(Query(limit=1), [], ["greenhouse:acme"])
    st = r.status["greenhouse:acme"]
    assert (st["found"], st["matched"], st["kept"]) == (3, 3, 1) and "limited" in st["error"] and len(r.jobs) == 1


def test_arbeitsagentur_v6_and_details():
    r = run_search(Query(keywords="python", limit=50), ["arbeitsagentur"])
    j = r.jobs[0]
    assert j.company == "Munich Soft GmbH" and j.location.startswith("München") and j.description.startswith("Python, FastAPI") and "60,000" in j.salary


def test_missing_key_is_skipped_not_failed():
    r = run_search(Query(), ["reed", "arbeitnow"], cfg={})
    assert r.status["reed"]["state"] == "skipped" and r.status["arbeitnow"]["state"] == "done"


def test_parse_targets():
    b, p, n = parse_targets(["smartrecruiters:Visa", "greenhouse:Stripe", "https://jobs.lever.co/palantir/abc", "https://acme.recruitee.com/o/x", "www.foo.com/careers", "Big Co"])
    assert ("smartrecruiters", "Visa") in b and ("greenhouse", "stripe") in b and ("lever", "palantir") in b and ("recruitee", "acme") in b
    assert p == ["www.foo.com/careers"] and n == ["bigco"]


def test_exports_roundtrip():
    r = run_search(Query(limit=50), ["arbeitnow", "remoteok"], ["greenhouse:acme"])
    meta = {"tool": "test"}
    assert export.to_csv(r.jobs).decode("utf-8-sig").splitlines()[0].startswith("title,company,location,department,office")
    data = json.loads(export.to_json(r.jobs, meta))
    assert len(data["jobs"]) == len(r.jobs) and data["jobs"][0]["description"]
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(export.to_xlsx(r.jobs, list(r.status.values()), meta)))
    assert wb.sheetnames == ["Jobs", "Companies", "Sources", "About"]
    assert wb["Jobs"].max_row == len(r.jobs) + 1


def test_helpers():
    assert iso(1790800000000) == iso(1790800000) == "2026-09-30"
    assert iso("Oct 02, 2026") == iso("2026/10/02") == "2026-10-02"
    assert iso("02/10/2026") == "2026-10-02" and iso("Fri, 03 Oct 2026 10:00:00 +0000") == "2026-10-03"
    assert text("&lt;p&gt;A&lt;/p&gt;&lt;p&gt;B &amp;amp; C&lt;/p&gt;") == "A\n\nB & C"
    assert Job(title="X", company="Acme Ltd", location="London, UK").key == Job(title="x", company="ACME", location="London").key


def test_retry_after_and_blocked():
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        if req.url.host == "a.test": return httpx.Response(429, headers={"Retry-After": "0"}) if calls["n"] == 1 else httpx.Response(200, json={"ok": 1})
        return httpx.Response(403)
    async def go():
        net = Net(cache_path=Path(tempfile.mkdtemp()) / "c.sqlite", transport=httpx.MockTransport(h))
        assert await net.json("https://a.test/x", interval=0) == {"ok": 1}
        assert await net.json("https://a.test/x", interval=0) == {"ok": 1}   # second call served from cache
        with pytest.raises(Blocked): await net.fetch("https://b.test/y", interval=0)
        s = dict(net.stats); await net.close(); return s
    s = asyncio.run(go())
    assert s["retries"] == 1 and s["cache_hits"] == 1


def test_robots_respected():
    def h(req):
        if req.url.path == "/robots.txt": return httpx.Response(200, text="User-agent: *\nDisallow: /careers\n")
        return httpx.Response(200, text="<html></html>")
    async def go():
        net = Net(cache_path=Path(tempfile.mkdtemp()) / "c.sqlite", transport=httpx.MockTransport(h))
        with pytest.raises(Blocked): await net.fetch("https://c.test/careers", check_robots=True, interval=0)
        await net.close()
    asyncio.run(go())
