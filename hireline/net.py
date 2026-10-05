"""Polite, fast HTTP: one shared connection pool, a per-host pace, retries that honour Retry-After, a disk cache and
robots.txt checks for HTML pages. Nothing here hides who we are, rotates identities or solves CAPTCHAs: a source that
blocks us is reported as blocked, not worked around."""
from __future__ import annotations
import asyncio, json, os, random, sqlite3, time, hashlib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import httpx

UA = os.getenv("HIRELINE_UA", "Hireline/1.2 (job research tool; respects robots.txt and API terms)")
DATA = Path(os.getenv("HIRELINE_DATA", Path(__file__).resolve().parent.parent / "data"))


class Blocked(Exception):
    """The site said no (401/403, robots.txt, or rate limit that did not clear). Not retried with tricks."""


class Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS http (k TEXT PRIMARY KEY, t REAL, body BLOB)")

    def get(self, k: str, ttl: float):
        r = self.db.execute("SELECT t, body FROM http WHERE k=?", (k,)).fetchone()
        return r[1] if r and time.time() - r[0] < ttl else None

    def put(self, k: str, body: bytes):
        self.db.execute("INSERT OR REPLACE INTO http VALUES (?,?,?)", (k, time.time(), body)); self.db.commit()

    def clear(self):
        self.db.execute("DELETE FROM http"); self.db.commit()


class Net:
    def __init__(self, cache_path: Path | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.cache = Cache(cache_path or DATA / "cache.sqlite")
        self.transport = transport
        self.client: httpx.AsyncClient | None = None
        self.next_slot: dict[str, float] = {}
        self.gap: dict[str, float] = {}       # learned extra spacing for hosts that answered 429
        self.locks: dict[str, asyncio.Lock] = {}
        self.robots: dict[str, tuple[RobotFileParser, float]] = {}   # site -> (rules, expires)
        self.gate = asyncio.Semaphore(int(os.getenv("HIRELINE_CONCURRENCY", "12")))
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0}

    def _client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(25, connect=10), follow_redirects=True, transport=self.transport,
                headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
                limits=httpx.Limits(max_connections=40, max_keepalive_connections=20))
        return self.client

    async def close(self):
        if self.client: await self.client.aclose(); self.client = None

    async def _pace(self, host: str, interval: float):
        """At most one request per `interval` seconds to each host (or slower if the host told us to), in arrival order."""
        lock = self.locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self.next_slot.get(host, 0) - time.monotonic()
            if wait > 0: await asyncio.sleep(wait)
            self.next_slot[host] = time.monotonic() + max(interval, self.gap.get(host, 0))

    async def fetch(self, url: str, *, params: dict | None = None, headers: dict | None = None, method: str = "GET",
                    body: dict | None = None, auth=None, ttl: float = 1800, interval: float = 1.0, tries: int = 4,
                    check_robots: bool = False) -> bytes:
        req = self._client().build_request(method, url, params=params, headers=headers, json=body)
        key = hashlib.sha1(f"{method} {req.url} {json.dumps(body, sort_keys=True) if body else ''}".encode()).hexdigest()
        if ttl > 0:
            hit = self.cache.get(key, ttl)
            if hit is not None:
                self.stats["cache_hits"] += 1; return hit
        if check_robots and not await self.allowed(str(req.url)):
            raise Blocked("robots.txt disallows this page")
        host = urlsplit(str(req.url)).netloc
        delay = 1.0
        for attempt in range(tries):
            await self._pace(host, interval)
            try:
                async with self.gate:
                    self.stats["requests"] += 1
                    r = await self._client().send(self._client().build_request(method, url, params=params, headers=headers, json=body), auth=auth)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt == tries - 1: raise
                self._retry(host, e.__class__.__name__); await asyncio.sleep(delay + random.random()); delay *= 2; continue
            if r.status_code == 200:
                if self.gap.get(host, 0) > interval: self.gap[host] = max(interval, self.gap[host] * 0.97)   # ease back slowly
                if ttl > 0: self.cache.put(key, r.content)
                return r.content
            if r.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                ra = r.headers.get("Retry-After", "")
                wait = float(ra) if ra.replace(".", "", 1).isdigit() else delay + random.random()
                if wait > 60: raise Blocked(f"HTTP {r.status_code}: asked to wait {int(wait)} s")
                self._retry(host, str(r.status_code))
                if r.status_code == 429:   # the site says we are too fast: space every later request to it further apart
                    self.gap[host] = min(10.0, max(interval, self.gap.get(host, 0)) * 2)
                    wait = max(wait, self.gap[host])
                self.next_slot[host] = time.monotonic() + wait   # slow the whole host down, not just this call
                await asyncio.sleep(wait); delay *= 2; continue
            if r.status_code in (401, 403): raise Blocked(f"HTTP {r.status_code} (access refused)")
            if r.status_code == 429: raise Blocked("HTTP 429 (rate limit did not clear)")
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
        raise Blocked("gave up after retries")

    def _retry(self, host: str, why: str):
        self.stats["retries"] += 1
        k = f"{host} {why}"; by = self.stats.setdefault("retry_by", {}); by[k] = by.get(k, 0) + 1

    async def json(self, url: str, **kw):
        return json.loads(await self.fetch(url, **kw))

    async def allowed(self, url: str) -> bool:
        """robots.txt per RFC 9309: rules on 200; no rules on other 4xx; on 429/5xx/network errors the file is
        'unreachable', so we do not crawl and look again in 10 minutes instead of trusting a stale answer."""
        p = urlsplit(url); base = f"{p.scheme}://{p.netloc}"
        async with self.locks.setdefault("robots " + base, asyncio.Lock()):    # one fetch per site, not a burst
            hit = self.robots.get(base)
            if hit is None or time.monotonic() > hit[1]:
                rp, ttl = RobotFileParser(), 86400.0
                for attempt in range(2):
                    await self._pace(p.netloc, 2.0)
                    try:
                        r = await self._client().get(base + "/robots.txt", timeout=10)
                        code = r.status_code
                    except httpx.HTTPError:
                        code = 0
                    if code == 200: rp.parse(r.text.splitlines()); break
                    if 400 <= code < 500 and code != 429: rp.allow_all = True; break
                    if attempt == 0: await asyncio.sleep(2)
                else:
                    rp.disallow_all = True; ttl = 600
                    self.stats.setdefault("robots_unreachable", []).append(p.netloc)
                hit = self.robots[base] = (rp, time.monotonic() + ttl)
        if hit[0].disallow_all and hit[1] - time.monotonic() <= 600:
            raise Blocked("robots.txt could not be read right now (site busy); try again in a few minutes")
        return hit[0].can_fetch(UA, url)
