"""Hireline web server: a single page, a streaming search endpoint and exports."""
from __future__ import annotations
import asyncio, json, os
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from . import export, geo
from .engine import Run, execute
from .net import Net, DATA
from .sources import SOURCES, Query, country_code
from .sources.base import COUNTRY_NAMES
from .sources.regional import rozee_detail

VERSION = "1.2.0"
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
SETTINGS = DATA / "settings.json"
KEYS = ["REED_API_KEY", "USAJOBS_API_KEY", "USAJOBS_EMAIL", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY", "MUSE_API_KEY"]

app = FastAPI(title="Hireline", version=VERSION)
app.add_middleware(GZipMiddleware, minimum_size=800)
DEMO = os.getenv("HIRELINE_DEMO") == "1"   # offline sample data, for trying the UI without internet
if DEMO:
    from . import demo
    import tempfile
    NET = Net(cache_path=Path(tempfile.mkdtemp()) / "c.sqlite", transport=demo.transport())
else:
    NET = Net()
RUNS: "OrderedDict[str, Run]" = OrderedDict()


def settings() -> dict:
    cfg = {k: os.getenv(k, "") for k in KEYS}
    try: cfg.update({k: v for k, v in json.loads(SETTINGS.read_text()).items() if k in KEYS and v})
    except (OSError, ValueError): pass
    if DEMO:
        from .demo import DEMO_KEYS
        cfg.update(DEMO_KEYS)
    return cfg


@app.on_event("shutdown")
async def _close():
    await NET.close()


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/static/{name}")
async def static(name: str):
    p = (STATIC / name).resolve()
    if p.parent != STATIC or not p.exists(): raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/sources")
async def sources():
    cfg = settings()
    return {"version": VERSION, "sources": [
        {"id": s.id, "name": s.name, "group": s.group, "region": s.region, "needs": list(s.needs),
         "ready": all(cfg.get(k) for k in s.needs), "note": s.note, "home": s.home, "signup": s.signup,
         "default": s.default} for s in SOURCES.values()]}


@app.get("/api/countries")
async def list_countries():
    return {"countries": await geo.countries(NET)}


@app.get("/api/cities")
async def list_cities(country: str):
    code = country_code(country)
    if not code: raise HTTPException(400, "Unknown country")
    return await geo.cities(NET, code)


@app.get("/api/settings")
async def get_settings():
    return {k: bool(v) for k, v in settings().items()}


@app.post("/api/settings")
async def put_settings(body: dict):
    cur = {}
    try: cur = json.loads(SETTINGS.read_text())
    except (OSError, ValueError): pass
    for k, v in body.items():
        if k in KEYS: cur[k] = (v or "").strip()
    SETTINGS.parent.mkdir(parents=True, exist_ok=True); SETTINGS.write_text(json.dumps(cur, indent=1))
    return await get_settings()


class SearchIn(BaseModel):
    keywords: str = ""
    location: str = ""
    country: str = ""
    sources: list[str] = []
    companies: list[str] = []
    limit: int = 100
    days: int = 0
    remote: bool = False


@app.post("/api/search")
async def search(body: SearchIn):
    q = Query(keywords=body.keywords.strip(), location=body.location.strip(), country=country_code(body.country),
              limit=max(1, min(body.limit, 2000)), days=max(0, body.days), remote=body.remote)
    if body.country.strip() and not q.country: raise HTTPException(400, f"Unknown country '{body.country}'. Use a name or a 2-letter code.")
    if q.country and q.country not in COUNTRY_NAMES: await geo.countries(NET)   # learn the name of any country picked in the form
    targets = [c for c in body.companies if c.strip()][:200]
    if not body.sources and not targets: raise HTTPException(400, "Pick at least one source or enter a company.")
    run = Run(q, body.sources, targets)
    RUNS[run.id] = run
    while len(RUNS) > 20: RUNS.popitem(last=False)
    asyncio.create_task(execute(run, NET, settings()))
    return {"run": run.id}


@app.get("/api/runs/{rid}/events")
async def events(rid: str, request: Request):
    run = RUNS.get(rid) or _404()
    async def stream():
        while True:
            if await request.is_disconnected(): break
            try: ev = await asyncio.wait_for(run.events.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"; continue
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev["type"] == "done": break
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{rid}/jobs/{i}")
async def job(rid: str, i: int):
    run = RUNS.get(rid) or _404()
    if not 0 <= i < len(run.jobs): raise HTTPException(404)
    j = run.jobs[i]
    if j.source == "rozee" and not j.extra.get("detailed"): await rozee_detail(NET, j)   # full text on demand
    r = j.row(); r["also_on"] = j.extra.get("also_on", []); r["extra"] = {k: v for k, v in j.extra.items() if k != "also_on"}
    return r


@app.get("/api/runs/{rid}/export.{fmt}")
async def download(rid: str, fmt: str):
    run = RUNS.get(rid) or _404()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    base = "hireline-" + "-".join(x for x in (run.q.keywords.replace(" ", "_")[:30], run.q.country) if x) + f"-{stamp}"
    meta = {"tool": f"Hireline {VERSION}", "keywords": run.q.keywords, "location": run.q.location, "country": run.q.country,
            "companies": ", ".join(run.targets), "jobs": len(run.jobs), "exported": stamp,
            "note": "Follow each source's terms (Sources sheet). Data comes from official or public APIs, feeds and JSON-LD only."}
    if fmt == "csv": return Response(export.to_csv(run.jobs), media_type="text/csv", headers=_disp(base + ".csv"))
    if fmt == "json": return Response(export.to_json(run.jobs, meta), media_type="application/json", headers=_disp(base + ".json"))
    if fmt == "xlsx":
        data = await asyncio.to_thread(export.to_xlsx, run.jobs, list(run.status.values()), meta)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=_disp(base + ".xlsx"))
    raise HTTPException(400, "Use csv, xlsx or json")


@app.post("/api/cache/clear")
async def clear_cache():
    NET.cache.clear(); return {"ok": True}


@app.get("/api/status")
async def status():
    return {"version": VERSION, "runs": len(RUNS), "net": NET.stats}


def _disp(name):
    return {"Content-Disposition": f'attachment; filename="{name}"'}


def _404():
    raise HTTPException(404, "Run not found (the server may have restarted)")
