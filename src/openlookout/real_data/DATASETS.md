# Real datasets used by OpenLookout evaluation

## Used

### 1. RLKWiC (activity-only baseline)
- **URL**: https://zenodo.org/records/11059573 (also https://purl.org/RLKWiC)
- **License**: CC-BY-4.0
- **What**: 8 participants, ~2 months desktop activity; window titles, apps, clipboard, browsed webs, contexts
- **We used**: participant `p1` (richest: 16k+ events, clipboard present)
- **Converter**: `convert_rlkwic.py` → `capture_rlkwic_p1/`
- **Gaps after conversion**: clipboard src/dst inferred; no form_edit; file contents are text extracts; file_save synthesized
- **Solve limit**: almost no verifiable source spreadsheets → cards stayed observation-only

### 2. Labelled AWT (activity-only secondary)
- **URL**: https://github.com/project-pivot/labelled-awt-data
- **License**: GPL-3.0
- **What**: 1 academic user, 4 weeks (2023-03-06 → 2023-04-02), app + window title + start/end + activity/case labels
- **Converter**: `convert_awt.py` → `capture_awt/`
- **Gaps**: no clipboard, no file paths, no form_edit, almost no URLs

### 3. Hybrid DCC expenses + reconstructed activity (SOLVE primary) ✅
- **Documents**: Dublin City Council *Councillor Allowance and Expenses 2024*
  - URL: https://data.gov.ie/dataset/councillor-allowance-and-expenses-dcc
  - Download used: `hybrid/raw/councillor-expenses-2024.csv`
  - **License**: **CC-BY** (Dublin City Council / data.gov.ie)
- **Builder**: `build_hybrid.py` → `home_hybrid/admin/` + `capture_hybrid/`
- **What we did (honest)**:
  - Expanded real monthly category amounts into 941 dated line items (Sep–Oct 2024 window)
  - Built real-derived workbooks: `费用明细.xlsx`, `类别对照.xlsx`, 7 hand-made `周汇总_*.xlsx` (one intentional undercount), bank CSV with recurring charge / price bump / same-day duplicate (amounts seeded from real Petty Cash field = 80)
  - **Activity events are RECONSTRUCTED** to match those files (weekly Friday assembly, clipboard, form pastes) — **not** a live screen recording of a councillor
- **Scale**: 911 events, ~7 weeks, multi-file solve path
- **Ground truth for our own eval only**: `hybrid/GROUND_TRUTH_hybrid.json` (detectors never read it)

## Considered but not used
| Dataset | Why skipped |
|---|---|
| DeniseLewis1/personal-finance-dashboard transactions.csv | Public GitHub sample but **no license declared** on the repo |
| boboIloveyou/RecordMe-App-Switch (HF) | No license declared on the dataset card |
| chenjun082/manictime | App name only, no window titles → too thin for discovery |
| BEHACOM | 1-minute aggregated features, not raw events |
| SWELL-KW | Lab tasks ~3h/person, not multi-week continuous natural use; download heavy |
| Datoric computer-use traces | Commercial license |
| RealityMining / StudentLife | Phone-heavy, not desktop PC activity |
| csvtodashboard sample expenses (CC0) | URL 404 at fetch time |
