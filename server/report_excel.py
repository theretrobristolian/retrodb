#!/usr/bin/env python3
"""Create a human-readable multi-console XLSX from RetroDB's RA audit CSV."""
import csv
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

COLS = ['Game name','File name','Disc ID','RA compatible','Reason / next action','RA game ID','Recommended release','Region','Patch URL']
def row_for(r):
    yes = r['status'] == 'matched'
    title = r['ra_game_title'] or r['recommended_ra_title'] or Path(r['path']).stem
    patch = r['preferred_patch_url']
    suggested = bool(r['recommended_ra_title'])
    if yes: status, reason = 'YES', 'Verified RA hash; ready to play'
    elif r['status'] == 'failed': status, reason = 'ERROR', r['error'] or 'Disc hashing failed'
    elif suggested:
        status = 'NO'
        if patch: reason = 'Official patch available; verify required source before applying'
        elif r['local_region'] and r['preferred_region'] and r['local_region'] != r['preferred_region']:
            reason = 'Different region recommended: ' + r['preferred_region']
        else: reason = 'Different ISO release or revision recommended'
        if r['release_guidance']: reason += ' — ' + r['release_guidance']
    elif r['alternative_candidates']: status, reason = 'UNKNOWN', 'Ambiguous title; verify alternatives manually'
    else: status, reason = 'UNKNOWN', 'No confident match; possibly unsupported'
    return [title, Path(r['path']).name, r['local_serial'], status, reason,
            r['ra_game_id'] or r['recommended_ra_game_id'], r['preferred_release_name'],
            r['local_region'], patch]
def xml_sheet(rows):
    xml=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
         '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
         '<cols>']
    for i,width in enumerate(([30,18,20,24,24,18] if len(rows[0]) == 6 else [38,54,18,17,75,17,44,16,55]),1):
        xml.append('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i,i,width))
    xml.append('</cols><sheetData>')
    for n,row in enumerate(rows,1):
        xml.append('<row r="%d">' % n)
        for i,val in enumerate(row):
            style = 1 if n == 1 else (2 if n%2 == 0 else 0)
            if n > 1 and len(row) == 9 and i == 3:
                style = {'YES':3,'NO':4,'UNKNOWN':5,'ERROR':6}.get(val,style)
            xml.append('<c r="%s%d" s="%d" t="inlineStr"><is><t>%s</t></is></c>' %
                       (chr(65+i),n,style,escape(str(val or ''))))
        xml.append('</row>')
    xml.append('</sheetData><autoFilter ref="A1:%s%d"/></worksheet>' % (chr(64+len(rows[0])),len(rows)))
    return ''.join(xml)
def main(source,destination):
    with open(source,newline='',encoding='utf-8-sig') as handle: entries=list(csv.DictReader(handle))
    assert entries and 'preferred_patch_url' in entries[0], 'Invalid RetroDB audit CSV'
    sheets=[]
    summary=[['Console','Disc images','RA compatible','Alternative ISO','Unknown','Hash errors']]
    for platform,name in [('Sony PlayStation','PlayStation 1'),('Sony PlayStation 2','PlayStation 2')]:
        entries_console=sorted((row_for(r) for r in entries if r['platform']==platform),
                               key=lambda r:(r[0].casefold(),r[1].casefold()))
        counts=Counter(r[3] for r in entries_console)
        summary.append([name,len(entries_console),counts['YES'],counts['NO'],counts['UNKNOWN'],counts['ERROR']])
        sheets.append((name,[COLS]+entries_console))
    sheets.insert(0,('Summary',summary))
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'%i for i in range(1,len(sheets)+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>'%(name,i,i) for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'%(i,i) for i in range(1,len(sheets)+1))+'<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml','<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/></font><font><b/><color rgb="FFFFFFFF"/></font></fonts><fills count="7"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'+''.join('<fill><patternFill patternType="solid"><fgColor rgb="%s"/></patternFill></fill>'%c for c in ('FF17365D','FFF1F5F9','FFDDF4E4','FFFFE5CC','FFFDF1C8'))+'</fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="7">'+''.join('<xf numFmtId="0" fontId="%d" fillId="%d" borderId="0" xfId="0"/>'%(1 if i==1 else 0, {0:0,1:2,2:3,3:4,4:5,5:6,6:6}[i]) for i in range(7))+'</cellXfs></styleSheet>')
        for i,(_,rows) in enumerate(sheets,1): z.writestr('xl/worksheets/sheet%d.xml'%i,xml_sheet(rows))
    print('[OK] Excel audit exported:',destination)
    for row in summary[1:]: print('    %s: %s compatible, %s alternative releases, %s unknown' % (row[0],row[2],row[3],row[4]))
if __name__=='__main__':
    if len(sys.argv)!=3: sys.exit('Usage: python3 server/report_excel.py input.csv output.xlsx')
    main(sys.argv[1],sys.argv[2])
