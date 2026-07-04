# Retrieval Validation Report

Generated: 2026-07-02

## Data Structure Validation

Validates that expected data sections exist in the canonical KB.

| Topic | Query | Expected Sections | Status |
|-------|-------|-------------------|--------|
| AIML fees | AIML fees | courses.btech.AIML.fees, fees_summary.btech_ee_aiml_ds_cy_csd | OK |
| Data Science fees | Data Science fees | courses.btech.DS.fees, fees_summary.btech_ee_aiml_ds_cy_csd | OK |
| semester fee | semester fee | fees_summary.semester_wise_*, fees_summary.*.per_semester | ISSUE |
| | | _Expected section fees_summary.semester_wise_* not fully present or empty_ | |
| principal | principal | principal.name, principal.email | OK |
| HOD | HOD | departments.*.hod.name | ISSUE |
| | | _Expected section departments.*.hod.name not fully present or empty_ | |
| faculty | faculty | departments.*.hod, academics.faculty, principal, vice_principal | ISSUE |
| | | _Expected section departments.*.hod not fully present or empty_ | |
| placement | placement | placements.*, courses.btech.*.placement | ISSUE |
| | | _Expected section courses.btech.*.placement not fully present or empty_ | |
| hostel | hostel | hostel.* | OK |
| documents | documents | admission_documents.* | OK |
| scholarship | scholarship | scholarships.* | OK |

## Production Hallucination Guard Failures

These queries were deflected by the hallucination guard because entities were not found in retrieved context:

