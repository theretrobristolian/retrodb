#!/usr/bin/env python3
"""Create a human-readable multi-console XLSX from RetroDB's RA audit CSV."""
import csv
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape
sys.path.insert(0, str(Path(__file__).resolve().parent))
from online_catalogue import ONLINE_COLUMNS, load as load_online, report_row as online_report_row

COLS = ['Game name','File name','Disc ID','RA compatible','Patchable','Reason / next action','RA game ID','Recommended release','Region','Patch URL','GameDB identity','RA candidates to review','Disc classification','Collection decision','RA set status','RA no-set game ID','Identity evidence','Resolution detail','Patch status','Patch type','Patch warning']
VERIFIED = 'clean-base-verified-ready-to-patch'
def patch_sources(path):
    """Index precisely checksum-verified patchable collection sources by RA ID."""
    if not path or not Path(path).is_file(): return {}
    with open(path,encoding='utf-8') as handle: records=json.load(handle)
    return {
        (str(row.get('collection_source','')), str(row.get('ra_game_id',''))): row
        for row in records
        if row.get('state') == VERIFIED and row.get('candidate_path') == row.get('collection_source')
        and row.get('candidate_path') and row.get('ra_game_id')
    }

def patched_outputs(path):
    """Only report VERIFIED when the saved patched output still exists."""
    if not path or not Path(path).is_file():
        return set()
    try:
        with open(path, encoding='utf-8') as handle:
            records = json.load(handle)
        return {(str(row.get('ra_game_id', '')), str(row.get('title', '')))
                for row in records if row.get('status') == 'patched-and-verified'
                and row.get('ra_hash') and row.get('output')
                and Path(row['output']).is_file()}
    except (OSError, ValueError, TypeError):
        return set()


def patch_kind(r):
    label = (r.get('preferred_release_name') or '').casefold()
    if 'anti-cheat' in label or 'anti cheat' in label:
        return 'Anti-cheat'
    if 'debug patch' in label:
        return 'Debug restriction (verify instructions)'
    if 'region conversion' in label:
        return 'Region conversion (verify instructions)'
    return 'Other / review patch notes'


def row_for(r, verified_sources=frozenset(), root='/mnt/retrodb-retronas', verified_outputs=frozenset()):
    yes = r['status'] == 'matched' and r.get('ra_set_status', 'HAS_SET') == 'HAS_SET'
    title = r.get('ra_game_title') or r.get('recommended_ra_title') or r.get('gamedb_title') or r.get('local_friendly_title') or Path(r['path']).stem
    source = str(Path(root) / r['path'])
    verified_variant = verified_sources.get((source, str(r.get('recommended_ra_game_id', '')))) if isinstance(verified_sources, dict) else None
    patch = (verified_variant or {}).get('patch_url') or r['preferred_patch_url']
    release = (verified_variant or {}).get('required_release') or r['preferred_release_name']
    suggested = bool(r['recommended_ra_title'])
    patchable = bool(not yes and suggested and verified_variant and patch)
    verified_output = (str(r.get('recommended_ra_game_id', '')), r.get('recommended_ra_title', '')) in verified_outputs
    mismatch = (bool(r.get('local_region')) and bool(r.get('preferred_region'))
                and r['local_region'].casefold() != r['preferred_region'].casefold())
    warning = ('LOCAL REGION MISMATCH: ' + r['local_region'] + ' disc; patch targets '
               + r['preferred_region'] + '. No region conversion is implied.' if mismatch and patch else '')
    patch_state = ('VERIFIED' if verified_output else 'READY' if patchable else
                   'AVAILABLE' if patch else 'NONE')
    patch_status = 'YES' if patchable else 'NO'
    if yes: status, reason = 'YES', 'Verified RA hash; ready to play'
    elif patchable: status, reason = 'NO', 'READY: exact local source checksum verified; apply patch to a separate copy, then verify output RA hash'
    elif r['status'] == 'failed': status, reason = 'ERROR', r['error'] or 'Disc hashing failed'
    elif suggested:
        status = 'NO'
        if r.get('recommendation_confidence') == 'supported-alternative-edition':
            reason = 'Different edition required for RA: use the recommended supported release; current ISO is not verified'
        elif r.get('recommendation_confidence') == 'verified-serial-alias':
            reason = 'Game identified via verified disc serial; current ISO hash not RA supported'
        elif patch: reason = 'AVAILABLE ONLY: official patch exists, but required clean source is not checksum-verified; do not apply to this ISO'
        elif r['local_region'] and r['preferred_region'] and r['local_region'] != r['preferred_region']:
            reason = 'Different region recommended: ' + r['preferred_region']
        else: reason = 'Different ISO release or revision recommended'
        if r['release_guidance']: reason += ' — ' + r['release_guidance']
    elif r.get('ra_set_status') == 'NOT_LISTED':
        status, reason = 'NO SET', 'User-reviewed: no RetroAchievements game listing found (recheck if catalogue changes)'
    elif r.get('ra_set_status') == 'NO_SET':
        status, reason = 'NO SET', 'RetroAchievements lists this game but has no achievement set'
    elif r.get('disc_classification') == 'special-disc-review':
        status, reason = 'UNKNOWN', 'Promotional/demo or hack compilation: do not assume retail RA compatibility'
    elif r['alternative_candidates']: status, reason = 'UNKNOWN', 'Potential RA titles found; review candidates manually (not verified)'
    elif r.get('gamedb_title'): status, reason = 'UNKNOWN', 'GameDB identified disc; RA identity still needs evidence, not an assumed unsupported release'
    else: status, reason = 'UNKNOWN', 'No confident match; possibly unsupported'
    if warning and not yes:
        reason += ' — ' + warning
    return [title, Path(r['path']).name, r['local_serial'], status, patch_status, reason,
            r['ra_game_id'] or r['recommended_ra_game_id'], release,
            r['local_region'], patch, r.get('gamedb_title', ''), r.get('alternative_candidates', ''), r.get('disc_classification', 'standard'), 'COUNT', r.get('ra_set_status', 'UNRESOLVED'), r.get('no_set_ra_game_id', ''), r.get('identity_resolution', ''), r.get('identity_review_reason', ''), patch_state, patch_kind(r) if patch else '', warning]
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


