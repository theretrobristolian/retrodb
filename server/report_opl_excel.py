#!/usr/bin/env python3
"""Create a filterable, formatted OPL proposal workbook; CSV remains the rename input."""
import csv
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

HEADERS = (
    "Current relative path", "Current filename", "Disc ID", "GameDB title",
    "Proposed filename", "Proposed relative path", "Display preview with RA",
    "Title truncated", "Status", "Notes", "Duplicate recommendation",
    "SHA256", "Disc inspection",
)
WIDTHS = (64, 43, 17, 44, 43, 64, 38, 17, 17, 75, 65, 65, 65)

def cell_ref(col):
    value = ""
    while col:
        col, rem = divmod(col - 1, 26)
        value = chr(65 + rem) + value
    return value

def sheet_xml(rows):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
           '<cols>']
    for idx, width in enumerate(WIDTHS, 1):
        out.append(f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>')
    out.append('</cols><sheetData>')
    for number, row in enumerate(rows, 1):
        out.append(f'<row r="{number}">')
        for idx, value in enumerate(row, 1):
            style = 1 if number == 1 else (2 if number % 2 == 0 else 0)
            if number > 1 and idx == 9:
                style = {"PROPOSED": 3, "UNCHANGED": 4, "REVIEW": 5,
                         "COLLISION": 6}.get(value, style)
            if number > 1 and idx == 8 and value == "YES":
                style = 5
            text = escape(str(value or ""))
            out.append(f'<c r="{cell_ref(idx)}{number}" s="{style}" t="inlineStr"><is><t>{text}</t></is></c>')
        out.append('</row>')
    out.append('</sheetData>')
    out.append(f'<autoFilter ref="A1:M{len(rows)}"/>')
    out.append('</worksheet>')
    return "".join(out)

def main(input_csv, output_xlsx):
    with open(input_csv, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(HEADERS).issubset(reader.fieldnames):
            raise ValueError("Invalid OPL rename proposal CSV")
        records = list(reader)
    # The workbook is a review copy; it never changes the CSV driving the rename.
    rows = [HEADERS] + [tuple(record.get(field, "") for field in HEADERS)
                        for record in records]
    output_xlsx = Path(output_xlsx)
    output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_xlsx, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="OPL Rename Proposals" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr("xl/styles.xml", '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/></font><font><b/><color rgb="FFFFFFFF"/></font></fonts><fills count="7"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'+''.join('<fill><patternFill patternType="solid"><fgColor rgb="%s"/></patternFill></fill>' % value for value in ("FF17365D","FFF1F5F9","FFDDF4E4","FFE5EBF2","FFFFE5CC"))+'</fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="7">'+''.join('<xf numFmtId="0" fontId="%d" fillId="%d" borderId="0" xfId="0"/>' % (1 if i == 1 else 0, {0:0,1:2,2:3,3:4,4:5,5:6,6:6}[i]) for i in range(7))+'</cellXfs></styleSheet>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml(rows))
    counts = Counter(record.get("Status", "") for record in records)
    print(f"[OK] OPL Excel workbook: {output_xlsx}")
    print(f"[INFO] {len(records)} titles | " + ", ".join(f"{name}: {counts[name]}" for name in ("PROPOSED", "UNCHANGED", "REVIEW", "COLLISION")))
    print("[SAFE] Review-only workbook; renaming continues to use the original CSV.")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: report_opl_excel.py input.csv output.xlsx")
    main(sys.argv[1], sys.argv[2])
