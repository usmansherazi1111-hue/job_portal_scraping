"""Offline sample responses shaped like each source's real API (field names taken from the live endpoints/docs).
Used by the tests and by HIRELINE_DEMO=1, which runs the whole app with no internet."""
from __future__ import annotations
import json, re
from urllib.parse import parse_qs, urlsplit
import httpx

DESC = "<p>We are hiring a <b>{t}</b> to join our {d} team.</p><ul><li>Python, SQL</li><li>Own features end to end</li></ul><p>Benefits: hybrid work.</p>"


def J(obj, status=200):
    return httpx.Response(status, content=json.dumps(obj).encode(), headers={"content-type": "application/json"})


def greenhouse(slug):
    jobs = [{"id": 4000 + i, "title": t, "updated_at": "2026-10-0%dT10:00:00-04:00" % (i + 1), "first_published": "2026-09-2%dT09:00:00-04:00" % i,
             "location": {"name": loc}, "absolute_url": f"https://boards.greenhouse.io/{slug}/jobs/{4000 + i}",
             "content": DESC.format(t=t, d=dep).replace("<", "&lt;").replace(">", "&gt;"),
             "departments": [{"id": 1, "name": dep}], "offices": [{"id": 2, "name": off, "location": loc}]}
            for i, (t, loc, dep, off) in enumerate([("Senior Python Engineer", "London, United Kingdom", "Engineering", "London HQ"),
                                                    ("Account Executive", "Dubai, United Arab Emirates", "Sales", "Dubai"),
                                                    ("Data Analyst", "Karachi, Pakistan", "Data", "Karachi")])]
    return {"jobs": jobs, "meta": {"total": len(jobs)}}


