"""Harvest job postings from LinkedIn (public guest API) and Reed, and fetch full postings.

Usage (from the project root):
    python -I _claude/tools/harvest.py search > pool.json      # all titles, past 24h
    python -I _claude/tools/harvest.py search --only "Embedded Test Engineer"
    python -I _claude/tools/harvest.py posting <url>            # full text + fields + liveness
    python -I _claude/tools/harvest.py import indeed.json cvl.json  # browser dumps → pool shape

Indeed and CV-Library are Cloudflare-blocked to scripts; they are harvested in a real Chrome
tab by board-harvest.js (Claude in Chrome) and brought in with `import`.

Titles are read from the **Titles** table in _claude/GetJobs-Prompt.md, so the prompt stays
the only place they are defined. Read-only: never applies, never logs in.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROMPT = os.path.join(ROOT, "_claude", "GetJobs-Prompt.md")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
# GETJOBS_DAYS=7 widens the window (LinkedIn f_TPR, Reed lastweek) for first runs of new titles.
DAYS = int(os.environ.get("GETJOBS_DAYS", "1"))
# Reed's "today" means since midnight, so a run just after midnight sees almost nothing
# (2 jobs on 2026-11-14 00:20). GETJOBS_REED=lastthreedays widens Reed alone; dedupe drops repeats.
REED_WINDOW = os.environ.get("GETJOBS_REED") or ("today" if DAYS <= 1 else "lastweek")
# GETJOBS_SOURCES=reed (or linkedin) runs one source only.
SOURCES = os.environ.get("GETJOBS_SOURCES", "linkedin,reed")
LOCATION = os.environ.get("GETJOBS_LOCATION", "United Kingdom")  # LinkedIn search location
DELAY = 1.5  # seconds between requests; LinkedIn's guest API returns 429 when hammered
# Cheap client-side title filter — the sites' own matching is fuzzy. A hit here is only a
# reason to open the posting (prompt A2); a miss means the job was never a candidate.
# EDIT ME: words that make a title worth opening, for YOUR field (keep board-harvest.js TW in step).
TITLE_WORDS = re.compile(
    r"\b(test|tester|testing|qa|quality assurance|sdet|automation|v&v|verification|validation|"
    r"field|deployment|integration|drone|uav|uas|rpas|flight|pilot)\b", re.I)
DEAD = re.compile(r"no longer (available|accepting)|position (has been )?filled|job (has )?closed|"
                  r"this job has expired|page not found|\b404\b", re.I)


def get(url, tries=4):
    for n in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-GB"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace"), r.geturl()
        except urllib.error.HTTPError as e:
            if e.code == 429 and n < tries - 1:
                time.sleep(10 * (n + 1))
                continue
            return e.code, e.read().decode("utf-8", "replace"), url
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                __import__("http.client").client.IncompleteRead) as e:  # Reed drops chunks mid-read
            if n == tries - 1:
                return 0, str(e), url
            time.sleep(3)
    return 0, "", url


def text(fragment):
    fragment = re.sub(r"<br\s*/?>|</p>|</li>", "\n", fragment)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def titles():
    s = open(PROMPT, encoding="utf-8").read()
    block = s[s.index("**Titles**"):s.index("Match comma and spelled-out")]
    out = []
    for line in block.splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        for cell in line.strip("|").split("|"):
            for t in cell.split(" / "):
                t = re.sub(r"\(.*?\)", "", t).strip()
                if t and t not in out:
                    out.append(t)
    return out


def linkedin_search(q):
    jobs, start = [], 0
    while start < 1000:
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
               + urllib.parse.urlencode({"keywords": q, "location": LOCATION,
                                         "f_TPR": "r%d" % (86400 * DAYS), "start": start}))
        status, body, _ = get(url)
        time.sleep(DELAY)
        cards = re.findall(r"<li>(.*?)</li>", body, re.S) if status == 200 else []
        if not cards:
            break
        for c in cards:
            m = re.search(r"jobs/view/[^\"?]*?-(\d+)[\"?]", c) or re.search(r"jobPosting:(\d+)", c)
            if not m:
                continue
            f = lambda cls: text((re.search(cls + r'[^>]*>(.*?)</(?:h3|h4|span|a)>', c, re.S)
                                  or [None, ""])[1])
            jobs.append({"source": "linkedin.com", "job_id": m.group(1),
                         "url": "https://www.linkedin.com/jobs/view/%s/" % m.group(1),
                         "role": f("base-search-card__title"),
                         "company": f("base-search-card__subtitle"),
                         "location": f("job-search-card__location"),
                         "salary": f("job-search-card__salary-info"),
                         "posted": (re.search(r'datetime="([^"]+)"', c) or [None, ""])[1]})
        start += len(cards)
        # The guest search matches ANY keyword and sorts by relevance ("Systems Test Engineer"
        # pages out to 500+ in 24 h). A full page with no title match = the noise tail; stop.
        if not any(TITLE_WORDS.search(j["role"]) for j in jobs[-len(cards):]):
            break
    return jobs


def next_data(body):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
    return json.loads(m.group(1)) if m else {}


REED_WORK = {"1": "On-site", "2": "Hybrid", "3": "Remote"}


def reed_salary(d):
    lo, hi = d.get("salaryFrom"), d.get("salaryTo")
    if not hi or str(hi) in ("0", "0.0", "None"):
        return ""
    unit = {"1": "/hour", "2": "/day", "3": "/week", "4": "/month", "5": "/year"}.get(
        str(d.get("salaryType")), "")
    return "£%s - £%s%s" % (lo, hi, unit)


def reed_search(q):
    jobs, page = [], 1
    slug = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")
    while page < 50:
        url = "https://www.reed.co.uk/jobs/%s-jobs?dateCreatedOffSet=%s&pageno=%d" % (slug, REED_WINDOW, page)
        status, body, _ = get(url)
        time.sleep(DELAY)
        sr = (next_data(body).get("props", {}).get("pageProps", {}).get("searchResults") or {})
        batch = sr.get("jobs") or []
        if status != 200 or not batch:
            break
        for j in batch:
            d = j["jobDetail"]
            jobs.append({"source": "reed.co.uk", "job_id": str(d["jobId"]),
                         "url": "https://www.reed.co.uk" + j["url"].split("?")[0],
                         "role": d.get("jobTitle", ""), "company": d.get("ouName", ""),
                         "location": d.get("displayLocationName", ""),
                         "work_mode": REED_WORK.get(str(d.get("workingOption")), ""),
                         "salary": reed_salary(d), "posted": d.get("dateCreated", ""),
                         "is_agency": str(d.get("ouType")) == "1"})
        if len(jobs) >= int(sr.get("count") or 0):
            break
        page += 1
    return jobs


def search(only=None):
    pool, seen, log = [], {}, []
    for q in ([only] if only else titles()):
        for name, fn in [x for x in (("linkedin.com", linkedin_search), ("reed.co.uk", reed_search))
                         if x[0].split(".")[0] in SOURCES]:
            hits = fn(q)
            log.append({"query": q, "source": name, "hits": len(hits)})
            # progress on stderr, so a stalled run is visible (`tail` the .err file)
            print("%s  %-14s %-40s %d" % (time.strftime("%H:%M:%S"), name, q, len(hits)),
                  file=sys.stderr, flush=True)
            for j in hits:
                key = (j["source"], j["job_id"])
                if key in seen:
                    seen[key]["queries"].append(q)
                    continue
                j["queries"] = [q]
                j["title_match"] = bool(TITLE_WORDS.search(j["role"]))
                seen[key] = j
                pool.append(j)
    return {"queries": log, "raw": sum(x["hits"] for x in log), "unique": len(pool),
            "title_matches": sum(j["title_match"] for j in pool), "jobs": pool}


def posting(url):
    status, body, final = get(url)
    out = {"url": url, "final_url": final, "http": status}
    if "linkedin.com" in url:
        jid = re.search(r"(\d{6,})", url).group(1)
        status, body, _ = get("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/" + jid)
        out["http"] = status
        desc = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", body, re.S)
        out["company"] = text((re.search(r"topcard__org-name-link[^>]*>(.*?)</a>", body, re.S)
                               or [None, ""])[1])
        out["location"] = text((re.search(r'topcard__flavor--bullet">(.*?)</span>', body, re.S)
                                or [None, ""])[1])
        out["salary"] = text((re.search(r'compensation__salary[^>]*>(.*?)</div>', body, re.S)
                              or [None, ""])[1])
        out["criteria"] = dict((text(a), text(b)) for a, b in re.findall(
            r'description__job-criteria-subheader">(.*?)</h3>\s*<span[^>]*>(.*?)</span>', body, re.S))
        out["closed"] = bool(re.search(r"No longer accepting applications", body))
        out["description"] = text(desc.group(1)) if desc else ""
    elif "reed.co.uk" in url:
        d = (next_data(body).get("props", {}).get("pageProps", {})
             .get("consolidatedJobDetails", {}).get("jobDetails") or {})
        out["company"] = (d.get("ouName") or d.get("employerName") or
                          (d.get("profile") or {}).get("name", "") if isinstance(d, dict) else "")
        out["fields"] = {k: v for k, v in d.items()
                         if k != "description" and not isinstance(v, (dict, list))}
        out["description"] = text(d.get("description", "")) if d else ""
        out["closed"] = not d
    else:
        out["description"] = text(re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S))
    out["dead"] = (out["http"] not in (200,) or out.get("closed", False) or not out["description"]
                   or bool(DEAD.search(out["description"][:600])))
    out["chars"] = len(out["description"])
    return out


def import_browser(paths):
    """Normalise BH.result() dumps (Indeed / CV-Library, from board-harvest.js) into the same
    pool shape `search` emits, so dedupe and screening treat every source alike."""
    log, pool = [], []
    for p in paths:
        data = json.load(open(p, encoding="utf-8"))
        if "rows" in data:  # BH.exportRows() shape: title-matched jobs as positional rows
            canon = {"uk.indeed.com": "https://uk.indeed.com/viewjob?jk=%s",
                     "cv-library.co.uk": "https://www.cv-library.co.uk/job/%s/"}[data["source"]]
            data["jobs"] = [dict(zip(data["cols"], r), source=data["source"],
                                 url=canon % r[0]) for r in data["rows"]]
            data["queries"] = [dict(q, source=data["source"]) for q in data.get("queries") or []]
        log += data.get("queries") or []
        for e in data.get("errors", []):
            log.append({"query": e.get("query"), "source": data.get("source"), "hits": 0,
                        "error": e.get("error")})
        for j in data.get("jobs", []):
            j["title_match"] = bool(TITLE_WORDS.search(j.get("role", "")))
            pool.append(j)
    return {"queries": log, "raw": sum(x.get("hits", 0) for x in log), "unique": len(pool),
            "title_matches": sum(j["title_match"] for j in pool), "jobs": pool}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "import":
        print(json.dumps(import_browser(sys.argv[2:]), ensure_ascii=False, indent=1))
    elif sys.argv[1] == "search":
        only = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--only" else None
        print(json.dumps(search(only), ensure_ascii=False, indent=1))
    elif sys.argv[1] == "posting":
        print(json.dumps(posting(sys.argv[2]), ensure_ascii=False, indent=1))
    elif sys.argv[1] == "titles":
        print("\n".join(titles()))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
