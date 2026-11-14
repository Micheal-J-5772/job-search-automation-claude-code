---
name: getjobs
description: Run the daily job-search screening — harvest postings from the configured sources, screen them against the criteria, write matches to the Tracker tab and rejections (with reason + evidence) to the Rejected tab of Job-Search_Tracker.xlsx, then draft a cover letter and a reviewed, tailored CV per new Tracker row. Use when the user says "getjobs", "run the job search", "screen today's jobs", or similar.
---

# GetJobs

The project root (the folder containing this `.claude/`) is the "Job Search" folder.

1. Read `_claude/GetJobs-Prompt.md` in full. **It is the only authority** on what to screen,
   write and report. Follow it exactly.
2. Read `_claude/GetJobs-Runbook.md` — mechanics only.
3. For cover letters and CVs, follow `_claude/Cover-Letters-Prompt.md`, using
   `_claude/Cover-Letter_TEMPLATE.docx` as the shell, and review every CV with the
   `cyber-resume-reviewer` skill (runbook §6b).
4. Source material lives in `docs/`. Never state a claim that is not traceable to it.

**Refuse to run a screen while `_claude/GetJobs-Prompt.md` still contains `<ENTER` or `<ADD`
placeholders in sections A2 or C1–C9** — list which ones are unfilled and stop. Screening on
template examples would reject or keep jobs for someone else's criteria.

**Arguments:**
* A single posting URL → run the full pipeline on just that posting ("run it on one job first").
* "last N days" / "we missed N days" → widen every source's window to cover the gap (runbook §1).

**After the report**, wait for the user's borderline overrules (prompt A9) before applying.

Hard rules restated: never click Apply or Submit; never save the xlsx with a library that
rewrites the whole file; never solve a captcha; never claim anything `docs/` doesn't say.
