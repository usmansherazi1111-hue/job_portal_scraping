"""Runs one search across the chosen sources concurrently and streams progress, then de-duplicates the results."""
from __future__ import annotations
import asyncio, re, time, uuid
from datetime import date, timedelta
from .model import Job
from .sources import SOURCES, Query, careers_page, detect
from .sources.ats import ATS
from .net import Blocked

ATS_IDS = [s.id for s in ATS]


def parse_targets(lines: list[str]) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Company inputs -> (known boards, careers-page URLs, bare names to auto-detect).
    Accepts 'greenhouse:stripe', any ATS URL, a careers URL/domain, or just a company name."""
    boards, pages, names = [], [], []
    for raw in lines:
        s = raw.strip()
        if not s: continue
        m = re.match(r"^(\w+)\s*:\s*([\w.-]+)$", s)
        if m and m.group(1).lower() in ATS_IDS:     # SmartRecruiters ids are case-sensitive ("Visa"); the rest are lower-case
            ats = m.group(1).lower()
            boards.append((ats, m.group(2) if ats == "smartrecruiters" else m.group(2).lower())); continue
        found = detect(s)
        if found: boards += [b for b in found if b not in boards]; continue
        if re.search(r"\.[a-z]{2,}(/|$)", s, re.I): pages.append(s); continue
        names.append(re.sub(r"[^\w-]", "", s.lower().replace(" ", "")))
    return boards, pages, names


class Run:
    def __init__(self, q: Query, source_ids: list[str], targets: list[str]):
        self.id = uuid.uuid4().hex[:10]
        self.q, self.source_ids, self.targets = q, source_ids, targets
        self.jobs: list[Job] = []
        self.status: dict[str, dict] = {}
        self.events: asyncio.Queue = asyncio.Queue()
        self.started = time.time(); self.finished = None

    def emit(self, kind: str, **data):
        self.events.put_nowait({"type": kind, **data})

    def _set(self, sid: str, **kw):
        st = self.status.setdefault(sid, {"id": sid, "name": SOURCES[sid].name if sid in SOURCES else sid})
        st.update(kw); self.emit("source", **st)


def _done(run: Run, key: str, jobs: list[Job], keep, ms=None, note: str = "") -> list[Job]:
    """found = what the source returned, matched = what passed the keyword/place/date filter, kept = matched rows after
    the per-source limit (what is shown and exported)."""
    matched = [j for j in jobs if keep(j)]
    shown = matched[: run.q.limit] if run.q.limit > 0 else matched
    if not jobs and not note: note = "the source answered but returned no jobs"
    elif jobs and not matched and not note: note = "no job matched the keywords / location / date filters"
    elif len(shown) < len(matched): note = note or f"limited to {len(shown)} (raise 'Max / source' to get all {len(matched)})"
    run._set(key, state="done", found=len(jobs), matched=len(matched), kept=len(shown), ms=ms, error=note)
    return shown


async def _guard(run: Run, key: str, coro, keep):
    t = time.monotonic()
    try:
        jobs = await coro
        return _done(run, key, jobs, keep, ms=int((time.monotonic() - t) * 1000))
    except Blocked as e:
        run._set(key, state="blocked", error=str(e), ms=int((time.monotonic() - t) * 1000))
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        if "404" in msg: msg = "not found (check the company name)"
        run._set(key, state="error", error=msg[:160], ms=int((time.monotonic() - t) * 1000))
    return []


async def execute(run: Run, net, cfg: dict):
    q = run.q
    since = (date.today() - timedelta(days=q.days)).isoformat() if q.days else ""

    def keep_fn(local: bool):
        """Every source is checked locally too: server-side search is often fuzzy (synonyms, tags, 'remote anywhere')."""
        def keep(j: Job) -> bool:
            if not j.title: return False
            if since and (j.updated or j.posted) and (j.updated or j.posted) < since: return False
            return q.matches(j) if local else True
        return keep

    tasks = []
    for sid in run.source_ids:
        s = SOURCES.get(sid)
        if not s or s.group != "search": continue
        missing = [k for k in s.needs if not cfg.get(k)]
        if missing:
            run._set(sid, state="skipped", error="needs a free key: " + ", ".join(missing)); continue
        run._set(sid, state="running")
        tasks.append(_guard(run, sid, s.run(net, q, cfg), keep_fn(True)))

    boards, pages, names = parse_targets(run.targets)
    board_filter = keep_fn(bool(q.words or q.location or q.country))   # company boards: narrow only when the user asked to

    async def board(ats, slug):
        key = f"{ats}:{slug}"; run._set(key, state="running", name=f"{SOURCES[ats].name} / {slug}")
        return await _guard(run, key, SOURCES[ats].run(net, q, cfg, slug), board_filter)

    async def probe(name):
        """Bare company name: try every ATS at once and keep the ones that answer."""
        key = f"detect:{name}"; run._set(key, state="running", name=f"Find boards for '{name}'")
        async def one(ats):
            try: return ats, await SOURCES[ats].run(net, q, cfg, name)
            except Exception: return ats, None
        hits = [(a, js) for a, js in await asyncio.gather(*(one(a) for a in ATS_IDS)) if js]
        if not hits:
            run._set(key, state="error", error="no public ATS board under this name; try the careers page URL"); return []
        out = []
        for a, js in hits:
            run.status.setdefault(f"{a}:{name}", {"id": f"{a}:{name}", "name": f"{SOURCES[a].name} / {name}"})
            out += _done(run, f"{a}:{name}", js, board_filter)
        run._set(key, state="done", found=sum(len(js) for _, js in hits), matched=len(out), kept=len(out),
                 error="found on " + ", ".join(a for a, _ in hits))
        return out

    async def page(url):
        key = f"page:{url}"; run._set(key, state="running", name=url)
        async def go():
            jobs, found = await careers_page(net, url)
            extra = await asyncio.gather(*(board(a, s) for a, s in found if (a, s) not in boards))
            return jobs + [j for js in extra for j in js]
        return await _guard(run, key, go(), board_filter)

    tasks += [board(a, s) for a, s in boards] + [probe(n) for n in names] + [page(u) for u in pages]

    for fut in asyncio.as_completed(tasks):
        jobs = await fut
        added = merge(run, jobs)
        if added: run.emit("jobs", rows=[brief(run, i) for i in added])
    run.finished = time.time()
    run.emit("done", total=len(run.jobs), seconds=round(run.finished - run.started, 1), stats=dict(net.stats))


def merge(run: Run, jobs: list[Job]) -> list[int]:
    """Add jobs, folding duplicates (same company + title + city) into the richer record; returns indexes of new rows."""
    index = getattr(run, "_index", None)
    if index is None: index = run._index = {}
    added = []
    for j in jobs:
        k = j.key
        if k in index:
            old = run.jobs[index[k]]
            srcs = old.extra.setdefault("also_on", [])
            if j.source != old.source and j.source not in srcs: srcs.append(j.source)
            for f in ("description", "department", "office", "salary", "location", "employment_type"):
                if len(getattr(j, f) or "") > len(getattr(old, f) or ""): setattr(old, f, getattr(j, f))
            continue
        index[k] = len(run.jobs); run.jobs.append(j); added.append(len(run.jobs) - 1)
    return added


def brief(run: Run, i: int) -> dict:
    j = run.jobs[i]
    return {"i": i, "partial": j.source == "rozee" and not j.extra.get("detailed"), "title": j.title, "company": j.company, "location": j.location, "department": j.department, "office": j.office,
            "type": j.employment_type, "remote": j.remote, "salary": j.salary, "posted": j.posted, "updated": j.updated,
            "source": j.source, "also": j.extra.get("also_on", []), "url": j.url, "snippet": j.description[:220]}
