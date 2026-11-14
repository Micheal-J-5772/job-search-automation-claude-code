"""Build a CV PDF (+ TXT) straight from docs/Resume.md, optionally tailored to one job.

Usage (from the project root):
    python -I _claude/tools/cv.py                    # base CV  -> <Your-Name>-CV.pdf (root)
    python -I _claude/tools/cv.py tailor.json        # tailored -> [Id]-UK-en-[Company]-CV.pdf
                                                     #   in cover-letters-wip/ and -bak/
tailor.json (every key optional except id/company):
    {"id": "2", "company": "Acme Ltd",
     "headline": "Test Automation Engineer",             # must be a title held / on the resume
     "summary": "...",                                   # numbers must appear in Resume.md
     "sections": ["summary","experience","skills","projects","certifications","education"],
     "group_order": ["Software testing", ...],         # skill groups, by name
     "items_first": {"Languages & tools": ["Python", "SQL"]},
     "cert_first": ["ISTQB"], "project_first": ["Demo"],
     "degree": true}       # optional: if Resume.md has an "**Education (alternative wording):**"
                           # line, it replaces the first Education entry unless degree is true

Tailoring can only REORDER and EMPHASISE what Resume.md already says: an unknown skill,
group, certificate, project, headline or number is a hard error, and nothing listed in the
resume is ever dropped. Rendered with headless Chrome (real selectable text, single column,
ATS-friendly); refuses anything over 2 pages.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESUME = os.path.join(ROOT, "docs", "Resume.md")
WIP = os.path.join(ROOT, "cover-letters-wip")
BAK = os.path.join(ROOT, "cover-letters-bak")
FONTS = os.path.join(ROOT, "_claude", "fonts")   # optional Hanken/Schibsted Grotesk woff2; falls back to Segoe UI/Arial
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
MAX_PAGES = 2


def die(msg):
    sys.exit("ERROR: " + msg)


def section(md, name):
    m = re.search(r"^## %s\s*$(.*?)(?=^## |\Z)" % re.escape(name), md, re.M | re.S)
    if not m:
        die("Resume.md has no '## %s' section" % name)
    return m.group(1)


def bullets(block):
    """Top-level '- ' bullets, joining indented continuation lines."""
    out = []
    for line in block.splitlines():
        if line.startswith("- "):
            out.append(line[2:].strip())
        elif line.startswith("  ") and out and line.strip():
            out[-1] += " " + line.strip()
    # Resume.md carries internal notes for Claude: provenance tags ("(Stated by <you>, <date>.)")
    # and interview-prep-only bullets ("Honest gap ..."). Neither belongs on a CV sent to an
    # employer. Lines starting with "> " are never bullets, so use them for off-CV notes.
    out = [re.sub(r"\s*\((?:Stated|Confirmed) by [^)]*\)\.?", "", b).strip() for b in out]
    return [b for b in out if not re.match(r"(?i)honest gap|.*interview prep", b)]


def parse(md):
    def field(k):
        m = re.search(r"^\*\*%s:\*\*\s*(.+?)(?=^\*\*|\n\n)" % re.escape(k), md, re.M | re.S)
        if not m:
            die("Resume.md has no '**%s:**' line" % k)
        return m.group(1)
    opt = lambda k: field(k).strip() if re.search(r"^\*\*%s:\*\*" % re.escape(k), md, re.M) else ""
    cv = {"name": re.search(r"^# (.+?) —", md, re.M).group(1).strip(),
          "title": field("Title").strip(), "email": field("Email").strip(),
          "phone": field("Phone").strip(), "licence": opt("Driving licence"),
          "linkedin": opt("LinkedIn"),
          "summary": re.sub(r"\s+", " ", field("Summary")).strip()}
    cv["experience"] = []
    for head, body in re.findall(r"^### (.+?)$(.*?)(?=^### |\Z)", section(md, "Experience"), re.M | re.S):
        m = re.match(r"(.+?) — (.+?) \((.+?)\)(?: — (.+))?$", head.strip())
        cv["experience"].append({"title": m.group(1), "company": m.group(2), "dates": m.group(3),
                                 "domain": m.group(4) or "", "bullets": bullets(body)})
    cv["skills"] = []
    for b in bullets(section(md, "Skills")):
        g, items = re.match(r"\*\*(.+?):\*\*\s*(.+)", b).groups()
        sep = ";" if ";" in items else ","
        cv["skills"].append({"group": g, "items": [i.strip() for i in items.split(sep) if i.strip()]})
    cv["certifications"] = bullets(section(md, "Certifications"))
    cv["education"] = bullets(section(md, "Education"))
    cv["projects"] = bullets(section(md, "Projects & ventures"))
    return cv


def first(lst, prefixes, what):
    """Move items starting with any prefix to the front, in prefix order. Never drops."""
    head = []
    for p in prefixes:
        hit = [x for x in lst if re.sub(r"\*", "", x).startswith(p) and x not in head]
        if not hit:
            die("%s %r is not on the resume" % (what, p))
        head += hit
    return head + [x for x in lst if x not in head]


def tailor(cv, t, md):
    titles = {cv["title"]} | {e["title"] for e in cv["experience"]}
    if t.get("headline"):
        for part in t["headline"].split(" | "):
            if part not in titles:
                die("headline part %r is not a title on the resume (%s)" % (part, sorted(titles)))
        cv["title"] = t["headline"]
    if t.get("summary"):
        for num in re.findall(r"\d+\+?", t["summary"]):
            if num not in md:
                die("summary number %r does not appear in Resume.md" % num)
        cv["summary"] = t["summary"]
    groups = {s["group"]: s for s in cv["skills"]}
    for g in t.get("group_order", []):
        if g not in groups:
            die("skill group %r is not on the resume" % g)
    order = t.get("group_order", []) + [g for g in groups if g not in t.get("group_order", [])]
    cv["skills"] = [groups[g] for g in order]
    for g, items in t.get("items_first", {}).items():
        if g not in groups:
            die("skill group %r is not on the resume" % g)
        groups[g]["items"] = first(groups[g]["items"], items, "skill")
    if t.get("cert_first"):
        cv["certifications"] = first(cv["certifications"], t["cert_first"], "certification")
    if t.get("project_first"):
        cv["projects"] = first(cv["projects"], t["project_first"], "project")
    # Optional: one qualification, two honest wordings (e.g. a degree that was also an
    # apprenticeship). The alternative replaces the FIRST Education entry unless the job asks
    # for a degree ("degree": true in the tailoring file).
    alt = re.search(r"^\*\*Education \(alternative wording\):\*\*\s*(.+)$", md, re.M)
    if alt and not t.get("degree") and cv["education"]:
        cv["education"][0] = alt.group(1).strip()
    return cv


def cap(s):
    return s[:1].upper() + s[1:]


def md_inline(s):
    s = html.escape(s, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def render_html(cv, sections):
    font = lambda f: "file:///" + os.path.join(FONTS, f).replace("\\", "/").replace(" ", "%20")
    li = cv["linkedin"].replace("https://www.", "")
    parts = []
    for s in sections:
        if s == "summary":
            parts.append('<section><h2>Profile</h2><p class="summary">%s</p></section>' % md_inline(cv["summary"]))
        elif s == "experience":
            roles = "".join(
                '<div class="role"><div class="rh"><span class="rt">%s</span> <span class="rc">%s</span>'
                '%s<span class="rd">%s</span></div><ul>%s</ul></div>'
                % (md_inline(e["title"]), md_inline(e["company"]),
                   '<span class="dom">(%s)</span>' % md_inline(e["domain"]) if e["domain"] else "",
                   md_inline(e["dates"].replace("–", " – ")),
                   "".join("<li>%s</li>" % md_inline(b) for b in e["bullets"]))
                for e in cv["experience"])
            parts.append("<section><h2>Experience</h2>%s</section>" % roles)
        elif s == "skills":
            rows = "".join('<tr><th>%s</th><td>%s</td></tr>' % (md_inline(g["group"]), md_inline(cap(", ".join(g["items"]))))
                           for g in cv["skills"])
            parts.append('<section><h2>Skills</h2><table class="skills">%s</table></section>' % rows)
        else:
            key, label = {"projects": ("projects", "Projects &amp; ventures"),
                          "certifications": ("certifications", "Certifications"),
                          "education": ("education", "Education")}[s]
            parts.append("<section><h2>%s</h2><ul%s>%s</ul></section>"
                         % (label, ' class="cols"' if key == "certifications" else "", "".join("<li>%s</li>" % md_inline(x) for x in cv[key])))
    return """<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><title>%(name)s — CV</title><style>
