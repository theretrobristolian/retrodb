#!/usr/bin/env python3
"""Create a human-readable multi-console XLSX from RetroDB's RA audit CSV."""
import csv
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

COLS = ['Game name','File name','Disc ID','RA compatible','Patchable','Reason / next action','RA game ID','Recommended release','Region','Patch URL','GameDB identity','RA candidates to review','Disc classification','Collection decision','RA set status','RA no-set game ID']
VERIFIED = 'clean-base-verified-ready-to-patch'
def patch_sources(path):
    if not path or not Path(path).is_file(): return set()
    with open(path,encoding='utf-8') as handle: records=json.load(handle)
    return {(str(row.get('collection_source','')),str(row.get('title',''))) for row in records
            if row.get('state') == VERIFIED and row.get('candidate_path') == row.get('collection_source')
            and row.get('candidate_path')}

def row_for(r, verified_sources=frozenset(), root='/mnt/retrodb-retronas'):
    yes = r['status'] == 'matched' and r.get('ra_set_status', 'HAS_SET') == 'HAS_SET'
    title = r.get('ra_game_title') or r.get('recommended_ra_title') or r.get('gamedb_title') or r.get('local_friendly_title') or Path(r['path']).stem
    patch = r['preferred_patch_url']
    suggested = bool(r['recommended_ra_title'])
    source = str(Path(root) / r['path'])
    patchable = (not yes and suggested and
                 (source, r['recommended_ra_title']) in verified_sources)
    patch_status = 'YES' if patchable else 'NO'
    if yes: status, reason = 'YES', 'Verified RA hash; ready to play'
    elif patchable: status, reason = 'NO', 'PATCHABLE: source checksum verified in patch-prepare; apply official patch and reverify RA hash'
    elif r['status'] == 'failed': status, reason = 'ERROR', r['error'] or 'Disc hashing failed'
    elif suggested:
        status = 'NO'
        if r.get('recommendation_confidence') == 'verified-serial-alias':
            reason = 'Game identified via verified disc serial; current ISO hash not RA supported'
        elif patch: reason = 'Official patch available; verify required source before applying'
        elif r['local_region'] and r['preferred_region'] and r['local_region'] != r['preferred_region']:
            reason = 'Different region recommended: ' + r['preferred_region']
        else: reason = 'Different ISO release or revision recommended'
        if r['release_guidance']: reason += ' — ' + r['release_guidance']
    elif r.get('ra_set_status') == 'NO_SET':
        status, reason = 'NO SET', 'RetroAchievements lists this game but has no achievement set'
    elif r.get('disc_classification') == 'special-disc-review':
        status, reason = 'UNKNOWN', 'Promotional/demo or hack compilation: do not assume retail RA compatibility'
    elif r['alternative_candidates']: status, reason = 'UNKNOWN', 'Potential RA titles found; review candidates manually (not verified)'
    elif r.get('gamedb_title'): status, reason = 'UNKNOWN', 'GameDB identified disc; no confident RetroAchievements match yet'
    else: status, reason = 'UNKNOWN', 'No confident match; possibly unsupported'
    return [title, Path(r['path']).name, r['local_serial'], status, patch_status, reason,
            r['ra_game_id'] or r['recommended_ra_game_id'], r['preferred_release_name'],
            r['local_region'], patch, r.get('gamedb_title', ''), r.get('alternative_candidates', ''), r.get('disc_classification', 'standard'), 'COUNT', r.get('ra_set_status', 'UNRESOLVED'), r.get('no_set_ra_game_id', '')]
def apply_collection_dedup(entries):
    """Discount only demonstrably redundant noncompatible copies.

    The raw CSV and all ISO files are untouched. Do not hide multi-disc games:
    two verified hashes for the same RA ID remain counted. Also preserve
    unresolved duplicates when there is no compatible copy.
    """
    groups = {}
    for row in entries:
        game_id = str(row[6] or '').strip()
        if game_id:
            groups.setdefault(game_id, []).append(row)
    for group in groups.values():
        verified = [row for row in group if row[3] == 'YES']
        if not verified:
            continue
        for row in group:
            if row[3] != 'YES':
                row[13] = 'EXCLUDE — compatible copy present'
                row[5] = 'Already covered by verified RA-compatible ISO for this RA game ID; retained on RetroNAS'
            else:
                row[13] = 'COUNT — verified'
    return entries


