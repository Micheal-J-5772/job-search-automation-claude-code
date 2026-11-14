# GETJOBS — Runbook (the *how*)

> Mechanics only. `GetJobs-Prompt.md` is the *what* and wins on every rule. If this file and the
> prompt disagree, the prompt is right and this file is out of date — fix it.
>
> All commands run from the project root. Python scripts are always run with `-I`. Keep
> intermediate JSON in Claude's scratch directory — never in the project root.
> Built and tested on Windows 11, Python 3.12, Chrome, Microsoft Word (letters export via Word).

---

## 0. Preflight

| Step | How |
|---|---|
| Real date | `python -I -c "import datetime;print(datetime.date.today())"` |
| Workbook closed | `python -I _claude/tools/tracker.py check` → must print `closed`. If not, **stop and say so** |
| Browser | Claude in Chrome connected (`tabs_context_mcp` answers). If not, run LinkedIn + Reed only and say so |
| Source docs | Read `docs/Context-Brief.md` then `docs/Resume.md` in full |
| Placeholders | `grep -n "<ENTER\|<ADD" _claude/GetJobs-Prompt.md` — none may remain in A2 or C1–C9 |

---

## 1. Harvest LinkedIn + Reed (script)

```
python -I _claude/tools/harvest.py search > <scratch>/pool.json   (run in background; 10–40 min)
```

* Runs every title in the prompt's **Titles** table (parsed live — edit titles there, never here)
  against LinkedIn (guest API) and Reed. Progress is one line per query on stderr — `tail` it; if
  the last line is >5 min old the machine probably slept: kill and re-run.
* **Window:** default 24 h. **Catch-up after missed days:** `GETJOBS_DAYS=6` (LinkedIn takes any
  number of days; Reed switches to "last week"). Dedupe absorbs the overlap.
* `GETJOBS_LOCATION` sets the LinkedIn location (default `United Kingdom`).
* `title_match: false` jobs were never candidates (not logged). **Edit `TITLE_WORDS` in
  `harvest.py` (and `TW` in `board-harvest.js`) to your field's words before the first run.**
* `harvest.py search --only "<title>"` runs one title — for debugging or one-job tests.

## 1b. Harvest Indeed UK + CV-Library (Claude in Chrome)

Both sit behind Cloudflare: scripts get 403, but a real Chrome tab passes by itself (no captcha
to solve — if one appears, **stop and ask the user to tick it; never solve it**). Same-origin
`fetch()` from inside that tab reuses the clearance.

1. One new tab per board: `https://uk.indeed.com/jobs?q=Test&l=United+Kingdom` and
   `https://www.cv-library.co.uk/test-jobs`. Decline non-essential cookies.
   **Indeed must be signed in by the user** — signed-out visitors only get page 1.
2. Titles: `python -I _claude/tools/harvest.py titles`.
3. In each tab, `javascript_tool` with the full text of `_claude/tools/board-harvest.js`, then
   `BH.start([<titles>], <days>)` — days = 1 normally; 7 for a catch-up run (CV-Library accepts 1/3/7).
4. Poll `await new Promise(r=>setTimeout(r,35000)); BH.status()` (a call times out at 45 s).
   **Never navigate the harvesting tab** — a reload wipes `window.BH`. Collected jobs are also
   saved to `sessionStorage['bh_jobs_<site>']` after every query, so if Cloudflare forces a reload
   you can recover them; then re-inject and `BH.start()` only the titles that hadn't run.
5. Indeed 429s on long runs: the script waits 60 s and retries; Indeed is paced at 5 s.
6. Export title-matched rows. **`javascript_tool` truncates arrays at 100 items and strings at
   ~1,000 chars** — export in slices of 100 as arrays of short strings, and drop rows whose job id
   is already in the tracker *before* exporting. Values containing `?`, `=` or `&` may come back
   `[BLOCKED…]` — replace those characters first.
7. Save as `{"source","queries","errors","cols","rows"}` JSON (write it with the Write tool, not a
   heredoc — apostrophes in company names break heredocs), then
   `python -I _claude/tools/harvest.py import <scratch>/indeed.json <scratch>/cvl.json > <scratch>/pool_boards.json`.
