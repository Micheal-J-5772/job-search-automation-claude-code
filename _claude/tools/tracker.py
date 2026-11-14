"""Read and append rows to Job-Search_Tracker.xlsx by patching the sheet XML in place.

Never rewrites the workbook through a spreadsheet library: tables, data-validation dropdowns,
conditional formatting and add-in parts are carried through byte-for-byte.

Usage (run from the project root):
    python -I _claude/tools/tracker.py check            # is the workbook closed?
    python -I _claude/tools/tracker.py dump             # JSON of every filled row, both tabs
    python -I _claude/tools/tracker.py write rows.json  # append to Tracker + Rejected, one pass
    python -I _claude/tools/tracker.py set-data data.json  # replace the Data tab's lists
    python -I _claude/tools/tracker.py set edits.json   # overwrite text cells in existing rows
        edits.json: {"edits": [{"tab":"Tracker","row":2,"col":"I","value":"£99,500",
                                "expect_company":"Acme Ltd"}]}
    python -I _claude/tools/tracker.py outcomes-sync    # create/extend the Outcomes tab: one row
                                                        #   per APPLIED Tracker job (J = a date or
                                                        #   "Applied ...") not already on it
    python -I _claude/tools/tracker.py outcome updates.json   # change a job's status
        updates.json: {"updates": [{"id":"4","status":"Rejected","expect_company":"Cancer Research UK",
                                    "note":"Rejection email 14 Nov"}]}
        status must be one of STATUSES; "Updated" is set to today automatically.

rows.json:
    {"Tracker":  [{"company":..,"date":"2026-11-05","origin":..,"country":..,"url":..,
                   "role":..,"location":..,"comp":..}],
     "Rejected": [{... same keys ..., "reason":"Code — evidence"}]}
data.json:
    {"origins": [...], "countries": [...], "locations": [...]}
"""
import datetime
import html
import json
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOK = os.path.join(ROOT, "Job-Search_Tracker.xlsx")
BACKUPS = os.path.join(ROOT, ".tracker-backups")

SHEETS = {"Tracker": "xl/worksheets/sheet1.xml", "Rejected": "xl/worksheets/sheet2.xml"}
DATA_SHEET = "xl/worksheets/sheet4.xml"
COLS = "ABCDEFGHIJ"
# Column styles taken from the template's canonical row 2 — never from the cell being
# overwritten, since stray cells further down carry different styles.
COL_STYLE = {"A": "22", "B": "34", "C": "6", "D": "10", "E": "10", "F": "7",
             "G": "38", "H": "10", "I": "11", "J": "9"}
FIELDS = {"B": "company", "C": "date", "D": "origin", "E": "country", "G": "role",
          "H": "location", "I": "comp"}
HYPERLINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"

# Outcomes tab: one row per applied Tracker job (Id, Company, Role, Applied, Status, Updated, Notes),
# so you can see what's progressing and never re-apply to a role you were rejected from.
OUTCOMES = "Outcomes"
OUT_HEAD = ["Id", "Company", "Role", "Applied", "Status", "Updated", "Notes"]
OUT_WIDTH = [6, 28, 46, 12, 18, 12, 50]
STATUSES = ["Applied - waiting", "Progressing", "Interview", "Offer", "Rejected", "Withdrawn",
            "No reply"]
WORKSHEET_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def check_closed():
    lock = os.path.join(ROOT, "~$" + os.path.basename(BOOK))
    if os.path.exists(lock):
        return False, "Excel lock file present: " + lock
    lo_lock = os.path.join(ROOT, ".~lock." + os.path.basename(BOOK) + "#")
    if os.path.exists(lo_lock):
        return False, "LibreOffice lock file present (workbook open in LibreOffice): " + lo_lock
    try:
        with open(BOOK, "r+b"):
            pass
    except PermissionError:
        return False, "workbook is open in another program"
    return True, "closed"


def read_zip():
    with zipfile.ZipFile(BOOK) as z:
        return [(i, z.read(i.filename)) for i in z.infolist()]


def parts_dict(entries):
    return {i.filename: d for i, d in entries}


def shared_strings(parts):
    s = parts.get("xl/sharedStrings.xml", b"").decode("utf-8")
    out = []
    for si in re.findall(r"<si>(.*?)</si>", s, re.S):
        out.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
    return out