@font-face{font-family:Hanken;src:url('%(h4)s');font-weight:400}
@font-face{font-family:Hanken;src:url('%(h5)s');font-weight:500}
@font-face{font-family:Schibsted;src:url('%(s5)s');font-weight:500}
@font-face{font-family:Schibsted;src:url('%(s6)s');font-weight:600}
@page{size:A4;margin:9mm 14mm}
*{box-sizing:border-box}
body{margin:0;font:400 9.2pt/1.33 Hanken,'Segoe UI',Arial,sans-serif;color:#171a19}
header{border-bottom:1.5pt solid #8f5c0d;padding-bottom:5pt;margin-bottom:4pt}
h1{font:600 21pt/1.1 Schibsted,'Segoe UI',Arial,sans-serif;margin:0}
.headline{font:500 11pt Schibsted,'Segoe UI',Arial,sans-serif;color:#8f5c0d;margin-top:2pt}
.contact{margin-top:4pt;font-weight:500;color:#3d4442}
h2{font:500 11pt Schibsted,'Segoe UI',Arial,sans-serif;margin:7pt 0 3pt;color:#171a19;
   border-bottom:.5pt solid #c9cec9;padding-bottom:2pt}
section{break-inside:auto}
p{margin:0}
ul{margin:2pt 0 0;padding-left:13pt}
li{margin:.5pt 0}
.role{margin-bottom:4.5pt;break-inside:avoid}
.rh{display:flex;align-items:baseline;gap:5pt}
.rt{font-weight:500}
.rc{color:#3d4442}
.rd{margin-left:auto;font-weight:500;font-variant-numeric:tabular-nums;color:#3d4442;white-space:nowrap}
.dom{font-size:8.6pt;color:#5a625f}
table.skills{border-collapse:collapse;width:100%%}
.skills th{font-weight:500;text-align:left;vertical-align:top;white-space:nowrap;padding:1pt 10pt 1pt 0;width:1%%}
.skills td{padding:1pt 0}
strong{font-weight:500}
ul.cols{columns:2;column-gap:14pt}
ul.cols li{break-inside:avoid}
</style></head><body>
<header><h1>%(name)s</h1><div class="headline">%(title)s</div>
<div class="contact">%(contact)s</div></header>
%(body)s
</body></html>""" % {"name": html.escape(cv["name"]), "title": html.escape(cv["title"]),
                     "email": html.escape(cv["email"]), "li": html.escape(li),
                     "phone": html.escape(cv["phone"]), "licence": html.escape(cv["licence"]), "body": "".join(parts),
                     "contact": " &nbsp;|&nbsp; ".join(html.escape(x) for x in contact_bits(cv, li)),
                     "h4": font("hanken-grotesk-latin-400-normal.woff2"),
                     "h5": font("hanken-grotesk-latin-500-normal.woff2"),
                     "s5": font("schibsted-grotesk-latin-500-normal.woff2"),
                     "s6": font("schibsted-grotesk-latin-600-normal.woff2")}


def contact_bits(cv, li):
    bits = [cv["phone"], cv["email"]] + ([li] if li else [])
    return bits + (["%s driving licence" % cv["licence"]] if cv["licence"] else [])


def plain_text(cv, sections):
    L = [cv["name"], cv["title"], " | ".join(contact_bits(cv, cv["linkedin"])), ""]
    strip = lambda s: s.replace("**", "")
    for s in sections:
        if s == "summary":
            L += ["PROFILE", cv["summary"], ""]
        elif s == "experience":
            L.append("EXPERIENCE")
            for e in cv["experience"]:
                L.append("%s — %s (%s)" % (e["title"], e["company"], e["dates"]))
                L += ["- " + b for b in e["bullets"]] + [""]
        elif s == "skills":
            L += ["SKILLS"] + ["%s: %s" % (g["group"], ", ".join(g["items"])) for g in cv["skills"]] + [""]
        else:
            L += [s.upper()] + ["- " + strip(x) for x in cv[s]] + [""]
    return "\n".join(L)


def to_pdf(html_text, pdf):
    exe = next((c for c in CHROME if os.path.exists(c)), None)
    if not exe:
        die("no Chrome/Edge found for PDF rendering")
    tmp = tempfile.mkdtemp(prefix="cv-")
    try:
        src = os.path.join(tmp, "cv.html")
        open(src, "w", encoding="utf-8").write(html_text)
        out = os.path.join(tmp, "cv.pdf")
        # Separate profile dir so the person's own running Chrome is never touched.
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--user-data-dir=" + os.path.join(tmp, "profile"),
                        "--print-to-pdf=" + out, "file:///" + src.replace("\\", "/")],
                       capture_output=True, timeout=120)
        if not os.path.exists(out):
            die("Chrome did not produce a PDF")
        data = open(out, "rb").read()
        pages = len(re.findall(rb"/Type\s*/Page(?![s\w])", data))
        shutil.copyfile(out, pdf)
        return pages
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    md = open(RESUME, encoding="utf-8").read()
    cv = parse(md)
    t = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 else {}
    cv = tailor(cv, t, md)
    sections = t.get("sections") or ["summary", "experience", "skills", "projects", "certifications", "education"]
    if sorted(sections) != sorted(["summary", "experience", "skills", "projects", "certifications", "education"]):
        die("sections must list all six sections exactly once (reorder only)")
    html_text = render_html(cv, sections)
    if t:
        co = re.sub(r"[^A-Za-z0-9]+", "-", t["company"]).strip("-")
        stem = "%s-UK-en-%s-CV" % (t["id"], co)
        job = "%s-%s" % (t["id"], co)            # one folder per job
        dirs = [os.path.join(WIP, job), os.path.join(BAK, job)]
    else:
        stem, dirs = re.sub(r"[^A-Za-z0-9]+", "-", cv["name"]).strip("-") + "-CV", [ROOT]
    tmp_pdf = os.path.join(tempfile.gettempdir(), stem + ".pdf")
    pages = to_pdf(html_text, tmp_pdf)
    if not 1 <= pages <= MAX_PAGES:
        die("%s rendered at %d pages — must be 1–%d. Nothing saved." % (stem, pages, MAX_PAGES))
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(tmp_pdf, os.path.join(d, stem + ".pdf"))
        open(os.path.join(d, stem + ".txt"), "w", encoding="utf-8").write(plain_text(cv, sections))
    os.remove(tmp_pdf)
    print(json.dumps({"file": stem + ".pdf", "pages": pages, "dirs": [os.path.relpath(d, ROOT) for d in dirs]}))


if __name__ == "__main__":
    main()