8. Full postings: `await BH.details(["<id>", …])` (≤4 ids per call), or run a background loop in
   the tab that fills `window.DET` and poll it.
9. Close both tabs at the end.

## 1c. Target-company career pages

Prefer the public JSON boards: Greenhouse `boards-api.greenhouse.io/v1/boards/<co>/jobs`,
Lever `api.lever.co/v0/postings/<co>?mode=json`, Ashby `api.ashbyhq.com/posting-api/job-board/<co>`,
Workable `apply.workable.com/api/v1/widget/accounts/<co>`, BambooHR `<co>.bamboohr.com/careers/list`.
Report pages you couldn't read (403/404/JS-only) — never treat them as "no jobs".

---

## 2. Cheap screens (no page fetch), in this order

1. **Company** — excluded employers, excluded-industry companies by name, job boards shown as
   the employer (e.g. Jobgether, Haystack, eFinancialCareers, targetjobs, TipTopJob, Free-Work,
   AI-training "task" platforms).
2. **Title** — apprentice/intern/trainee/placement, Head of/Director/Manager, obvious excluded
   role types (field service, PAT/fixed-wire testing, production test, IT support…).
3. **Salary** — explicit card salary below the floor (annualise hourly/daily first).
4. **Location** — only when the card proves it. **A LinkedIn city is not proof** — fetch.

## 3. Full screen

```
python -I _claude/tools/harvest.py posting <url> > <scratch>/p_<id>.json
```

Returns `description`, `company`, `location`, `salary`, `criteria`, `chars`, `dead`. Apply
section C in order; first rule that fires wins. Useful automation: compute C1 density and
excluded-industry keyword counts for every posting, bucket by "remote stated / on-site stated /
in my area / unclear", then **read in full** every posting that could be kept.

* **Read the requirements block before keeping** — a named platform/domain that is *required*
  and not in `docs/` is `Credential` (see prompt C3).
* **Spot-check automatic rejects:** "Must be based in the UK" is not hybrid; heavy boilerplate can
  fail the density test on a real test role; benefits-list "remote working options" is not a remote role.
* **Salary often sits in the first line of the description** with the card empty — grep `£|GBP`.

## 4. Dedupe (both passes, every run)

```
python -I _claude/tools/tracker.py dump > <scratch>/tracker.json
```

1. Job id in the link — against both tabs. 2. Normalised Company + Role — against both tabs.
3. **Eyeball cross-source copies** under different company spellings (agency vs agency Ltd, agency
   vs client, identical JD text) — keep the higher-priority source, count the rest as duplicates.

## 5. Write both tabs in one pass — **once**

Build `<scratch>/rows.json`:

```json
{"Tracker":  [{"company":"…","date":"YYYY-MM-DD","origin":"linkedin.com","country":"UK",
               "url":"https://…","role":"full title","location":"Remote","comp":"£45,000"}],
 "Rejected": [{"company":"…","date":"…","origin":"reed.co.uk","country":"UK","url":"…",
               "role":"…","location":"","comp":"","reason":"Location — \"Leeds, on-site\""}]}
```

```
python -I _claude/tools/tracker.py write <scratch>/rows.json
```

* Refuses if the workbook is open; backs up to `.tracker-backups/` first; finds the next row by
  the last non-empty Company cell; patches the sheet XML only (dropdowns/tables survive);
  writes `Link` + a real hyperlink; prints the Ids written.
* **Not idempotent.** Run `write` exactly once, never chained with another `tracker.py` call in
  the same command (two writes in one second share a backup filename).
* `origin` should match the Data tab list (`linkedin.com`, `reed.co.uk`, `uk.indeed.com`,
  `cv-library.co.uk`, `company site`) — edit the Data tab to your boards.
* **Never open and save the workbook with openpyxl/pandas/Excel automation.**

### Verify
`tracker.py dump` → every intended row present with its `url`, on both tabs; **wait ~75 s
(background sleep), dump again**, compare. Only then report row numbers.

---

## 6. Cover letters and CVs

One per new `Tracker` row, after the rows are verified. Content rules: `Cover-Letters-Prompt.md`.

```
python -I _claude/tools/letter.py <scratch>/letter_<id>.json   # one page or it refuses
python -I _claude/tools/cv.py <scratch>/cv_<id>.json           # ≤2 pages or it refuses
```