def cell_text(cell, sst):
    v = re.search(r"<v>(.*?)</v>", cell, re.S)
    if 't="s"' in cell and v:
        return sst[int(v.group(1))]
    if 't="inlineStr"' in cell:
        return html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", cell, re.S)))
    return html.unescape(v.group(1)) if v else ""


def rels_path(sheet):
    d, f = sheet.rsplit("/", 1)
    return d + "/_rels/" + f + ".rels"


def hyperlinks(parts, sheet):
    xml = parts[sheet].decode("utf-8")
    rels = parts.get(rels_path(sheet), b"").decode("utf-8")
    targets = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    targets.update({a: b for b, a in re.findall(r'Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
    return {ref: html.unescape(targets.get(rid, ""))
            for ref, rid in re.findall(r'<hyperlink ref="([A-Z]+\d+)"[^>]*r:id="([^"]+)"', xml)}


def serial_to_date(v):
    try:
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v)))).isoformat()
    except ValueError:
        return v


def dump(parts):
    sst = shared_strings(parts)
    result = {}
    for name, sheet in SHEETS.items():
        xml = parts[sheet].decode("utf-8")
        links = hyperlinks(parts, sheet)
        rows = []
        for rnum, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
            if rnum == "1":
                continue
            cells = {re.match(r'<c r="([A-Z]+)', c).group(1): c
                     for c in re.findall(r'<c r="[A-Z]+\d+".*?(?:/>|</c>)', body, re.S)}
            get = lambda col: cell_text(cells.get(col, ""), sst)
            if not get("B").strip():
                continue
            rows.append({"row": int(rnum), "id": get("A"), "company": get("B"),
                         "date": serial_to_date(get("C")), "origin": get("D"),
                         "country": get("E"), "url": links.get("F" + rnum, ""),
                         "role": get("G"), "location": get("H"), "comp": get("I"),
                         "last": get("J")})
        result[name] = rows
    return result


def esc(text):
    text = str(text).replace(" ", " ").replace(" ", " ")
    return html.escape(text, quote=False)


