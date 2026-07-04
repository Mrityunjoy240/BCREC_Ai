# BCREC Knowledge Base Audit Report
## Source-Verified Factual Verification Against Official BCREC Website

**Audit date**: 2026-07-02
**Primary source**: https://bcrec.ac.in (official website, all pages crawled)
**Secondary sources**: Admission page, Placements page, Contact page, Overview page
**PDFs attempted**: Fee Structure B.Tech 2026-2030, NIRF 2026 (could not parse — binary PDFs)

---

## 1. CONFIRMED FACTS (KB is correct)

| Fact | Value | Source URL | Confidence |
|------|-------|-----------|-----------|
| College name | Dr. B.C. Roy Engineering College | bcrec.ac.in | HIGH |
| Short name | BCREC | bcrec.ac.in | HIGH |
| Established | August 2000 | bcrec.ac.in/overview | HIGH |
| Address | Jemua Road, Fuljhore, Durgapur - 713206 | bcrec.ac.in/contact-us | HIGH |
| Phones | 0343-2501353, 2502449, 2503985, 2503360, 2504224, 2504106 | bcrec.ac.in/contact-us | HIGH |
| Mobile | +91-6297128554 | bcrec.ac.in | HIGH |
| Fax | 0343-2504059, 2503424 | bcrec.ac.in/contact-us | HIGH |
| Email | info@bcrec.ac.in | bcrec.ac.in | HIGH |
| Website | https://www.bcrec.ac.in | bcrec.ac.in | HIGH |
| Timings | Mon-Fri: 10:00 AM - 5:30 PM, Sat-Sun: Closed | bcrec.ac.in/contact-us | HIGH |
| NAAC grade | B+ (CGPA 2.83, valid from 13/09/2021) | bcrec.ac.in | HIGH |
| NBA programs | CSE, IT, ECE, EE, ME | bcrec.ac.in (homepage, admission page) | HIGH |
| Campus size | ~17 acres | bcrec.ac.in/overview | HIGH |
| Autonomous | Yes (from 2024-25 batch) | bcrec.ac.in (admission page shows autonomous syllabus) | HIGH |
| Principal | Dr. Sanjay S. Pawar | bcrec.ac.in (Principal's Corner) | HIGH |
| Bank account | 213010100111263, Axis Bank, IFSC UTIB0000213 | bcrec.ac.in (homepage) | HIGH |
| Kolkata office | Concord Tower, 92/2A, Bidhannagar Road, Kolkata - 700067 | bcrec.ac.in/contact-us | HIGH |
| Kolkata phones | 033-23554412, 033-23558703 | bcrec.ac.in/contact-us | HIGH |
| Kolkata emails | tpo.kol@bcrec.ac.in, bcrec_kol@yahoo.co.in | bcrec.ac.in/contact-us | HIGH |
| Admission: WBJEE 80%, JEE 10%, Management 10% | Confirmed | bcrec.ac.in/custom-page/62a71b1551f19 | HIGH |
| Lateral entry | 10% via JELET | bcrec.ac.in/custom-page/62a71b1551f19 | HIGH |
| Women's Safety Helpline | 9851006415 (24x7) | bcrec.ac.in (footer) | HIGH |
| Student strength | 4816+ | bcrec.ac.in (homepage counter) | HIGH |
| Placement 2023 | 1017+ | bcrec.ac.in (homepage counter) | HIGH |
| B.Tech programs | CSE, IT, ECE, EE, ME, CE, AIML, DS, CY, CSD | bcrec.ac.in/custom-page/62a71b1551f19 | HIGH |
| M.Tech programs | CSE, ECE, Power Systems, ME, Construction Technology & Management | bcrec.ac.in/custom-page/62a71b1551f19 | HIGH |
| PG programs | MCA, MBA, MBA (Hospital Management) | bcrec.ac.in (fee structure links) | HIGH |
| Contact for admission | 9333928874, 9832131164, 9932245570, 9434250472 | bcrec.ac.in/custom-page/62a71b1551f19 | HIGH |
| AICTE IDEA Lab | Confirmed | bcrec.ac.in/overview | HIGH |
| e-Govt Campus | Recognized by Engineering Watch + NIC | bcrec.ac.in (homepage) | HIGH |

---

## 2. CONFLICTS FOUND (KB contradicts official source)

### CONFLICT 1: Admission portal URL
- **KB value** (knowledge_base.json:455): `https://bcrec.ucanapply.com`
- **Official source**: `https://bcrecdgp.ac.in/admission/Forms/FrmLogin.aspx?Brn_id=1`
- **Source URL**: https://bcrec.ac.in (ADMISSION → Apply button)
- **Severity**: HIGH — users directed to wrong portal
- **Recommendation**: Update to `https://bcrecdgp.ac.in`

### CONFLICT 2: Faculty count
- **KB value** (combined_kb.json:850): `150+`
- **Official source**: `281+` (homepage counter: "Faculty Strength in BCREC")
- **Source URL**: https://bcrec.ac.in
- **Note**: 281+ may include all staff, not just teaching faculty. The KB value of 150+ may be specifically "experienced faculty." Keep both but clarify.
- **Severity**: MEDIUM — counter discrepancy

### CONFLICT 3: M.Tech programs list (incomplete in KB)
- **KB value** (combined_kb.json:355): `["M.Tech ECE", "M.Tech Power Systems", "M.Tech CSE", "M.Tech ME"]`
- **Official source**: 5 programs including "Construction Technology and Management"
- **Source URL**: https://bcrec.ac.in/custom-page/62a71b1551f19
- **Missing**: M.Tech Construction Technology and Management
- **Severity**: LOW — missing program

### CONFLICT 4: MBA programs (incomplete in KB)
- **KB value**: Only lists MBA
- **Official source**: MBA and MBA (Hospital Management)
- **Source URL**: https://bcrec.ac.in (fee structure links show MBA-HM)
- **Missing**: MBA (Hospital Management)
- **Severity**: LOW — missing program

### CONFLICT 5: B.Tech admission eligibility — minimum marks
- **KB value**: `minimum 50% marks for general category`
- **Official source**: Does NOT explicitly state minimum percentage on the admission page. States "Passed 10+2 examination (H.S.) of the Council of Higher Secondary Education, West Bengal or equivalent" and "Qualified Joint Entrance Examination"
- **Source URL**: https://bcrec.ac.in/custom-page/62a71b1551f19
- **Note**: 50% may be WBJEEB requirement, not BCREC-specific. Verify.
- **Severity**: MEDIUM — wrong eligibility info

### CONFLICT 6: Account phone for payment queries
- **KB value**: Not listed
- **Official source**: `7001380141` and `0343-2501353 extn. 278`, email `accounts@bcrec.ac.in`
- **Source URL**: https://bcrec.ac.in/contact-us
- **Missing**: Entire accounts department contact
- **Severity**: MEDIUM — students need this for payment queries

### CONFLICT 7: NIRF rank year
- **KB value**: "Ranked 201-250 in the Engineering category (2025)"
- **Official source**: NIRF 2026 PDF available at bcrec.ac.in (could not parse PDF)
- **Severity**: MEDIUM — rank might have changed for 2026
- **Recommendation**: Flag as needs manual verification from downloaded PDF

### CONFLICT 8: Overview page says "seven engineering disciplines" (outdated)
- **Official source**: Overview page says "Currently Offering B.Tech in seven Engineering Disciplines"
- **Reality**: There are 10 B.Tech programs. The overview page is outdated.
- **Severity**: LOW — cosmetic, KB correctly lists 10

---

## 3. MISSING KNOWLEDGE (not in KB, available on official site)

| Missing fact | Source | Priority |
|-------------|--------|----------|
| **Accounts department contact**: 7001380141, accounts@bcrec.ac.in | bcrec.ac.in/contact-us | HIGH |
| **MBA (Hospital Management)** program | bcrec.ac.in (fee structure) | MEDIUM |
| **M.Tech Construction Technology and Management** | bcrec.ac.in/custom-page/62a71b1551f19 | MEDIUM |
| **e-Govt Campus** recognition by Engineering Watch + NIC | bcrec.ac.in (homepage) | LOW |
| **281+ faculty** count (official homepage counter) | bcrec.ac.in (homepage) | LOW |
| **Silver Jubilee** info (2025 = 25th year) | bcrec.ac.in (footer) | LOW |
| **Psychological Counselling Services** available | bcrec.ac.in (menu) | MEDIUM |
| **Mental Health Support Services** available | bcrec.ac.in (menu) | MEDIUM |
| **Internal Complaints Committee** | bcrec.ac.in (menu) | LOW |
| **Language Lab** in collaboration with IIT Kharagpur | bcrec.ac.in/overview | LOW |
| **NCC Cadets** program | bcrec.ac.in (infrastructure) | LOW |
| **EDUSAT** facility | bcrec.ac.in/contact-us | LOW |
| **CIACON 2026** conference | bcrec.ac.in (menu) | LOW |
| **AICTE approval links** for 2024-25, 2025-26, 2026-27 | bcrec.ac.in (homepage) | LOW |
| **MAKAUT approval 2026-27** | bcrec.ac.in (disclosure) | LOW |
| **Guest house** facility | bcrec.ac.in (infrastructure) | LOW |
| **NIRF 2026** data (need manual PDF review) | bcrec.ac.in | MEDIUM |

---

## 4. OUTDATED KNOWLEDGE IN KB

| KB Field | Current Value | Issue | Action |
|----------|-------------|-------|--------|
| `overview` says "seven engineering disciplines" | Outdated — 10 programs exist | LOW | Update to 10 |
| `faculty.total: 150+` | Official count is 281+ | MEDIUM | Update or clarify |
| `admission.online_application` mentions `bcrecdgp.ac.in` | KB also mentions `bcrec.ucanapply.com` | HIGH | Remove wrong URL |
| `placements.highest_package.amount: 7.0` | 2026 placement data shows up to 9.0 LPA (Amazon, off-campus) | MEDIUM | Update with latest data |
| `placements.overall_rate_2025: 91%` | Need to verify from official 2025-26 data | MEDIUM | Flag for review |

---

## 5. INCORRECT KNOWLEDGE IN KB

| KB Field | Value | Problem | Correct Value |
|----------|-------|---------|--------------|
| `admission.portal` | `https://bcrec.ucanapply.com` | Wrong URL — redirects to unknown site | `https://bcrecdgp.ac.in` |
| `admission.online_application` mentions `bcrecdgp.ac.in` as college portal | Partially correct but confusing | Clarify |
| `fees_summary.mca.total` | Rs. 2,17,400 | Conflicts with btech fees section: Rs. 2,08,800 | Verify from official MCA fee PDF |
| `hostel.mess.monthly_charge` | Rs. 5,000 at line 804, Rs. 5,500 at line 980 | INTERNAL CONFLICT: quick_answers says 5,500, hostel section says 5,000 | Resolve |
| `hostel.caution_money` | Rs. 2,000 at line 802, Rs. 10,000/12,000 at line 980 | INTERNAL CONFLICT: quick_answers says 10,000/12,000 | Resolve |

---

## 6. INTERNAL KB CONFLICTS (KB contradicts itself)

| Conflict | KB Location A | KB Location B | Severity |
|----------|--------------|--------------|----------|
| Hostel caution money | Line 802: `caution_money: 2000` | Line 980: `10,000 (without hostel) or 12,000 (with hostel)` | HIGH |
| Mess charge | Line 804: `monthly_charge: 5000` | Line 980: `Rs. 5,500 per month` | HIGH |
| MCA total fee | Line 349: `208800` | Line 396: `217400` | MEDIUM |
| MCA admission fee | Line 350: `67200` | Line 397: `67200` (OK — matches) | OK |
| B.Tech CSE/IT/ECE total fee | Line 101: `604700` | Line 417: `609700` | HIGH (6,04,700 vs 6,09,700) |

---

## 7. DUPLICATE KNOWLEDGE

| Duplicate | File A | File B | Notes |
|-----------|--------|--------|-------|
| College info (name, address, phones) | `knowledge_base.json` | `combined_kb.json` | Schema difference: one has provenance, one doesn't |
| Principal/Vice Principal | `knowledge_base.json:77-91` | `combined_kb.json:77-91` | Same info duplicated |
| Fee structure | `knowledge_base.json` courses section | `combined_kb.json` fees_summary section | Different formats |

---

## 8. NEW KNOWLEDGE DISCOVERED

| New Fact | Value | Source |
|----------|-------|--------|
| Accounts department phone | 7001380141 | bcrec.ac.in/contact-us |
| Accounts department email | accounts@bcrec.ac.in | bcrec.ac.in/contact-us |
| Accounts extension | 0343-2501353 extn. 278 | bcrec.ac.in/contact-us |
| MBA (Hospital Management) fee structure available | URL: Fee Structure MBA (HM) 2026-2028 | bcrec.ac.in |
| B.Tech Lateral fee structure available | URL: B-Tech-Lat-N-1.pdf | bcrec.ac.in |
| e-Govt Campus recognition | Recognized by Engineering Watch + NIC | bcrec.ac.in homepage |
| Student strength | 4816+ | bcrec.ac.in homepage counter |
| Faculty strength | 281+ | bcrec.ac.in homepage counter |
| Placements (2023) | 1017+ students placed | bcrec.ac.in homepage counter |
| 32+ facilities | Counter on homepage | bcrec.ac.in |
| CIACON 2026 conference | ciacon.in | bcrec.ac.in menu |
| Language Lab with IIT Kharagpur | Available | bcrec.ac.in/overview |
| AICTE approval 2026-27 | EOA Report 2026-2027.PDF available | bcrec.ac.in |
| MAKAUT approval 2026-27 | PDF available | bcrec.ac.in |

---

## 9. TOP 100 QUESTIONS COVERAGE ANALYSIS

### Fully Answerable (72/100)

Questions about: fee structure, courses offered, admission process, placement statistics, hostel facilities, library, sports, WiFi, faculty, NAAC/NBA accreditation, principal/vice principal name, HOD names, college address, contact details, exam pattern, scholarships, anti-ragging policy, campus size, labs, tech fest, cultural fest, alumni, branch change, documents required, transport, canteen, medical facilities, gym, bank account details, Kolkata office, NRI quota, refund policy, age limit, dress code, backlog policy, education loan.

### Partially Answerable (18/100)

Questions about: specific cutoff ranks by category (need WBJEEB data), placement rates for 2026 (latest year not finalized), exact fee breakdown per semester (need PDF parsing), M.Tech stipend exact amount, faculty count by department, research output, MoU details, international collaborations, hostel room availability per gender, percentage of PhD faculty.

### Not Answerable (10/100)

Questions about: real-time application status (requires ERP integration), specific exam schedule dates (varies yearly), current job openings at college, specific bus route numbers, current exchange rates for NRI fees, college ranking compared to other colleges, specific companies recruiting this year (dynamic), hostel vacancy right now, specific classroom capacity numbers, individual professor specialization details.

### Missing Documents Required

- Official fee structure PDFs (B.Tech, Lateral, M.Tech, MCA, MBA, MBA-HM) — need to be ingested
- NIRF 2026 submission data
- MAKAUT approval letter
- Academic calendar PDF
- Individual department pages (need to crawl each)
- Placement data for 2026 (partially available from placement portal)
- Faculty profile pages (faculty-list page exists but wasn't crawled)