* `letter.json`: `{"id","company","date","recipient":[…],"salutation","opening","why",
  "mapping":[[their requirement, my evidence], …3–6],"close"}`
* `cv.json`: `{"id","company","headline","summary","group_order","items_first","cert_first",
  "project_first","degree"}` — reorder/emphasise only; unknown skills/titles/numbers are errors.
* Both read name, contact line and headline from `docs/Resume.md`. Letters need Microsoft Word
  (COM export); CVs need Chrome or Edge.
* `cv.py` splits a skills line on commas — **don't put commas inside a skill's brackets**.

### 6b. Review every generated CV

Install once: `git clone https://github.com/mubix/cyber-resume-reviewer-skill` and copy its
`cyber-resume-reviewer/` folder into `.claude/skills/` (MIT, by Rob Fuller; read it first — its
scripts are local-only). Then for each new CV:

1. Save the posting text to `<scratch>/review/jd_<id>.txt` and run the stdlib-only helper:
   `python -I .claude/skills/cyber-resume-reviewer/scripts/analyze_resume_text.py --resume <CV .txt> --jd <scratch>/review/jd_<id>.txt`
   Its term list is IT/cyber-flavoured — a signal, never a reason to add a keyword.
2. Quick review against the JD (skill's quick-review template): up to five material findings.
3. Fix only through `docs/Resume.md` or the tailoring JSON. Anything needing a new fact → a
   question for the user, never a CV line. Record the answer in `docs/` with the date.
4. Re-run `cv.py`, confirm ≤2 pages and no leaked notes; report findings with the letter list.

---

## 7. Applying (the user applies; Claude prepares)

* "Open X" means open only; filling needs the user's go-ahead (a list of Ids = "apply to these").
* Read every field first (labels, required flags, options). Fill from `docs/Context-Brief.md` →
  Application-form answers. Anything not on record — salary, years of X, convictions, knockout
  yes/no questions — **ask** (one multiple-choice question each), then record the answer.
* Email/terms/consent gates, account creation, passwords and captchas are the user's.
* Re-read every value from the DOM after uploads (many forms re-render) and before handover.
* **The user clicks Submit.** Afterwards confirm the thank-you page, then
  `tracker.py set` column J = date, then `tracker.py outcomes-sync` (run on its own).
* Outcome news ("rejected", "interview"): `tracker.py outcome <updates.json>`.

### ATS traps
* **LinkedIn Easy Apply** pre-ticks screening answers from earlier applications and defaults to
  the last uploaded CV (which names another company) — check every radio; upload this job's CV.
  "Upload resume" creates its file input on click: patch `HTMLInputElement.prototype.click` to
  append the input to `document.body` instead of opening the picker, `find` it, `file_upload`,
  then restore `click`.
* **LinkedIn tags** (Hybrid/Contract/On-site) can contradict the posting — flag it.
* **Ashby / plain React forms:** set values with the native value setter + `input`/`change` events;
  radios by clicking their labels.
* **Lever:** "Current location" is an autocomplete a CV upload clears — type, click a suggestion.
* **Greenhouse:** react-select dropdowns (click → type → Enter); reCAPTCHA is the user's.
* **Harri / Attrax-style multi-page forms:** an email + consent gate first (user's), then personal
  details + CV, then a screening page with knockout selects.
* **Teamtailor-style:** consent checkboxes need a real click, not a scripted `.click()`.

---

## Traps found so far

* Windows console prints `£`/`—` as `�` unless stdout is UTF-8 — add
  `sys.stdout.reconfigure(encoding="utf-8")` to one-liners.
* LinkedIn's time filter is "posted *or reposted*" — dedupe catches the repeats.
* Recruiters show as the company on LinkedIn; CV-Library posters are mostly agencies.
* CV-Library returns HTTP 404 for an empty search (= 0 hits); matches any word and sorts by
  relevance, so the harvester stops paging once a full page has no title match.
* Indeed's fuzzy matching returns the same cards for related titles — overlap, not a block.
* Reed occasionally drops a chunked response — `get()` retries it.
* Don't POST board data from a Chrome tab to localhost — CSP blocks it. Export via return values.
* Cross-source duplicates under different employer spellings survive normalisation — eyeball them.