| Query | Reason | Count |
|-------|--------|-------|
| What are the charges for the library? | out_of_kb_deflection | 9 |
| Do engineering students have to pay lab fees separately? | out_of_kb_deflection | 9 |
| Can I pay fees in installments? | out_of_kb_deflection | 8 |
| What's the acceptance rate for BCREC? | out_of_kb_deflection | 8 |
| Do you offer lateral entry for diploma holders? | out_of_kb_deflection | 8 |
| How many faculty members are in the ECE department? | out_of_kb_deflection | 8 |
| Can I transfer from another college? | out_of_kb_deflection | 7 |
| What are the qualifications of the CSE HOD? | out_of_kb_deflection | 7 |
| When does the placement season start? | out_of_kb_deflection | 6 |
| What sports facilities are available? | out_of_kb_deflection | 6 |
| Who handles student affairs? | out_of_kb_deflection | 4 |
| How many hostels are there in BCREC? | out_of_kb_deflection | 4 |
| Is there a library with good resources? | out_of_kb_deflection | 3 |
| Who is responsible for placements? | out_of_kb_deflection | 3 |
| What's the college address? | out_of_kb_deflection | 3 |
| Shara bochhor abedon grohito hoy ki? | out_of_kb_deflection | 3 |
| GATE score proyojon ache ki? | out_of_kb_deflection | 3 |
| Poroborti bhirti chokro kokhon? | out_of_kb_deflection | 3 |
| Principal ke baare mein batao | hallucination_guard: entities not found in context: ['0343', '2501353', '03432501353'] | 3 |
| Bhai Mars mission kaise join karein? | low_confidence_retrieval_0.093 | 3 |
| What's the placement rate? | hallucination_guard: entities not found in context: ['936'] | 2 |
| placement rate kya hai? | hallucination_guard: entities not found in context: ['936'] | 2 |
| Hostel ache? | hallucination_guard: entities not found in context: ['১৫০০', '২০০০'] | 2 |
| What are the college timings? | out_of_kb_deflection | 2 |
| Bhortir jonno ki ki dolil lage? | out_of_kb_deflection | 2 |
| What is the placement rate of IT and how many companies visited? | out_of_kb_deflection | 2 |
| Who is the principal of this college? | hallucination_guard: entities not found in context: ['03432501353'] | 2 |
| How many companies visited in 2025? | out_of_kb_deflection | 1 |
| Tell me about Dr. Chandan Chattoraj | out_of_kb_deflection | 1 |
| ??? ??? ????? ???? | out_of_kb_deflection | 1 |
| ??????????? ??? | out_of_kb_deflection | 1 |
| vice principal name | hallucination_guard: entities not found in context: ['0343', '2501353', '03432501353'] | 1 |
| placement rate | hallucination_guard: entities not found in context: ['0343', '2501353', '03432501353'] | 1 |
| who is vice principal | hallucination_guard: entities not found in context: ['0343', '2501353', '03432501353'] | 1 |
| vice principal name | out_of_kb_deflection | 1 |
| I have 90k WBJEE rank and 50% marks in PCM, can I get admission? | hallucination_guard: entities not found in context: ['90000'] | 1 |
| What is his phone number? | hallucination_guard: entities not found in context: ['03432501353'] | 1 |
| मुझे सीएसी एंड एआईएमएल डिपार्टमेंट का फैकल्टी बारे में बताइए कौन कौन है क्या क्या है | out_of_kb_deflection_stream | 1 |
| Ami admission nite pari? | hallucination_guard: entities not found in context: ['03432501353'] | 1 |
| Who is the vice Principal of this college? | out_of_kb_deflection_stream | 1 |
| What's the fee structure for IT branch? | hallucination_guard: entities not found in context: ['98225'] | 1 |
| What's the contact number of the Principal's office? | hallucination_guard: entities not found in context: ['03432501353'] | 1 |
| Is GATE score required for admission? | out_of_kb_deflection | 1 |
| Do you have computer labs? | out_of_kb_deflection | 1 |
| What is the total cost of studying at BCREC? | out_of_kb_deflection | 1 |
| Can I meet the Vice Principal? | out_of_kb_deflection | 1 |
| What's the contact number of the Principal's office? | out_of_kb_deflection | 1 |
| How many companies visited for placements? | out_of_kb_deflection | 1 |
| Do final year students get guaranteed placements? | out_of_kb_deflection | 1 |
| How many students got placed last year? | out_of_kb_deflection | 1 |
| BCREC mein padhai ka total kharcha kitna hai? | out_of_kb_deflection | 1 |
| ECE saal mein kitne rupaye ka kharch hai? | out_of_kb_deflection | 1 |
| Library ke liye kitna charge hai? | out_of_kb_deflection | 1 |
| Agla pravesh chakra kab hai? | out_of_kb_deflection | 1 |
| CSE ke HOD ki yogyataen kya hain? | out_of_kb_deflection | 1 |
| Kya main Vice Principal se mil sakta hoon? | out_of_kb_deflection | 1 |
| Principal karyalaya ka phone number kya hai? | hallucination_guard: entities not found in context: ['03432501353'] | 1 |
| Pichhle saal kitne chhatron ko jagah mili? | out_of_kb_deflection | 1 |
| Placement ke liye kitni companies aayin? | out_of_kb_deflection | 1 |
| Kya parivahan uplabdh hai? | out_of_kb_deflection | 1 |
| Engineering shiksharthider alada lab fee dite hoy ki? | out_of_kb_deflection | 1 |
| CSE ebong anyo vibhager modhye fee parthokko koto? | hallucination_guard: entities not found in context: ['03432501353'] | 1 |
| Shikkharthi bishoyok dayittwe ke ache? | out_of_kb_deflection | 1 |
| Placement season kokhon shuru hoy? | out_of_kb_deflection | 1 |
| Campus e hostel ache ki? | out_of_kb_deflection | 1 |
| Ki ki khelar subidha ache? | out_of_kb_deflection | 1 |
| Campus e WiFi ache ki? | out_of_kb_deflection | 1 |
| Poribohon upolobdh ache ki? | out_of_kb_deflection | 1 |
| What is the weather like in Durgapur? | out_of_kb_deflection | 1 |
| Who won the 2024 T20 World Cup? | out_of_kb_deflection | 1 |
| What is the stock price of Apple? | out_of_kb_deflection | 1 |
| Does BCREC have a library? | out_of_kb_deflection | 1 |
| Does BCREC have online classes? | out_of_kb_deflection | 1 |
| Vorti process ta ki? | out_of_kb_deflection | 1 |
| Tell me about the CSE department | out_of_kb_deflection | 1 |
| How many hostels are there in BCREC? | out_of_kb_deflection_stream | 1 |
| How many hostels are there in BCREC? | hallucination_guard: entities not found in context: ['03432501353', '03432502449'] | 1 |
| DC Royal का | out_of_kb_deflection_stream | 1 |
| What is the capital of France? | low_confidence_retrieval_0.045 | 1 |
| How many seats in ECE department? | out_of_kb_deflection | 1 |
| What is the cutoff for WBJEE? | hallucination_guard: entities not found in context: ['0343', '2501353', '03432501353'] | 1 |
| What is the fee for CSE? | hallucination_guard: entities not found in context: ['98225'] | 1 |
| Is there any scholarship for SC students? | hallucination_guard: entities not found in context: ['03432501353'] | 1 |

## Known Data Deficiencies (from production gaps)

| Topic | Queries Deflected | Root Cause |
|-------|-------------------|------------|
| Fees | Fee-specific queries (library charges, lab fees) | Separate lab/library fee info not in KB |
| Placement | Placement rate, season start | Phone numbers in context causing hallucination guard false positives |
| Faculty | Faculty count, HOD qualifications | No per-department faculty lists beyond HOD |
| Hostel | Hostel count, facilities | Entity extraction incorrectly picking phone numbers |
| Principal/VP | VP name, Principal contact | Phone numbers in context triggering false entity check |
| Transfer/Acceptance | Lateral entry, acceptance rate | Info exists in KB but not retrieved with high confidence |
