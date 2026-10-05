"""Country and city lists for the search form. Read from countriesnow.space (free, no key) and cached for 30 days;
the built-in country list is used when it cannot be reached."""
from __future__ import annotations
from .sources.base import COUNTRY_NAMES, COUNTRY_WORDS

API = "https://countriesnow.space/api/v0.1/countries"
TTL = 30 * 86400
API_NAMES: dict[str, str] = {}      # iso2 -> the API's own country name (used to ask it for cities)
NOT_CITIES = {"united kingdom", "england", "scotland", "wales", "northern ireland", "great britain", "deutschland",
              "united states", "punjab", "sindh", "khyber", "u.s."}


async def countries(net) -> list[dict]:
    names = dict(COUNTRY_NAMES)
    try:
        d = await net.json(f"{API}/iso", interval=0.5, ttl=TTL, tries=2)
        for c in d.get("data") or []:
            code, name = (c.get("Iso2") or "").lower(), c.get("name") or ""
            if len(code) != 2 or not name: continue
            API_NAMES[code] = name
            names.setdefault(code, name)
    except Exception:
        pass
    for code, name in names.items(): COUNTRY_NAMES.setdefault(code, name)   # so searches know every country's name
    return sorted(({"code": k, "name": v} for k, v in names.items() if v), key=lambda c: c["name"])


async def cities(net, code: str) -> dict:
    """{'popular': the main cities (what job sites use most), 'cities': every city the API knows, A-Z}."""
    code = code.lower()
    if code not in API_NAMES: await countries(net)
    name = COUNTRY_NAMES.get(code, code.upper())
    found: list[str] = []
    try:
        d = await net.json(f"{API}/cities", method="POST", body={"country": API_NAMES.get(code, name)}, interval=0.5, ttl=TTL, tries=2)
        found = [] if d.get("error") else (d.get("data") or [])
    except Exception:
        pass
    seen, all_cities = set(), []
    for c in found:
        c = " ".join(str(c).split())
        if c and c.lower() not in seen and not c.lower().endswith((" district", " municipality")):
            seen.add(c.lower()); all_cities.append(c)
    by_lower = {c.lower(): c for c in all_cities}
    popular = []
    for w in COUNTRY_WORDS.get(code, []):
        if w in NOT_CITIES or w == name.lower() or len(w) < 4 or any(ch in w for ch in ",.") or "remote" in w: continue
        if all_cities and w not in by_lower: continue
        p = by_lower.get(w, w.title())
        if p not in popular: popular.append(p)
    return {"country": code, "name": name, "popular": popular, "cities": sorted(all_cities, key=str.lower)}