ACTION_COLS = [
    'Platform', 'Game name', 'File name', 'Disc ID', 'Status', 'Action',
    'Recommended release', 'Recommended region', 'RA game ID',
    'Existing RA-compatible copy', 'Reason / evidence', 'RA candidates',
    'Local RA hash', 'Accepted RA hashes', 'File path',
]


def action_rows(entries, platform):
    """Actionable entries only; retain evidence and avoid redundant work."""
    rows = []
    verified_by_id = {}
    for r in entries:
        if r[3] == 'YES' and str(r[6]).strip():
            verified_by_id.setdefault(str(r[6]).strip(), []).append(r[1])
    for r in entries:
        if r[3] in ('YES', 'NO SET') or str(r[13]).startswith('EXCLUDE'):
            continue
        if r[3] == 'ERROR':
            action = 'Fix disc hash error'
        elif r[4] == 'YES':
            action = 'Apply verified patch; check new RA hash'
        elif r[3] == 'UNKNOWN':
            action = 'Investigate RA identity or listing'
        else:
            action = 'Obtain supported region / edition / revision'
        matched_copy = ' | '.join(verified_by_id.get(str(r[6]).strip(), []))
        rows.append([
            platform, r[0], r[1], r[2], r[3], action,
            r[7], r[8], r[6], matched_copy, r[5], r[11],
            '', '', '',  # populated from the original audit rows below
        ])
    return rows


def action_rows_from_audit(raw_entries, platform, displayed):
    """Join readable Excel decisions to underlying hashes and full paths."""
    by_filename = {}
    for raw in raw_entries:
        if raw.get('platform') == platform:
            by_filename.setdefault((raw.get('local_serial'), Path(raw.get('path', '')).name), []).append(raw)
    actions = action_rows(displayed, platform)
    for row in actions:
        candidates = by_filename.get((row[3], row[2]), [])
        if len(candidates) == 1:
            raw = candidates[0]
            row[12] = raw.get('local_ra_hash', '')
            row[13] = raw.get('accepted_ra_hashes', '')
            row[14] = raw.get('path', '')
    return actions