def str_cell(ref, style, text):
    return ('<c r="%s" s="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (ref, style, esc(text)))


def date_serial(iso):
    d = datetime.date.fromisoformat(iso)
    return (d - datetime.date(1899, 12, 30)).days


def build_row(rnum, existing_id, row, last_key):
    cells = []
    for col in COLS:
        ref = "%s%d" % (col, rnum)
        st = COL_STYLE[col]
        if col == "A":
            cells.append('<c r="%s" s="%s"><v>%s</v></c>' % (ref, st, existing_id or rnum))
        elif col == "C":
            cells.append('<c r="%s" s="%s"><v>%d</v></c>' % (ref, st, date_serial(row["date"])))
        elif col == "F":
            cells.append(str_cell(ref, st, "Link") if row.get("url") else '<c r="%s" s="%s"/>' % (ref, st))
        elif col == "J":
            v = row.get(last_key, "")
            cells.append(str_cell(ref, st, v) if v else '<c r="%s" s="%s"/>' % (ref, st))
        else:
            v = row.get(FIELDS[col], "")
            cells.append(str_cell(ref, st, v) if v else '<c r="%s" s="%s"/>' % (ref, st))
    return '<row r="%d" spans="1:10" x14ac:dyDescent="0.2">%s</row>' % (rnum, "".join(cells))


def append_rows(parts, name, rows, filled):
    sheet = SHEETS[name]
    xml = parts[sheet].decode("utf-8")
    rels_p = rels_path(sheet)
    rels = parts.get(rels_p, b"").decode("utf-8")
    last = max([r["row"] for r in filled] or [1])
    rel_ids = [int(x) for x in re.findall(r'Id="rId(\d+)"', rels)] or [0]
    next_rid = max(rel_ids) + 1
    new_links, new_rels, written = [], [], []
    for row in rows:
        last += 1
        m = re.search(r'<row r="%d"[^>]*>(.*?)</row>' % last, xml, re.S)
        existing_id = ""
        if m:
            a = re.search(r'<c r="A%d"[^>]*>(?:<v>(.*?)</v>)?' % last, m.group(1))
            existing_id = a.group(1) if a and a.group(1) else ""
        new = build_row(last, existing_id, row, "reason" if name == "Rejected" else "applied")
        if m:
            xml = xml[:m.start()] + new + xml[m.end():]
        else:
            die("%s row %d does not exist in the template — extend the table first" % (name, last))
        if row.get("url"):
            rid = "rId%d" % next_rid
            next_rid += 1
            new_links.append('<hyperlink ref="F%d" r:id="%s"/>' % (last, rid))
            new_rels.append('<Relationship Id="%s" Type="%s" Target="%s" TargetMode="External"/>'
                            % (rid, HYPERLINK_REL, html.escape(row["url"])))
        written.append({"row": last, "id": existing_id or str(last), "company": row.get("company"),
                        "role": row.get("role")})
    if new_links:
        if "<hyperlinks>" in xml:
            xml = xml.replace("</hyperlinks>", "".join(new_links) + "</hyperlinks>", 1)
        else:
            i = xml.index("<pageMargins")
            xml = xml[:i] + "<hyperlinks>" + "".join(new_links) + "</hyperlinks>" + xml[i:]
        if not rels:
            rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships '
                    'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
        rels = rels.replace("</Relationships>", "".join(new_rels) + "</Relationships>")
        parts[rels_p] = rels.encode("utf-8")
    parts[sheet] = xml.encode("utf-8")
    return written


def save(entries, parts):
    os.makedirs(BACKUPS, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(BOOK, os.path.join(BACKUPS, "Job-Search_Tracker.%s.xlsx" % stamp))
    tmp = BOOK + ".tmp"
    names = {i.filename for i, _ in entries}
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for info, _ in entries:
            z.writestr(info, parts[info.filename])
        for extra in sorted(set(parts) - names):
            z.writestr(extra, parts[extra])
    os.replace(tmp, BOOK)


def set_data(parts, data):
    lists = [data["origins"], data["countries"], data["locations"]]
    n = max(len(x) for x in lists)
    rows = []
    for i in range(n):
        r = i + 2
        cells = "".join(
            '<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (col, r, esc(lst[i]))
            for col, lst in zip("ABC", lists) if i < len(lst))
        rows.append('<row r="%d" spans="1:3">%s</row>' % (r, cells))
    xml = parts[DATA_SHEET].decode("utf-8")
    xml = re.sub(r"<sheetData>.*?</sheetData>", "<sheetData>" + "".join(rows) + "</sheetData>",
                 xml, flags=re.S)
    xml = re.sub(r'<dimension ref="[^"]*"/>', '<dimension ref="A2:C%d"/>' % (n + 1), xml)
    parts[DATA_SHEET] = xml.encode("utf-8")
    for sheet in SHEETS.values():
        s = parts[sheet].decode("utf-8")
        for col, lst in zip("ABC", lists):
            s = re.sub(r"Data!\$%s\$2:\$%s\$\d+" % (col, col),
                       "Data!$%s$2:$%s$%d" % (col, col, len(lst) + 1), s)
        parts[sheet] = s.encode("utf-8")


def set_cells(parts, edits):
    """Overwrite single text cells in rows that already exist. Each edit must name the
    company it expects in column B of that row, so a stale row number can't hit the wrong
    job. Only text columns; A (Id), C (date) and F (link) are never touched."""
    sst = shared_strings(parts)
    done = []
    for e in edits:
        tab, rnum, col, value = e["tab"], int(e["row"]), e["col"].upper(), e["value"]
        if col not in "BDEGHIJ" or len(col) != 1:
            die("column %s is not editable with set" % col)
        sheet = SHEETS[tab]
        xml = parts[sheet].decode("utf-8")
        m = re.search(r'<row r="%d"[^>]*>(.*?)</row>' % rnum, xml, re.S)
        if not m:
            die("%s row %d not found" % (tab, rnum))
        b = re.search(r'<c r="B%d".*?(?:/>|</c>)' % rnum, m.group(1), re.S)
        company = cell_text(b.group(0), sst) if b else ""
        if company != e["expect_company"]:
            die("%s row %d is %r, expected %r — nothing written" % (tab, rnum, company, e["expect_company"]))
        ref = "%s%d" % (col, rnum)
        new = str_cell(ref, COL_STYLE[col], value) if value else '<c r="%s" s="%s"/>' % (ref, COL_STYLE[col])
        body, n = re.subn(r'<c r="%s"(?:[^>]*/>|.*?</c>)' % ref, lambda _: new, m.group(1), count=1, flags=re.S)
        if not n:
            die("cell %s missing in %s" % (ref, tab))
        xml = xml[:m.start(1)] + body + xml[m.end(1):]
        parts[sheet] = xml.encode("utf-8")
        done.append({"tab": tab, "cell": ref, "company": company, "value": value})
    return done


def sheet_path(parts, name):
    """Worksheet part for a tab name, via workbook.xml + its rels (None if no such tab)."""
    w = parts["xl/workbook.xml"].decode("utf-8")
    m = re.search(r'<sheet name="%s"[^>]*r:id="([^"]+)"' % re.escape(name), w)
    if not m:
        return None
    rels = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    for rel in re.findall(r"<Relationship [^>]*/>", rels):
        if 'Id="%s"' % m.group(1) in rel:
            return "xl/" + re.search(r'Target="([^"]+)"', rel).group(1).lstrip("/").replace("xl/", "", 1)
    die("workbook rel %s for tab %s not found" % (m.group(1), name))


def applied(last):
    return bool(re.match(r"\d{4}-\d{2}-\d{2}$", last.strip())) or last.strip().lower().startswith("applied")


def out_row(rnum, r):
    cells = []
    for i, col in enumerate("ABCDEFG"):
        ref = "%s%d" % (col, rnum)
        v = r[i]
        if col == "A" and str(v).isdigit():
            cells.append('<c r="%s" s="15"><v>%s</v></c>' % (ref, v))
        elif v:
            cells.append(str_cell(ref, "15", v))
        else:
            cells.append('<c r="%s" s="15"/>' % ref)
    return '<row r="%d" spans="1:7">%s</row>' % (rnum, "".join(cells))


def read_outcomes(parts, path):
    sst = shared_strings(parts)
    xml = parts[path].decode("utf-8")
    rows = []
    for rnum, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml, re.S):
        if rnum == "1":
            continue
        cells = {re.match(r'<c r="([A-Z]+)', c).group(1): c
                 for c in re.findall(r'<c r="[A-Z]+\d+".*?(?:/>|</c>)', body, re.S)}
        vals = [cell_text(cells.get(c, ""), sst) for c in "ABCDEFG"]
        if vals[0].strip():
            rows.append({"row": int(rnum), **dict(zip([h.lower() for h in OUT_HEAD], vals))})
    return rows


def write_outcomes(parts, path, rows):
    """(Re)write the Outcomes sheet XML from a list of 7-value lists (header added here)."""
    n = len(rows) + 1
    head = "".join(str_cell("%s1" % c, "14", h) for c, h in zip("ABCDEFG", OUT_HEAD))
    data = '<row r="1" spans="1:7">%s</row>' % head + "".join(out_row(i + 2, r) for i, r in enumerate(rows))
    cols = "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w)
                   for i, w in enumerate(OUT_WIDTH))
    dv = ('<dataValidations count="1"><dataValidation type="list" allowBlank="1" showErrorMessage="1" '
          'sqref="E2:E1000"><formula1>"%s"</formula1></dataValidation></dataValidations>' % ",".join(STATUSES))
    parts[path] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<dimension ref="A1:G%d"/><sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="16"/><cols>%s</cols><sheetData>%s</sheetData>%s'
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        '</worksheet>' % (n, cols, data, dv)).encode("utf-8")