def xml_sheet(rows):
    xml=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
         '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
         '<cols>']
    for i,width in enumerate(([28,16,18,18,18,20,18,18,18,18,20,22,24,19,24,20,18,18,18] if len(rows[0]) == 19 else [38,54,18,17,16,75,17,44,16,55,44,70,24,38,20,20]),1):
        xml.append('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i,i,width))
    xml.append('</cols><sheetData>')
    for n,row in enumerate(rows,1):
        xml.append('<row r="%d">' % n)
        for i,val in enumerate(row):
            style = 1 if n == 1 else (2 if n%2 == 0 else 0)
            if n > 1 and len(row) == 16 and i == 3:
                style = {'YES':3,'NO':4,'UNKNOWN':5,'ERROR':6,'NO SET':5}.get(val,style)
            if n > 1 and len(row) == 16 and i == 4 and val == 'YES': style = 3
            xml.append('<c r="%s%d" s="%d" t="inlineStr"><is><t>%s</t></is></c>' %
                       (chr(65+i),n,style,escape(str(val or ''))))
        xml.append('</row>')
    xml.append('</sheetData><autoFilter ref="A1:%s%d"/></worksheet>' % (chr(64+len(rows[0])),len(rows)))
    return ''.join(xml)
def main(source,destination,preparation=None):
    with open(source,newline='',encoding='utf-8-sig') as handle: entries=list(csv.DictReader(handle))
    assert entries and 'preferred_patch_url' in entries[0], 'Invalid RetroDB audit CSV'
    sources = patch_sources(preparation)
    sheets=[]
    summary=[['Console','Disc images','Effective images','Excluded duplicates','RA-ready %','Eligible RA-ready %','RA eligible images','RA compatible','Patchable','Alternative ISO','No achievement set','Unresolved','GameDB identified unresolved','RA candidates to review','Hash errors','Patchable %','No-set %','Unresolved %','RA identified %']]
    for platform,name in [('Sony PlayStation','PlayStation 1'),('Sony PlayStation 2','PlayStation 2')]:
        entries_console=sorted((row_for(r, sources) for r in entries if r['platform']==platform),
                               key=lambda r:(r[0].casefold(),r[1].casefold()))
        apply_collection_dedup(entries_console)
        active=[r for r in entries_console if not r[13].startswith('EXCLUDE')]
        excluded=len(entries_console)-len(active)
        counts=Counter(r[3] for r in active)
        patched=sum(r[4]=='YES' for r in active)
        identified_unknown=sum(r[3]=='UNKNOWN' and bool(r[10]) for r in active)
        review_count=sum(r[3]=='UNKNOWN' and bool(r[11]) for r in active)
        effective=len(active)
        percent=f'{100*counts["YES"]/effective:.2f}%' if effective else '0.00%'
        eligible=effective-counts['NO SET']
        eligible_percent=f'{100*counts["YES"]/eligible:.2f}%' if eligible else 'N/A'
        summary.append([name,len(entries_console),effective,excluded,percent,eligible_percent,eligible,counts['YES'],patched,counts['NO']-patched,counts['NO SET'],counts['UNKNOWN'],identified_unknown,review_count,counts['ERROR'],
                        f'{100*patched/effective:.2f}%' if effective else '0.00%',
                        f'{100*counts["NO SET"]/effective:.2f}%' if effective else '0.00%',
                        f'{100*counts["UNKNOWN"]/effective:.2f}%' if effective else '0.00%',
                        f'{100*(counts["YES"]+counts["NO"]+counts["NO SET"])/effective:.2f}%' if effective else '0.00%'])
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
    for row in summary[1:]: print('    %s: %s/%s RA-compatible (%s); %s redundant copies excluded from reporting, %s patchable, %s alternative ISOs, %s unknown' % (row[0],row[7],row[2],row[4],row[3],row[8],row[9],row[11]))
if __name__=='__main__':
    if len(sys.argv) not in (3,4): sys.exit('Usage: python3 server/report_excel.py input.csv output.xlsx [patch-prepare.json]')
    main(sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)==4 else None)
