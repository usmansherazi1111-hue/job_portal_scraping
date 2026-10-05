# Hireline

Collects job postings from 24 free sources (official APIs, public feeds, job sites, company ATS boards and
JobPosting data on careers pages), filters them by keyword, country and city, and exports CSV, Excel and JSON.

## Run on Windows

1. Install Python 3.10 or newer from https://www.python.org/downloads/ (tick "Add python.exe to PATH").
2. Clone or download this repository.
3. Double-click **`setup.bat`** once. It creates a private environment in `.venv` and installs the packages.
4. Double-click **`run.bat`** whenever you want to use the app. It opens http://127.0.0.1:8100 in your browser.
   Keep its window open while you use the app; close it to stop.

`run.bat` also runs the setup by itself the first time, if you forget. To use another port: `set HIRELINE_PORT=8200` then `run.bat`.
Mac / Linux: `./run.sh`.

## Searching

* **Country, then City:** pick a country from the list; its cities load automatically (main cities first, type to filter).
  Results are strict: only jobs located in that city/country. Tick "Also include remote jobs" to add remote jobs open to it.
* **Portals:** 20 work with no key. Reed, USAJOBS, Adzuna and Jooble need a free key: click "add free key" next to them.
  Keys stay on your PC in `data/settings.json` (never uploaded).
* **Company boards:** type a company name (checked on Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Personio,
  Recruitee), `ats:slug` (e.g. `lever:palantir`), an ATS URL, or a careers page URL.
* Pakistan: Workable job search and Rozee.pk give city-level results; Jooble (free key) adds more.

## Being a good citizen

Per-site pacing, automatic slow-down when a site answers HTTP 429, retries that honour Retry-After, a local cache
(`data/cache.sqlite`), robots.txt checks for HTML pages and an honest User-Agent. No CAPTCHA solving, proxies, login use
or bot-detection evasion: a site that refuses is shown as "blocked". Follow each source's terms (see the Sources sheet in
the Excel export).

## Development

Tests (offline, mocked responses): `.venv\Scripts\python -m pytest -q`. `HIRELINE_DEMO=1` runs the app on sample data.
City lists come from countriesnow.space (free, cached 30 days).