def add_sheet(parts, name, after):
    """Register a new worksheet part in workbook.xml, its rels, content types and app.xml."""
    existing = [int(x) for x in re.findall(r"xl/worksheets/sheet(\d+)\.xml$", "\n".join(parts), re.M)]
    path = "xl/worksheets/sheet%d.xml" % (max(existing) + 1)
    w = parts["xl/workbook.xml"].decode("utf-8")
    rels = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    rid = "rId%d" % (max(int(x) for x in re.findall(r'Id="rId(\d+)"', rels)) + 1)
    sid = max(int(x) for x in re.findall(r'<sheet [^>]*sheetId="(\d+)"', w)) + 1
    m = re.search(r'<sheet name="%s"[^>]*/>' % re.escape(after), w)
    w = w[:m.end()] + '<sheet name="%s" sheetId="%d" r:id="%s"/>' % (name, sid, rid) + w[m.end():]
    parts["xl/workbook.xml"] = w.encode("utf-8")
    rels = rels.replace("</Relationships>", '<Relationship Id="%s" Type="%s" Target="%s"/></Relationships>'
                        % (rid, WORKSHEET_REL, path[3:]))
    parts["xl/_rels/workbook.xml.rels"] = rels.encode("utf-8")
    ct = parts["[Content_Types].xml"].decode("utf-8")
    ct = ct.replace("</Types>", '<Override PartName="/%s" ContentType="%s"/></Types>' % (path, WORKSHEET_CT))
    parts["[Content_Types].xml"] = ct.encode("utf-8")
    app = parts.get("docProps/app.xml", b"").decode("utf-8")
    if "<TitlesOfParts>" in app:
        app = re.sub(r"(<vt:lpstr>Worksheets</vt:lpstr></vt:variant><vt:variant><vt:i4>)(\d+)",
                     lambda k: k.group(1) + str(int(k.group(2)) + 1), app)
        tp = re.search(r'<TitlesOfParts><vt:vector size="(\d+)"', app)
        app = app[:tp.start(1)] + str(int(tp.group(1)) + 1) + app[tp.end(1):]
        app = app.replace("<vt:lpstr>%s</vt:lpstr>" % after,
                          "<vt:lpstr>%s</vt:lpstr><vt:lpstr>%s</vt:lpstr>" % (after, name), 1)
        parts["docProps/app.xml"] = app.encode("utf-8")
    return path


