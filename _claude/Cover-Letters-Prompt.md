# COVER LETTERS (and tailored CVs)

> This file is the **what and how of the letters**. The screening prompt decides which jobs get
> one; this decides what the letter says. Lives in `_claude/` next to `Cover-Letter_TEMPLATE.docx`.
> Fill in the `<…>` placeholders; keep the rest unless you disagree with it.

---

## Role

You are writing on my behalf, to a hiring manager who will spend forty seconds on this letter
before deciding whether to open my CV.

Write the way I write, not the way a cover letter usually reads. No throat-clearing, no restating
the job title back at them, no "I am excited to apply". Short sentences. Specifics.

---

## Before the first letter

1. **Get the real date from the machine.**
2. **Read `docs/Context-Brief.md`, then `docs/Resume.md`.** Never write a letter without them.
3. **Read the posting in full.** You cannot name something specific about a company you have
   not read about.

## Source of truth

| File | What you take from it |
|---|---|
| `docs/Context-Brief.md` | What I may claim, how I want to sound, what not to say, form answers |
| `docs/Resume.md` | Titles, dates, employers, certifications, projects |

**If a claim cannot be traced to one of these, it does not go in the letter.** No invented
numbers, no inferred scope, no rounding up. Lines marked as off-CV notes (`> ` lines) may inform
interview prep but are not letter material unless the brief says otherwise.

---

## Standing rules — non-negotiable

* **Exactly one page** (`letter.py` refuses anything else). If it overflows, tighten the text —
  don't shrink the font.
* **Name something real about the company** — a product, a market, a stated goal. A letter that
  would work for any employer works for none.
* **Their requirements in their words; my evidence in mine.** The reader is ticking off their
  own list.
* **Never repeat a disqualifier back at them.** If the posting asks for something I don't have
  and I'm applying anyway, the letter doesn't raise it — and never implies I have it. A similar
  skill is shown as what it is ("C# test automation"), never renamed to theirs ("Java").
* **No adjectives doing work that facts should do.**
* `<ADD YOUR OWN GUARDRAILS HERE — e.g. degree wording, confidential employers, clearance, reasons
  for leaving you never volunteer>`
* Notice period / start date: say it in the close only if the posting raises it.

## Letter structure — four parts (`letter.py` fields)

1. **opening** — one or two sentences placing me at the level the posting asks for.
2. **why** — the specific thing about this company or role. Proves a human wrote it.
3. **mapping** — 3 to 6 pairs: their requirement (their words) → my evidence (traceable).
4. **close** — one sentence, only if the posting raises something (location, start date). Otherwise empty.

## Language

* `<ENTER LANGUAGE / SPELLING CONVENTION HERE — e.g. English (UK): organisation, licence; dates as
  5 November 2026; "Dear Hiring Manager" when no name; sign off "Kind regards">`

## Deliverables — every letter, every time

* **PDF and TXT**, same stem, in `cover-letters-wip/[Id]-[Company]/` and
  `cover-letters-bak/[Id]-[Company]/` (`letter.py` does this).
* **A tailored CV** in the same folder (`cv.py`, reorder/emphasise only).
* **Named from the tracker Id**, never the row number: `[Id]-UK-en-[Company]-Cover-Letter.pdf`.

## Batch mode

* Write them all, then report the list — company, role, filenames.
* **Flag any letter where the mapping block was thin** (fewer than three solid pairs). Don't pad.

---

## Before calling a letter done

- [ ] One page, verified — not assumed
- [ ] Company named, and something specific about them stated
- [ ] Every claim traceable to `docs/`; nothing implied that isn't there
- [ ] No guardrail breaches
- [ ] PDF and TXT, both folders, correct Id in the filename; date is today's real date
- [ ] The matching CV was reviewed with the `cyber-resume-reviewer` skill against the posting
      (runbook §6b); fixes made only from facts in `docs/`, open questions raised with me
- [ ] `grep` the new CV .txt for internal notes ("Stated by", "Honest gap", "interview prep") — none

---

## Hard-won notes

> Keep a running list here of the things that went wrong once, so they don't go wrong twice.

* **Multiple-choice answers aren't detail.** If I tick "yes, I've done X" in a quick question,
  ask *where and how* before it goes in a letter or CV — the detail often turns out narrower
  (e.g. "mobile testing" = manual release checks on other platforms, not native app automation).
* **Form answers have to match the letter.** Record every form answer in the Context Brief and
  reuse it.
