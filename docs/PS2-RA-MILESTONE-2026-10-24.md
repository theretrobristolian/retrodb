# PS2 RetroAchievements audit milestone — 24 October 2026

This snapshot records the user's reported **RetroDB-Compatibility(20261024-183134).xlsx** audit, not a live rescanning of RetroNAS. Retain the original workbook and raw CSV as reproducible evidence; these numbers change on later audits.

## Current classified PS2 collection

| Metric | Count |
| --- | ---: |
| PS2 disc images scanned | 1,008 |
| Redundant copies excluded from effective metrics | 121 |
| Effective PS2 images | 887 |
| Accepted RA hash / verified compatible | 370 |
| Classified no achievement set or no matching listing | 517 |
| Outstanding unknown / incompatible eligible images | 0 |
| Eligible RA readiness | 370 / 370 (100%) |

**Important:** 100% is the audit's classified *eligible* subset, not all 887 effective images and not the entire RA PS2 catalogue. Reviewed `NOT_LISTED` and `NO_SET` are logically distinct and should be reported separately in a future non-disruptive reporting improvement.

## Work completed

- Verified PS2 disc images with RAHasher, not serials or filenames alone.
- Added reviewed regional/edition identities and explicit `NOT_LISTED` classifications for difficult titles.
- Kept supported alternative editions distinct (e.g. Metal Gear Solid 2: Sons of Liberty vs Substance, Most Wanted standard vs Black Edition).
- Added patch discovery, patch-source checksum verification, local patched RA hash verification, and backed-up NAS deployment safeguards.
- Kept ROM audit and OPL rename proposals read-only unless an explicit confirmed operation is requested.
- Added consolidated cross-platform **Action Required** worksheet; redundant alternatives with a verified equivalent are excluded from the outstanding queue.
- Preferred supported English-language European Raw Danger! release over Japanese variant for RA 5616.

## Before future changes

1. Keep a copy of the audited XLSX and matching CSV, and compare new runs against this baseline.
2. Preserve existing `OLD_` backup files and patch journals; don't bulk-delete or rename them.
3. Run applicable tests before changing matching, patch selection or NAS write code.
4. Avoid presenting a checksum-verified source as patched/RA-compatible until the **output RA hash** is checked.
5. Do not regress fully-reviewed `NOT_LISTED` games to ambiguous `UNKNOWN` solely from fuzzy title matching.

## PS1 phase — deliberately deferred

The same workbook indicated 87 PS1 images, 55 RA-compatible, 3 unresolved and 15 total Action Required entries, including potential alternative releases and patchable images. Those figures are a starting snapshot, **not** a confirmed remediation plan. When resuming: audit the latest PS1 sheet, separate CUE/BIN issues from actual game identity, validate patch README/source checksums, resolve recommendations systematically and keep original images read-only until a verified patched output exists.

This file records a stopping point; it intentionally makes **no runtime behaviour changes**.