def handler(request: httpx.Request) -> httpx.Response:
    u = urlsplit(str(request.url)); host, path = u.netloc, u.path; qs = {k: v[0] for k, v in parse_qs(u.query).items()}
    if path == "/robots.txt": return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    if host == "boards-api.greenhouse.io":
        m = re.match(r"/v1/boards/([\w-]+)(/jobs)?$", path)
        if not m or m.group(1) not in ("acme", "stripe"): return J({"status": 404, "error": "Job not found"}, 404)
        return J(greenhouse(m.group(1)) if m.group(2) else {"name": m.group(1).title() + " Inc", "content": ""})
    if host == "api.lever.co":
        if not path.endswith("/acme"): return J({"ok": False, "error": "Document not found"}, 404)
        return J([{"id": "a1b2", "text": "Backend Developer (Python)", "createdAt": 1790800000000, "updatedAt": 1791000000000,
                   "categories": {"team": "Platform", "department": "Engineering", "location": "Lahore, Pakistan", "commitment": "Full-time"},
                   "descriptionPlain": "Build our APIs.", "lists": [{"text": "Requirements", "content": "<li>3+ years Python</li>"}],
                   "additionalPlain": "Hybrid.", "hostedUrl": "https://jobs.lever.co/acme/a1b2", "workplaceType": "hybrid",
                   "salaryRange": {"min": 300000, "max": 450000, "currency": "PKR", "interval": "per-month-salary"}}])
    if host == "api.ashbyhq.com":
        if not path.endswith("/acme"): return J({"success": False}, 404)
        return J({"apiVersion": "1", "jobs": [{"id": "x9", "title": "Product Designer", "location": "Remote", "department": "Design", "team": "Growth",
                  "isRemote": True, "isListed": True, "employmentType": "FullTime", "publishedAt": "2026-10-02T12:00:00Z",
                  "descriptionPlain": "Design delightful flows.", "jobUrl": "https://jobs.ashbyhq.com/acme/x9",
                  "compensation": {"compensationTierSummary": "$110K - $140K"}}]})
    if host == "api.smartrecruiters.com":
        m = re.match(r"/v1/companies/([\w-]+)/postings(?:/(\w+))?$", path)
        if not m or m.group(1) != "acme": return J({"limit": 100, "offset": 0, "totalFound": 0, "content": []})
        if m.group(2): return J({"id": m.group(2), "postingUrl": f"https://jobs.smartrecruiters.com/acme/{m.group(2)}",
                                 "jobAd": {"sections": {"jobDescription": {"title": "Job Description", "text": "<p>Run our finance ops.</p>"},
                                                        "qualifications": {"title": "Qualifications", "text": "<p>ACCA</p>"}}}})
        return J({"limit": 100, "offset": 0, "totalFound": 1, "content": [{"id": "744000", "name": "Finance Manager", "releasedDate": "2026-09-30T08:00:00.000Z",
                  "company": {"identifier": "acme", "name": "Acme Group"}, "location": {"city": "Riyadh", "country": "sa", "remote": False},
                  "department": {"label": "Finance"}, "function": {"label": "Accounting"}, "typeOfEmployment": {"label": "Full-time"}}]})
    if host == "apply.workable.com":
        if not path.endswith("/acme"): return J({"error": "not found"}, 404)
        return J({"name": "Acme Workable", "description": "", "jobs": [{"title": "Customer Success Lead", "shortcode": "F4C0", "employment_type": "Full-time",
                  "telecommuting": False, "department": "Customer Success", "url": "https://apply.workable.com/j/F4C0", "published_on": "2026-09-28",
                  "created_at": "2026-09-28", "country": "United Arab Emirates", "city": "Dubai", "state": "", "function": "Support",
                  "locations": [{"country": "United Arab Emirates", "countryCode": "AE", "city": "Dubai"}], "description": "<p>Own key accounts.</p>"}]})
    if host.endswith(".jobs.personio.de"):
        if not host.startswith("acme."): return httpx.Response(404)
        x = ("<?xml version='1.0' encoding='UTF-8'?><workzag-jobs><position><id>123</id><subcompany>Acme GmbH</subcompany><office>Berlin</office>"
             "<department>Engineering</department><name>DevOps Engineer</name><jobDescriptions><jobDescription><name>Your tasks</name>"
             "<value><![CDATA[<p>Run Kubernetes.</p>]]></value></jobDescription></jobDescriptions><employmentType>permanent</employmentType>"
             "<schedule>full-time</schedule><createdAt>2026-09-29T10:00:00+00:00</createdAt></position></workzag-jobs>")
        return httpx.Response(200, content=x.encode(), headers={"content-type": "text/xml"})
    if host.endswith(".jobs.personio.com"): return httpx.Response(404)
    if host.endswith(".recruitee.com"):
        if not host.startswith("acme."): return J({"error": "not found"}, 404)
        return J({"offers": [{"id": 77, "title": "Sales Development Rep", "department": "Sales", "location": "Amsterdam, Netherlands", "city": "Amsterdam",
                  "country": "Netherlands", "published_at": "2026-09-25 10:00:00 UTC", "careers_url": "https://acme.recruitee.com/o/sdr",
                  "description": "<p>Book meetings.</p>", "requirements": "<p>English</p>", "employment_type_code": "fulltime", "remote": False}]})
    if host == "www.arbeitnow.com":
        return J({"data": [{"slug": "python-dev-berlin-1", "company_name": "Berlin Labs GmbH", "title": "Python Developer (m/w/d)", "description": "<p>Python and Django.</p>",
                  "remote": False, "url": "https://www.arbeitnow.com/jobs/companies/berlin-labs/python-dev-berlin-1", "tags": ["IT"], "job_types": ["Full Time"],
                  "location": "Berlin", "created_at": 1791212432}], "links": {"next": None}, "meta": {"current_page": 1}})
    if host == "www.themuse.com":
        return J({"page": int(qs.get("page", 0)), "page_count": 1, "results": [{"name": "Python Engineer", "contents": "<p>Python services.</p>", "id": 22176981,
                  "publication_date": "2026-09-28T19:02:11Z", "locations": [{"name": "London, United Kingdom"}], "categories": [{"name": "Software Engineering"}],
                  "levels": [{"name": "Senior Level", "short_name": "senior"}], "refs": {"landing_page": "https://www.themuse.com/jobs/x/python-engineer"},
                  "company": {"id": 1, "short_name": "celonis", "name": "Celonis"}}]})
    if host == "remoteok.com":
        return J([{"legal": "Link back to Remote OK"}, {"id": "1137461", "epoch": 1791058832, "date": "2026-10-03T20:20:32+00:00", "company": "Leverage Live Local",
                  "position": "Python Automation Engineer", "tags": ["python", "dev"], "description": "<p>Automate with Python.</p>", "location": "",
                  "salary_min": 90000, "salary_max": 120000, "url": "https://remoteOK.com/remote-jobs/1137461"}])
    if host == "remotive.com":
        return J({"job-count": 1, "jobs": [{"id": 2091132, "url": "https://remotive.com/remote-jobs/software-development/2091132", "title": "Senior Python Engineer",
                  "company_name": "Lemon.io", "category": "Software Development", "job_type": "full_time", "publication_date": "2026-09-30T13:15:26",
                  "candidate_required_location": "Europe, UK", "salary": "", "description": "<p>Python backends.</p>"}]})
    if host == "himalayas.app":
        return J({"jobs": [{"title": "Python Data Engineer", "companyName": "Aru Labs", "companySlug": "aru-labs", "employmentType": "Full Time",
                  "minSalary": 80000, "maxSalary": 100000, "currency": "USD", "salaryPeriod": "annual", "locationRestrictions": ["United Kingdom"],
                  "categories": ["Data-Engineer"], "parentCategories": ["Data"], "description": "<p>Pipelines in Python.</p>", "pubDate": 1791211755,
                  "applicationLink": "https://himalayas.app/companies/aru-labs/jobs/python-data-engineer", "guid": "https://himalayas.app/companies/aru-labs/jobs/python-data-engineer"}],
                  "totalCount": 1})
    if host == "jobicy.com":
        return J({"jobCount": 1, "jobs": [{"id": 154483, "url": "https://jobicy.com/jobs/154483-python", "jobTitle": "Senior Python Engineer", "companyName": "infisical",
                  "jobIndustry": ["Software Engineering"], "jobType": ["Full-Time"], "jobGeo": "UK, Europe", "jobLevel": "Senior",
                  "jobDescription": "<p>Python security.</p>", "pubDate": "2026-10-03T19:24:45+00:00"}]})
    if host == "weworkremotely.com":
        x = ("<rss><channel><item><title>Doist: Python Backend Engineer</title><region>Anywhere in the World</region><category>Back-End Programming</category>"
             "<type>Full-Time</type><description>&lt;p&gt;Python at Doist.&lt;/p&gt;</description><pubDate>Fri, 03 Oct 2026 10:00:00 +0000</pubDate>"
             "<guid>https://weworkremotely.com/remote-jobs/doist-python</guid><link>https://weworkremotely.com/remote-jobs/doist-python</link></item></channel></rss>")
        return httpx.Response(200, content=x.encode(), headers={"content-type": "application/rss+xml"})
    if host == "hn.algolia.com":
        if "search_by_date" in path: return J({"hits": [{"objectID": "45000000", "title": "Ask HN: Who is hiring? (October 2026)"}]})
        return J({"id": 45000000, "children": [{"id": 45000001, "created_at": "2026-10-01T15:00:00Z",
                  "text": "Acme Robotics | Senior Python Engineer | London, UK | ONSITE | Full-time | £90k<p>We build robots in Python."},
                  {"id": 45000002, "created_at": "2026-10-01T16:00:00Z", "text": "just a reply without pipes"}]})
    if host == "rest.arbeitsagentur.de":
        if request.headers.get("X-API-Key") != "jobboerse-jobsuche": return httpx.Response(403)
        if "/jobdetails/" in path: return J({"stellenangebotsTitel": "Python Entwickler (m/w/d)", "stellenangebotsBeschreibung": "Python, FastAPI und PostgreSQL."})
        return J({"ergebnisliste": [{"stellenangebotsTitel": "Python Entwickler (m/w/d)", "hauptberuf": "Softwareentwickler/in", "referenznummer": "10000-1234-S",
                  "stellenlokationen": [{"adresse": {"ort": "München", "region": "BAYERN", "land": "DEUTSCHLAND"}}], "firma": "Munich Soft GmbH",
                  "arbeitszeitVollzeit": True, "gehaltsspanneVon": 60000.0, "gehaltsspanneBis": 75000.0, "verguetungsangabe": "JAHRESGEHALT",
                  "datumErsteVeroeffentlichung": "2026-10-01", "aenderungsdatum": "2026-10-02T08:00:00.000"}], "maxErgebnisse": 1})
    if host == "jobs.workable.com":
        where = qs.get("location", "")
        rows = [("Senior Python Engineer", "Lahore", "Punjab", "Pakistan", "Devsinc"), ("Python Developer", "Karachi", "Sindh", "Pakistan", "Tkxel"),
                ("Python Data Engineer", "London", "England", "United Kingdom", "Lendable")]
        return J({"totalSize": 3, "jobs": [{"id": f"w{i}", "title": t, "department": "Engineering", "employmentType": "Full-time", "workplace": "on_site",
                  "description": f"<p>Python at {co}.</p>", "requirementsSection": "<ul><li>3 years Python</li></ul>", "benefitsSection": "",
                  "url": f"https://jobs.workable.com/view/w{i}", "locations": [f"{c}, {r}, {n}"], "location": {"city": c, "subregion": r, "countryName": n},
                  "created": "2026-09-30T07:03:02.000Z", "updated": "2026-10-01T07:03:02.000Z", "company": {"title": co}}
                  for i, (t, c, r, n, co) in enumerate(rows) if not where or c.lower() in where.lower() or n.lower() in where.lower()]})
    if host == "www.rozee.pk":
        if path.startswith("/job/jsearch/"):
            if "fpn" in qs: return httpx.Response(200, text="<html></html>")
            city = "Karachi" if "/fc/1184" in path else "Lahore"
            card = ('<div class="job border-bottom mb-3 "><div class="jcont"><div class="jhead"><div class="jobt pull-left"><h3 class="s-18" title="Python Developer">'
                    f'<a class="text-dark" href="//www.rozee.pk/python-developer-{city.lower()}-jobs-190{len(city)}?utm_source=x"><bdi>Python Developer</bdi></a></h3>'
                    '<div class="cname "><bdi class="pull-left"><a href="//www.rozee.pk/company/lahore-soft">Lahore Soft</a>, '
                    f'<a href="//www.rozee.pk/jobs-in-{city.lower()}">{city}</a>, <a href="//www.rozee.pk/">Pakistan</a></bdi></div></div></div>'
                    '<div class="jbody py-2"><bdi>Python and Django developer needed..</bdi></div><div class="jfooter"><span title="Posted On" data-toggle="tooltip">'
                    '<i class="calendar"></i>Oct 02, 2026 </span></div></div>')
            opts = '<select><option value="1184" >Karachi </option> <option value="1185" >Lahore </option></select>'
            return httpx.Response(200, text=f"<html>{opts}<div class=\"jlist\">{card}</div></html>")
        if "-jobs-" in path:
            ld = {"@context": "https://schema.org/", "@type": "JobPosting", "title": "Python Developer", "datePosted": "2026-10-02",
                  "description": "We need a Python developer with Django experience.", "employmentType": "FULL_TIME",
                  "hiringOrganization": {"@type": "Organization", "name": "Lahore Soft"}, "validThrough": "2026-11-01T00:00:00+05:00",
                  "jobLocation": {"@type": "Place", "address": {"addressLocality": "Lahore", "addressRegion": "Punjab", "addressCountry": {"name": "PK"}}}}
            return httpx.Response(200, text=f'<html><script type="application/ld+json">{json.dumps(ld)}</script><div>Job Details</div>'
                                             '<div><b>Functional Area:</b><span>Software &amp; Web Development</span></div>'
                                             '<div><b>Job Location:</b><span>Lahore</span></div></html>')
    if host == "www.reed.co.uk":
        return J({"results": [{"jobId": 55, "employerId": 9, "employerName": "Leeds Data Ltd", "jobTitle": "Python Developer", "locationName": "Leeds",
                  "minimumSalary": 45000, "maximumSalary": 55000, "currency": "GBP", "expirationDate": "15/11/2026", "date": "02/10/2026",
                  "jobDescription": "Python and AWS...", "jobUrl": "https://www.reed.co.uk/jobs/python-developer/55"}], "totalResults": 1})
    if host == "data.usajobs.gov":
        return J({"SearchResult": {"SearchResultItems": [{"MatchedObjectDescriptor": {"PositionID": "ABC-1", "PositionTitle": "IT Specialist (Python)",
                  "PositionURI": "https://www.usajobs.gov/job/1", "PositionLocationDisplay": "Washington, DC", "OrganizationName": "Census Bureau",
                  "DepartmentName": "Department of Commerce", "PositionSchedule": [{"Name": "Full-time"}],
                  "PositionRemuneration": [{"MinimumRange": "100000", "MaximumRange": "130000", "Description": "Per Year"}],
                  "PublicationStartDate": "2026-09-30", "ApplicationCloseDate": "2026-10-30", "UserArea": {"Details": {"JobSummary": "Python data work."}}}}]}})
    if host == "api.adzuna.com":
        return J({"results": [{"id": "129698749", "title": "Python Developer", "description": "Python, Django...", "created": "2026-10-01T18:07:39Z",
                  "redirect_url": "https://www.adzuna.co.uk/jobs/land/ad/129698749", "location": {"display_name": "Manchester"},
                  "company": {"display_name": "Corporate Project Solutions"}, "category": {"label": "IT Jobs"}, "contract_type": "permanent",
                  "salary_min": 50000, "salary_max": 55000}]})
    if host == "jooble.org":
        return J({"totalCount": 1, "jobs": [{"title": "Python Developer", "location": "Lahore", "snippet": "Python Django ...", "salary": "",
                  "source": "rozee.pk", "type": "Full-time", "link": "https://jooble.org/desc/1", "company": "Lahore Tech", "updated": "2026-10-01T00:00:00", "id": 1}]})
    if host == "open.canada.ca":
        if "package_show" in path:
            return J({"result": {"resources": [{"format": "CSV", "url": "https://open.canada.ca/data/x/download/job-bank-open-data-all-job-postings-en-sept2026.csv",
                                                "last_modified": "2026-10-02"}]}})
        csv = "Job Bank ID\tJob Title\tEmployer Business Name\tCity\tProvince/Territory\tFirst Posting Date\tSalary\n" \
              "4444\tPython Developer\tMaple Code Inc\tToronto\tON\t2026-09-15\t$45.00 hourly\n4445\tCook\tDiner\tOttawa\tON\t2026-09-16\t$17 hourly\n"
        return httpx.Response(200, content=csv.encode("utf-8"))
    if host in ("www.acme-example.com", "acme-example.com"):
        page = ('<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Office Manager",'
                '"datePosted":"2026-09-27","validThrough":"2026-11-01","employmentType":"FULL_TIME","hiringOrganization":{"@type":"Organization","name":"Acme Example"},'
                '"jobLocation":{"@type":"Place","address":{"addressLocality":"Lahore","addressCountry":"PK"}},"description":"<p>Keep the office running.</p>"}'
                '</script></head><body><a href="https://boards.greenhouse.io/acme">All jobs</a></body></html>')
        return httpx.Response(200, content=page.encode(), headers={"content-type": "text/html"})
    return httpx.Response(404)


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)


DEMO_KEYS = {"REED_API_KEY": "demo", "USAJOBS_API_KEY": "demo", "USAJOBS_EMAIL": "demo@example.com", "ADZUNA_APP_ID": "demo",
             "ADZUNA_APP_KEY": "demo", "JOOBLE_API_KEY": "demo"}
