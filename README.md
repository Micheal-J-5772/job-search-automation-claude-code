# Job Search Automation — Claude Code edition

A daily job-search pipeline you run inside **Claude Code**: one command (`/getjobs`) harvests
UK postings from LinkedIn, Reed, Indeed and CV-Library plus your target companies' career pages,
screens every one against criteria **you** write, logs matches to a tracker and every rejection
(with the rule and the quote that triggered it) to a second tab, then writes a one-page cover
letter and a tailored, reviewed CV for each match. You read, decide, and click Submit.

Built on the templates at [lagueux/job-search-automation](https://github.com/lagueux/job-search-automation)
("take it, change it, no attribution needed"), extended with working tools and lessons from
several weeks of real daily runs.

## What's in the box

| Path | What it is |
|---|---|
| `_claude/GetJobs-Prompt.md` | **The criteria and rules — start here.** Fill every `<ENTER …>` / `<ADD …>` |
| `_claude/GetJobs-Runbook.md` | The mechanics: commands, site quirks, spreadsheet safety, applying |
| `_claude/Cover-Letters-Prompt.md` | Letter rules + the CV review checklist |
| `_claude/Cover-Letter_TEMPLATE.docx` | Letter shell |
| `_claude/tools/harvest.py` | LinkedIn + Reed search, posting fetch, import of browser-harvested boards |
| `_claude/tools/board-harvest.js` | Indeed + CV-Library harvester, run inside a Chrome tab |
| `_claude/tools/tracker.py` | Safe xlsx writer: check / dump / write / set / outcomes-sync / outcome |
| `_claude/tools/cv.py` | Builds a 1–2 page CV PDF+TXT from `docs/Resume.md`, tailored per job (reorder only) |
| `_claude/tools/letter.py` | Builds a one-page letter PDF+TXT via Word |
| `.claude/skills/getjobs/SKILL.md` | The `/getjobs` command |
| `docs/Resume.md`, `docs/Context-Brief.md` | Templates for YOUR material (sample person "Alex Example") |
| `Job-Search_Tracker.xlsx` | Blank tracker: Tracker / Rejected / Data tabs (Outcomes is added automatically) |
| `cover-letters-wip/`, `cover-letters-bak/` | Your queue, and the never-edited archive |

## Requirements

* **Claude Code**, opened in this folder, with the **Claude in Chrome** extension (for Indeed,
  CV-Library and applying). Without Chrome it runs LinkedIn + Reed only.
* **Windows**, **Python 3.10+**, **Google Chrome or Edge** (CV PDFs), **Microsoft Word** (letter
  PDFs). The tools are UK-board specific; other countries need runbook/tool changes.
* Optional: the CV reviewer skill —
  `git clone https://github.com/mubix/cyber-resume-reviewer-skill` and copy its
  `cyber-resume-reviewer/` folder into `.claude/skills/` (read it before installing).

## Setup (an afternoon)

1. **Fill `docs/`.** Replace "Alex Example" in `docs/Resume.md` with your real record — keep the
   format exactly (cv.py parses it). Fill `docs/Context-Brief.md` yourself: what you may claim,
   what never to say, your form answers. **Every letter, CV and form answer is capped by these
   two files.**
2. **Fill `_claude/GetJobs-Prompt.md`.** Titles table, countries, target companies, and sections
   C1–C9. This is the step that matters: write each rule from a job you actually wasted an
   application on. `/getjobs` refuses to run while placeholders remain.
3. **Edit the title-word filter** (`TITLE_WORDS` in `harvest.py`, `TW` in `board-harvest.js`)
   to your field's words, and the Data tab of the tracker to your boards.
4. Fill the `<…>` guardrails in `_claude/Cover-Letters-Prompt.md`.
5. **Run it on one job first:** `/getjobs <one posting URL>`. Correct, re-run. Then go daily.

## Daily use

* `/getjobs` — the full run. Missed days? `/getjobs we missed 4 days` widens the window.
* Read the report: Tracker rows (with weak spots for interview prep) and a **numbered list of
  borderline rejects**. Reply "overrule 2, 5" — those get Tracker rows, letters and CVs, after
  Claude asks you about any requirement your docs don't cover.
* "Apply to 41, 43" — Claude opens and fills each form, asks you anything not on record, and
  hands over. **You click Submit**, then say "submitted" so it marks the tracker.

## What changed from the original templates

* Real tools instead of "ask your assistant to write it": harvesters, a tracker writer that never
  corrupts the workbook, CV and letter builders that refuse to overflow a page or invent a skill.
* **Catch-up runs** after missed days; Indeed rate-limit back-off; harvests survive a Cloudflare reload.
* **Cross-source dedupe** (agency name spellings, reused JDs) and a balanced funnel every run.
* **"Required platform/domain you don't have" counts as a hard requirement**, so you stop
  applying to jobs that need a system you've never used.
* **Borderline review and overrule** step, with grouped, numbered borderlines.
* **Every CV reviewed against the job** before it goes, fixing only from facts you've stated.
* **Ask, don't guess:** anything not in `docs/` becomes a question, and every answer is recorded
  so the next letter and form match. Multiple-choice "yes" answers get a follow-up for detail.
* An **Outcomes** tab tracks what's progressing and stops you re-applying to a rejection.

It sorts. You still decide, and you still read every posting before you apply.
