# Knowledge Base Audit Report

Generated: 2026-07-02

## 1. Duplicate Information

- knowledge_base.json and canonical/canonical_kb.json contain overlapping data (fees, HODs, placements) in different formats
- fees_summary has both aggregate (btech_cse_it_ece) and detailed (semester_wise_cse_it_ece) sections with overlapping data
- CSE/IT/ECE fees appear in both fees_summary.btech_cse_it_ece and fees_summary.semester_wise_cse_it_ece

## 2. Conflicting Values

- **EE/AIML/DS/CY/CSD total fee (arithmetic check)**: "Rs. 554100 (stated)" vs "Rs. 555600 (first 91900 + 6*66100 + eighth 67100)"
  - Source A: `canonical_kb.json > fees_summary > semester_wise_ee_group > total_btech`
  - Source B: `computed from same section`

- **ME/CE total fee (arithmetic check)**: "Rs. 444100 (stated)" vs "Rs. 364750 (first 78150 + 6*40800 + eighth 41800)"
  - Source A: `canonical_kb.json > fees_summary > semester_wise_me_ce > total_btech`
  - Source B: `computed from same section`

- **ME/CE per_semester fee consistency**: "Rs. 40800 (stated per_semester)" vs "Rs. 52279 (derived from (total - first) / 7)"
  - Source A: `canonical_kb.json > fees_summary > semester_wise_me_ce > per_semester`
  - Source B: `computed from same section`

- **btech_cse_it_ece vs semester_wise_cse_it_ece total fee**: "Rs. 604700 (from btech_cse_it_ece)" vs "Rs. 609700 (from semester_wise_cse_it_ece)"
  - Source A: `canonical_kb.json > fees_summary > btech_cse_it_ece > total`
  - Source B: `canonical_kb.json > fees_summary > semester_wise_cse_it_ece > total_btech`

- **MCA total fee**: "Rs. 208800 (from courses.mca.fees.total)" vs "Rs. 217400 (from fees_summary.mca.total)"
  - Source A: `canonical_kb.json > courses > mca > fees > total > value`
  - Source B: `canonical_kb.json > fees_summary > mca > total > value`

- **M.Tech total fee format discrepancy**: "Rs. 120400 (single value from courses.mtech.fees.total)" vs "Rs. 126000 to 206000 (range from fees_summary.mtech.total)"
  - Source A: `canonical_kb.json > courses > mtech > fees > total > value`
  - Source B: `canonical_kb.json > fees_summary > mtech > total > value`

- **Campus size (acres)**: "17 (current)" vs "25 (historical, per college.md)"
  - Source A: `canonical_kb.json > college > campus_size_acres > value`
  - Source B: `canonical_kb.json > college > campus_size_acres > history[0] > value (originally from college.md)`

- **Admission portal URLs**: "https://bcrec.ucanapply.com (from canonical portal field)" vs "bcrecdgp.ac.in (mentioned in knowledge_base.json admission.online_application)"
  - Source A: `canonical_kb.json > admission > portal > value`
  - Source B: `knowledge_base.json > admission > online_application > en`

- **CSE intake (seats)**: "180 (current)" vs "120 (historical, from cse.md)"
  - Source A: `canonical_kb.json > courses > btech > CSE > intake > value`
  - Source B: `canonical_kb.json > courses > btech > CSE > intake > history[0] > value`

- **IT intake (seats)**: "60 (current)" vs "120 (historical)"
  - Source A: `canonical_kb.json > courses > btech > IT > intake > value`
  - Source B: `canonical_kb.json > courses > btech > IT > intake > history[0] > value`

- **MCA intake (seats)**: "120 (current)" vs "60 (historical)"
  - Source A: `canonical_kb.json > courses > mca > intake > value`
  - Source B: `canonical_kb.json > courses > mca > intake > history[0] > value`

- **Hostel caution money**: "Rs. 2000 (current)" vs "Rs. 2000 (historical; official PDF says Rs. 12,000)"
  - Source A: `canonical_kb.json > hostel > caution_money > value`
  - Source B: `canonical_kb.json > hostel > caution_money > history[0] (provenance notes mention PDF conflict)`

- **Mess monthly charge**: "Rs. 5000 (current)" vs "Rs. 4,800 (official PDF) / Rs. 5,500 (quick_answers)"
  - Source A: `canonical_kb.json > hostel > mess > monthly_charge > value`
  - Source B: `canonical_kb.json > hostel > mess > monthly_charge > provenance > notes`


## 3. Missing HOD Information

Nothing missing.

## 4. Missing Fee Information

Nothing missing.

## 5. Missing Placement Statistics

- MBA: No placement data
- MCA: No placement data

## 6. Missing Faculty Information

- AIML: No faculty listing beyond HOD
- CE: No faculty listing beyond HOD
- CSD: No faculty listing beyond HOD
- CSE: No faculty listing beyond HOD
- CY: No faculty listing beyond HOD
- DS: No faculty listing beyond HOD
- ECE: No faculty listing beyond HOD
- EE: No faculty listing beyond HOD
- IT: No faculty listing beyond HOD
- MBA: No faculty listing beyond HOD
- MCA: No faculty listing beyond HOD
- ME: No faculty listing beyond HOD

## 7. Missing Laboratory Information

Nothing missing.

## 8. Missing Admission Information

Nothing missing.

## 9. Missing Contact Information

Nothing missing.

## 10. Missing Department Information

Nothing missing.

## 11. Known Knowledge Gaps from Production

Total gaps logged: 178

| Reason | Count |
|--------|-------|
| out_of_kb_deflection | 145 |
| hallucination_guard: entities not found in context: ['03432501353'] | 8 |
| hallucination_guard: entities not found in context: ['0343', '2501353', '03432501353'] | 7 |
| out_of_kb_deflection_stream | 4 |
| hallucination_guard: entities not found in context: ['936'] | 4 |
| low_confidence_retrieval_0.093 | 3 |
| hallucination_guard: entities not found in context: ['১৫০০', '২০০০'] | 2 |
| hallucination_guard: entities not found in context: ['98225'] | 2 |
| hallucination_guard: entities not found in context: ['90000'] | 1 |
| hallucination_guard: entities not found in context: ['03432501353', '03432502449'] | 1 |
| low_confidence_retrieval_0.045 | 1 |

## 12. Key Data Sources

| File | Path | Description |
|------|------|-------------|
| Canonical KB | `backend/data/canonical/canonical_kb.json` | Primary source, 1242 lines, provenance-tracked |
| Flat KB | `backend/data/knowledge_base.json` | Legacy flat KB, 983 lines |
| Admin FAQ | `backend/data/admin_faq.json` | FAQ routing metadata, 510 lines |
| Knowledge Gaps | `backend/data/knowledge_gaps.json` | Production gap log, 1248 lines |
| Dept Markdown | `backend/data/knowledge_base/departments/*.md` | Per-department markdown files (12 files) |
| Topic Markdown | `backend/data/knowledge_base/topics/*.md` | Topic markdown files (admissions, fees, etc.) |