def xml_sheet(rows):
    xml=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
         '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
         '<cols>']
    for i,width in enumerate(([28,16,18,18,18,20,18,18,18,18,20,22,24,19,24,20,18,18,18] if len(rows[0]) == 19 else [38,54,18,17,16,75,17,44,16,55,44,70,24,38,20,20,28,64,18,32,65]),1):
        xml.append('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i,i,width))
    xml.append('</cols><sheetData>')
    for n,row in enumerate(rows,1):
        xml.append('<row r="%d">' % n)
        for i,val in enumerate(row):
            style = 1 if n == 1 else (2 if n%2 == 0 else 0)
            if n > 1 and len(row) in (18, 21) and i == 3:
                style = {'YES':3,'NO':4,'UNKNOWN':5,'ERROR':6,'NO SET':5}.get(val,style)
            if n > 1 and len(row) == 16 and i == 4 and val == 'YES': style = 3
            xml.append('<c r="%s%d" s="%d" t="inlineStr"><is><t>%s</t></is></c>' %
                       (chr(65+i),n,style,escape(str(val or ''))))
        xml.append('</row>')
    xml.append('</sheetData><autoFilter ref="A1:%s%d"/></worksheet>' % (chr(64+len(rows[0])),len(rows)))
    return ''.join(xml)
def main(source,destination,preparation=None):
    with open(source,newline='',encoding='utf-8-sig') as handle: entries=list(csv.DictReader(handle))
    backups = [r for r in entries if Path(r.get('path', '')).name.casefold().startswith('old_')]
    entries = [r for r in entries if not Path(r.get('path', '')).name.casefold().startswith('old_')]
    if backups: print(f'[INFO] Excluded {len(backups)} OLD_ backup images from compatibility workbook.')
    assert entries and 'preferred_patch_url' in entries[0], 'Invalid RetroDB audit CSV'
    sources = patch_sources(preparation)
    outputs = patched_outputs(str(Path(preparation).with_name('patch-apply.json')) if preparation else None)
    sheets=[]
    online_catalogue = load_online(str(Path.home() / '.cache/retrodb/online-compatibility.json'))
    ps2_online = [online_report_row(r, online_catalogue) for r in entries if r.get('platform') == 'Sony PlayStation 2']
    ps2_online.sort(key=lambda row: (str(row[0]).casefold(), str(row[2])))
    all_actions=[]
    summary=[['Console','Disc images','Effective images','Excluded duplicates','RA-ready %','Eligible RA-ready %','RA eligible images','RA compatible','Patchable','Alternative ISO','No achievement set','Unresolved','GameDB identified unresolved','RA candidates to review','Hash errors','Patchable %','No-set %','Unresolved %','RA identified %']]
    for platform,name in [('Sony PlayStation','PlayStation 1'),('Sony PlayStation 2','PlayStation 2')]:
        entries_console=sorted((row_for(r, sources, verified_outputs=outputs) for r in entries if r['platform']==platform),
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
        all_actions.extend(action_rows_from_audit(entries, platform, active))
    priority = {'Fix disc hash error': 0, 'Apply verified patch; check new RA hash': 1,
                'Obtain supported region / edition / revision': 2, 'Investigate RA identity or listing': 3}
    all_actions.sort(key=lambda row: (priority.get(row[5], 9), row[0], row[1].casefold()))
    print(f'[INFO] Action Required (all platforms): {len(all_actions)} games need attention.')
    sheets.insert(0, ('Action Required', [ACTION_COLS] + all_actions))
    sheets.append(('PS2 Online', [ONLINE_COLUMNS] + ps2_online))
    print(f'[INFO] PS2 online: {len(ps2_online)} local discs; {sum(row[4] == "YES" for row in ps2_online)} with release-specific source evidence.')
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
    print(f'[INFO] Action Required: {len(all_actions)} unresolved, unverified or hash-error entries across all platforms.')
    for row in summary[1:]: print('    %s: %s/%s RA-compatible (%s); %s redundant copies excluded from reporting, %s patchable, %s alternative ISOs, %s unknown' % (row[0],row[7],row[2],row[4],row[3],row[8],row[9],row[11]))
if __name__=='__main__':
    if len(sys.argv) not in (3,4): sys.exit('Usage: python3 server/report_excel.py input.csv output.xlsx [patch-prepare.json]')
    main(sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)==4 else None)