def outcomes_sync(parts):
    today = datetime.date.today().isoformat()
    path = sheet_path(parts, OUTCOMES)
    have = []
    if path is None:
        path = add_sheet(parts, OUTCOMES, after="Rejected")
    else:
        have = [[o["id"], o["company"], o["role"], o["applied"], o["status"], o["updated"], o["notes"]]
                for o in read_outcomes(parts, path)]
    ids = {r[0] for r in have}
    added = []
    for t in dump(parts)["Tracker"]:
        if applied(t["last"]) and t["id"] not in ids:
            when = t["last"] if re.match(r"\d{4}-", t["last"]) else "not recorded"
            row = [t["id"], t["company"], t["role"], when, STATUSES[0], today, ""]
            have.append(row)
            added.append({"id": t["id"], "company": t["company"], "role": t["role"]})
    have.sort(key=lambda r: int(r[0]) if str(r[0]).isdigit() else 10 ** 9)
    write_outcomes(parts, path, have)
    return added


def outcome_update(parts, updates):
    today = datetime.date.today().isoformat()
    path = sheet_path(parts, OUTCOMES) or die("no Outcomes tab — run outcomes-sync first")
    rows = [[o["id"], o["company"], o["role"], o["applied"], o["status"], o["updated"], o["notes"]]
            for o in read_outcomes(parts, path)]
    done = []
    for u in updates:
        if u["status"] not in STATUSES:
            die("status %r not one of %s" % (u["status"], STATUSES))
        hit = [r for r in rows if r[0] == str(u["id"])]
        if not hit:
            die("Id %s is not on Outcomes (only applied jobs are) — nothing written" % u["id"])
        if hit[0][1] != u["expect_company"]:
            die("Outcomes Id %s is %r, expected %r — nothing written" % (u["id"], hit[0][1], u["expect_company"]))
        hit[0][4], hit[0][5] = u["status"], today
        if u.get("note") is not None:
            hit[0][6] = u["note"]
        done.append({"id": hit[0][0], "company": hit[0][1], "status": u["status"]})
    write_outcomes(parts, path, rows)
    return done


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        die(__doc__)
    cmd = sys.argv[1]
    ok, why = check_closed()
    if cmd == "check":
        print(why)
        sys.exit(0 if ok else 1)
    entries = read_zip()
    parts = parts_dict(entries)
    if cmd == "dump":
        d = dump(parts)
        op = sheet_path(parts, OUTCOMES)
        if op:
            d[OUTCOMES] = read_outcomes(parts, op)
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return
    if not ok:
        die(why)
    if cmd == "outcomes-sync":
        added = outcomes_sync(parts)
        save(entries, parts)
        print(json.dumps({"added": added}, ensure_ascii=False, indent=1))
        return
    payload = json.load(open(sys.argv[2], encoding="utf-8"))
    if cmd == "outcome":
        done = outcome_update(parts, payload["updates"])
        save(entries, parts)
        print(json.dumps(done, ensure_ascii=False, indent=1))
        return
    if cmd == "write":
        current = dump(parts)
        report = {}
        for name in SHEETS:
            if payload.get(name):
                report[name] = append_rows(parts, name, payload[name], current[name])
        save(entries, parts)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    elif cmd == "set":
        done = set_cells(parts, payload["edits"])
        save(entries, parts)
        print(json.dumps(done, ensure_ascii=False, indent=1))
    elif cmd == "set-data":
        set_data(parts, payload)
        save(entries, parts)
        print("Data tab updated")
    else:
        die("unknown command " + cmd)


if __name__ == "__main__":
    main()
