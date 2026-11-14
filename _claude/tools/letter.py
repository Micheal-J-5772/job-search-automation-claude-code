"""Build one cover letter (DOCX -> PDF via Word, plus TXT) from Cover-Letter_TEMPLATE.docx.

Usage (from the project root):
    python -I _claude/tools/letter.py letter.json

letter.json:
    {"id": "2", "company": "Acme", "date": "5 November 2026",
     "recipient": ["Hiring Manager", "Acme Ltd", "Bristol"],
     "salutation": "Dear Hiring Manager,",
     "opening": "...", "why": "...",
     "mapping": [["their requirement", "my evidence"], ...],   # 3-6 pairs
     "close": "... or empty"}

Writes [Id]-UK-en-[Company]-Cover-Letter.{pdf,txt} to cover-letters-wip/ and
cover-letters-bak/, and refuses to finish if the PDF is not exactly one page.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE = os.path.join(ROOT, "_claude", "Cover-Letter_TEMPLATE.docx")
WIP = os.path.join(ROOT, "cover-letters-wip")
BAK = os.path.join(ROOT, "cover-letters-bak")

RESUME = os.path.join(ROOT, "docs", "Resume.md")
SIGNOFF = "Kind regards,"
COUNTRY, LANG = "UK", "en"   # used in filenames: [Id]-UK-en-[Company]-Cover-Letter


def header():
    """Name, contact line and headline come from docs/Resume.md (the same fields cv.py uses)."""
    md = open(RESUME, encoding="utf-8").read()
    f = lambda k: (re.search(r"^\*\*%s:\*\*\s*(.+)$" % re.escape(k), md, re.M) or [None, ""])[1].strip()
    name = re.search(r"^# (.+?)(?: —|$)", md, re.M).group(1).strip()
    li = f("LinkedIn").replace("https://www.", "").replace("https://", "")
    return name, "  |  ".join(x for x in (f("Email"), li) if x), f("Title")


NAME, CONTACT, HEADLINE = header()


def esc(t):
    return html.escape(t.replace(" ", " "), quote=False)


def para(text, after, bold=False, size=None, style=None):
    ppr = ('<w:pStyle w:val="%s"/>' % style if style else "") + '<w:spacing w:after="%d"/>' % after
    rpr = ("<w:b/>" if bold else '<w:b w:val="0"/>') + ('<w:sz w:val="%d"/>' % size if size else "")
    return ('<w:p><w:pPr>%s</w:pPr><w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t>'
            '</w:r></w:p>' % (ppr, rpr, esc(text)))


def bullet(req, ev):
    return ('<w:p><w:pPr><w:pStyle w:val="ListBullet"/><w:spacing w:after="80"/></w:pPr>'
            '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
            '<w:r><w:t xml:space="preserve"> — %s</w:t></w:r></w:p>' % (esc(req), esc(ev)))


def body_xml(L):
    ps = [para(NAME, 40, bold=True, size=30), para(CONTACT, 40, size=18),
          para(HEADLINE, 240), para(L["date"], 280)]
    rec = L.get("recipient") or []
    for i, line in enumerate(rec):
        ps.append(para(line, 200 if i == len(rec) - 1 else 0))
    ps += [para(L["salutation"], 200), para(L["opening"], 160), para(L["why"], 160),
           para("Mapping directly to your requirements:", 120, bold=True)]
    ps += [bullet(r, e) for r, e in L["mapping"]]
    ps.append(para("", 0))
    if L.get("close"):
        ps.append(para(L["close"], 280))
    ps += [para(SIGNOFF, 40), para(NAME, 0)]
    return "".join(ps)


def build_docx(L, out):
    with zipfile.ZipFile(TEMPLATE) as z:
        entries = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in entries:
            if info.filename == "word/document.xml":
                s = data.decode("utf-8")
                start = s.index("<w:body>") + len("<w:body>")
                end = s.index("<w:sectPr")
                s = s[:start] + body_xml(L) + s[end:]
                s = s.replace('<w:pgSz w:w="12240" w:h="15840"/>', '<w:pgSz w:w="11906" w:h="16838"/>')
                data = s.encode("utf-8")
            z.writestr(info, data)


def to_pdf(docx, pdf):
    ps = (
        "$w = New-Object -ComObject Word.Application; $w.Visible = $false;"
        "try { $d = $w.Documents.Open('%s', $false, $true);"
        " $n = $d.ComputeStatistics(2); $d.SaveAs2('%s', 17); $d.Close($false); Write-Output $n }"
        " finally { $w.Quit() }" % (docx.replace("'", "''"), pdf.replace("'", "''")))
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        sys.exit("Word export failed: " + r.stderr)
    return int(r.stdout.strip().splitlines()[-1])


def plain_text(L):
    lines = [NAME, CONTACT, HEADLINE, "", L["date"], ""] + (L.get("recipient") or []) + [""]
    lines += [L["salutation"], "", L["opening"], "", L["why"], "",
              "Mapping directly to your requirements:"]
    lines += ["- %s — %s" % (r, e) for r, e in L["mapping"]]
    lines += [""] + ([L["close"], ""] if L.get("close") else []) + [SIGNOFF, NAME, ""]
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    L = json.load(open(sys.argv[1], encoding="utf-8"))
    if not 3 <= len(L["mapping"]) <= 6:
        sys.exit("mapping block needs 3-6 pairs, got %d" % len(L["mapping"]))
    company = re.sub(r"[^A-Za-z0-9]+", "-", L["company"]).strip("-")
    stem = "%s-%s-%s-%s-Cover-Letter" % (L["id"], COUNTRY, LANG, company)
    tmp = tempfile.mkdtemp()
    docx = os.path.join(tmp, stem + ".docx")
    pdf = os.path.join(tmp, stem + ".pdf")
    build_docx(L, docx)
    pages = to_pdf(docx, pdf)
    if pages != 1:
        sys.exit("%s is %d pages — must be exactly one. Nothing saved." % (stem, pages))
    txt = plain_text(L)
    job = "%s-%s" % (L["id"], company)          # one folder per job
    for d in (os.path.join(WIP, job), os.path.join(BAK, job)):
        os.makedirs(d, exist_ok=True)
        shutil.copy2(pdf, os.path.join(d, stem + ".pdf"))
        with open(os.path.join(d, stem + ".txt"), "w", encoding="utf-8") as f:
            f.write(txt)
    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"file": stem + ".pdf", "pages": pages}))


if __name__ == "__main__":
    main()
