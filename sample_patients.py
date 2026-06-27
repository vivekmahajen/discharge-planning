"""Synthetic, data-rich sample patients for the discharge-planning demo.

100 fictional patients spanning common discharge-planning scenarios (CHF, COPD,
stroke, hip fracture, sepsis, CABG, etc.). All data is entirely fabricated — NO
real PHI. Generation is deterministic (index-based) so the list and tests are
stable across runs.

Each patient is shaped exactly like SAMPLE_PATIENT_WEB (the flat fields the
Planner's 7 tabs consume), so the same form-population path works unchanged.
"""

from __future__ import annotations

import datetime
from typing import Optional

# ── Demographic pools ─────────────────────────────────────────────────────────

_FIRST_M = ["James", "Robert", "Miguel", "David", "Hector", "William", "Joseph",
            "Charles", "Raymond", "Frank", "Carlos", "George", "Walter", "Henry",
            "Arthur", "Eugene", "Samuel", "Leonard", "Vernon", "Stanley"]
_FIRST_F = ["Maria", "Dorothy", "Linda", "Patricia", "Barbara", "Susan", "Margaret",
            "Carmen", "Helen", "Ruth", "Gloria", "Joan", "Evelyn", "Rosa", "Lucille",
            "Beatrice", "Mabel", "Yolanda", "Thelma", "Estelle"]
_LAST = ["Mitchell", "Gonzalez", "Nguyen", "Johnson", "Patel", "Kim", "Rodriguez",
         "Williams", "Chen", "Garcia", "Brown", "Lopez", "Davis", "Martinez",
         "Wilson", "Anderson", "Tran", "Thomas", "Hernandez", "Lee", "Walker",
         "Robinson", "Reyes", "Young", "Singh", "Flores", "Carter", "Ramirez",
         "Cohen", "Okafor", "Petrov", "Hagopian", "Ahmadi", "Wong", " Portillo".strip(),
         "Delgado", "Sanchez", "Murphy", "Foster", "Castillo"]

_LANGS = [
    ("English", "English; reads at high-school level"),
    ("English", "English; low health literacy — teach-back required"),
    ("Spanish", "Spanish-preferred; limited English — qualified interpreter required"),
    ("Mandarin", "Mandarin-preferred; limited English — interpreter + translated materials"),
    ("Vietnamese", "Vietnamese-preferred; daughter often interprets (use qualified interpreter for consent)"),
    ("Tagalog", "Tagalog-preferred; conversational English"),
    ("Korean", "Korean-preferred; limited English — interpreter required"),
    ("Russian", "Russian-preferred; limited English"),
    ("Armenian", "Western Armenian-preferred; interpreter required"),
    ("Farsi", "Farsi-preferred; limited English"),
]

_INSURANCE = [
    ("Medicare Part A & B (Traditional)", "AARP Medigap Plan G — UnitedHealthcare", "Yes", 0),
    ("Medicare Advantage HMO — Humana Gold Plus", "None", "Yes (via MA plan)", 0),
    ("Medicare Advantage PPO — Aetna", "None", "Yes (via MA plan)", 12),
    ("Medicare Part A & B (Traditional)", "Medi-Cal (dual-eligible)", "Yes", 0),
    ("Medi-Cal Managed Care — Health Net", "None", "No", 0),
    ("Commercial PPO — Blue Shield of California", "None", "No", 0),
    ("Commercial HMO — Kaiser Permanente", "None", "No", 0),
    ("Medicare Part A & B (Traditional)", "Anthem Blue Cross Medigap Plan N", "Yes", 20),
    ("Medicare Advantage HMO — SCAN Health Plan", "None", "Yes (via MA plan)", 40),
    ("Medi-Cal (full scope) — L.A. Care", "None", "No", 0),
]

_LIVING = [
    "Lives alone in a single-story apartment",
    "Lives with spouse (also elderly, limited mobility) in a two-story home",
    "Lives with adult daughter and her family; daughter works full-time",
    "Lives alone in a second-floor walk-up (no elevator, 14 steps)",
    "Lives with spouse who is the primary caregiver",
    "Resided in an assisted-living facility prior to admission",
    "Lives alone; estranged from family; relies on neighbor",
    "Lives with adult son; son has variable work schedule",
    "Currently unhoused; was staying in a shelter before admission",
    "Lives with spouse in a senior mobile-home community",
]

_CAREGIVER = [
    "Daughter (lives 10 min away) — available evenings/weekends",
    "Spouse — willing but limited by own health conditions",
    "Son — can take 1 week off work for transition",
    "No reliable caregiver identified — lives alone",
    "Hired part-time caregiver 4 hrs/day (private pay)",
    "Granddaughter — primary contact, lives out of state, coordinates by phone",
    "Niece — available weekdays, works from home",
    "Assisted-living facility staff",
    "Case-managed through county social services; no family caregiver",
    "Neighbor provides limited assistance (meals, transport)",
]

_HOUSING = ["House (single-story)", "House (two-story)", "Apartment (elevator building)",
            "Apartment (2nd-floor walk-up)", "Senior independent living", "Assisted living",
            "Mobile home", "Shelter / transitional housing"]

_BEDROOM = ["First floor", "Second floor (stairs required)", "Ground floor near bathroom",
            "Upstairs — bathroom on main floor only", "Studio (single room)"]

_TRANSPORT = [
    "Family will provide transportation to follow-up appointments",
    "No personal/family transportation — needs medical transport or paratransit referral",
    "Drives self (cleared) — independent",
    "Uses Access paratransit; rides must be booked 1 day ahead",
    "Relies on rideshare/taxi vouchers via health plan",
    "Public bus only — limited mobility makes this difficult",
]

# ── Clinical scenario archetypes (rich, discharge-relevant) ────────────────────

_SCENARIOS = [
    {
        "specialty": "Cardiology",
        "los": 4,
        "primary": ("Acute decompensated heart failure (HFrEF), EF 30% — orthopnea, "
                    "DOE, 2+ pitting edema; net -10 lbs after IV diuresis"),
        "secondary": ["Type 2 diabetes mellitus — insulin during admission",
                      "Hypertension", "CKD stage 3 (baseline Cr 1.6)",
                      "Atrial fibrillation — rate-controlled, anticoagulated",
                      "Hyperlipidemia"],
        "adm_meds": ["Lisinopril 20 mg PO daily", "Metoprolol succinate 50 mg PO daily",
                     "Furosemide 40 mg PO daily", "Apixaban 5 mg PO BID",
                     "Atorvastatin 40 mg PO nightly", "Metformin 1000 mg PO BID"],
        "inp_meds": ["Furosemide 40 mg IV BID (diuresis)", "Insulin sliding scale",
                     "Enoxaparin 40 mg SC daily (prophylaxis held — on apixaban)"],
        "dis_meds": ["Sacubitril/valsartan 49/51 mg PO BID (NEW — replaces lisinopril)",
                     "Metoprolol succinate 50 mg PO daily",
                     "Furosemide 40 mg PO daily", "Spironolactone 25 mg PO daily (NEW)",
                     "Apixaban 5 mg PO BID", "Atorvastatin 40 mg PO nightly",
                     "Empagliflozin 10 mg PO daily (NEW — HF + T2DM)"],
        "pt": "Ambulates 150 ft with rolling walker, contact-guard assist; stairs not yet assessed.",
        "ot": "Modified-independent with ADLs; needs energy-conservation education for HF.",
        "st": "Not indicated — no dysphagia or cognitive concerns.",
        "notes": ("Daily weights and 2g sodium / 2L fluid restriction taught. HFrEF GDMT "
                  "up-titrated. Needs BMP within 3-5 days (K+/Cr on new spironolactone + ARNI). "
                  "High 30-day readmission risk — qualifies for HF transitions program."),
        "goals": ("Home with home-health nursing + PT; cardiology follow-up within 7 days; "
                  "BMP in 3-5 days; daily-weight log; HF education reinforcement."),
    },
    {
        "specialty": "Pulmonology",
        "los": 5,
        "primary": ("Acute exacerbation of COPD (GOLD D) with acute hypercapnic respiratory "
                    "failure — required BiPAP; now weaned to 2L NC"),
        "secondary": ["Tobacco use disorder (40 pack-years, still smoking)",
                      "Cor pulmonale", "Obstructive sleep apnea (nonadherent to CPAP)",
                      "Anxiety", "Malnutrition (BMI 18.4)"],
        "adm_meds": ["Tiotropium 18 mcg INH daily", "Albuterol INH PRN",
                     "Sertraline 50 mg PO daily"],
        "inp_meds": ["Prednisone 40 mg PO daily (5-day burst)", "Azithromycin 500 mg IV x3",
                     "Duoneb q6h scheduled", "BiPAP overnight"],
        "dis_meds": ["Prednisone taper (40→0 over 10 days)",
                     "Tiotropium 18 mcg INH daily", "Budesonide/formoterol 160/4.5 INH BID (NEW)",
                     "Albuterol INH PRN", "Sertraline 50 mg PO daily",
                     "Home O2 2L NC continuous (NEW — qualifies, SpO2 87% RA)"],
        "pt": "Ambulates 100 ft with O2 and rolling walker; desaturates to 86% on exertion.",
        "ot": "Needs energy conservation + home O2 safety training; modified-independent ADLs.",
        "st": "Not indicated.",
        "notes": ("New home oxygen — DME setup and safety teaching required before discharge. "
                  "Smoking-cessation counseling provided; pulmonary rehab referral placed. "
                  "Inhaler technique teach-back completed."),
        "goals": ("Home with home-health + home O2; pulmonology follow-up within 1 week; "
                  "pulmonary rehab; smoking cessation; CPAP re-fitting."),
    },
    {
        "specialty": "Neurology / Stroke",
        "los": 6,
        "primary": ("Acute ischemic stroke — left MCA territory; received IV thrombolysis; "
                    "residual right-sided weakness and expressive aphasia"),
        "secondary": ["Hypertension (poorly controlled, presenting BP 198/104)",
                      "Atrial fibrillation (new diagnosis)", "Hyperlipidemia",
                      "Type 2 diabetes mellitus", "Dysphagia (post-stroke)"],
        "adm_meds": ["Amlodipine 5 mg PO daily", "Atorvastatin 20 mg PO nightly"],
        "inp_meds": ["Alteplase (administered in ED)", "Telemetry",
                     "Insulin sliding scale", "VTE prophylaxis — SCDs"],
        "dis_meds": ["Apixaban 5 mg PO BID (NEW — AFib + stroke)",
                     "Atorvastatin 80 mg PO nightly (high-intensity)",
                     "Amlodipine 10 mg PO daily", "Lisinopril 10 mg PO daily (NEW)",
                     "Metformin 500 mg PO BID"],
        "pt": "Requires moderate assist for transfers; ambulates 50 ft with hemi-walker + 1 assist.",
        "ot": "Max assist for UE dressing/grooming due to R hemiparesis; home eval recommended.",
        "st": "Moderate expressive aphasia; dysphagia — nectar-thick liquids, soft diet; aspiration precautions.",
        "notes": ("Acute inpatient rehab (IRF) recommended — tolerates 3 hrs therapy/day. "
                  "Modified diet + aspiration precautions; family trained on safe-swallow. "
                  "New AFib — anticoagulation started; carotid imaging done."),
        "goals": ("Discharge to acute inpatient rehabilitation (IRF); continue anticoagulation; "
                  "BP goal <130/80; SLP + PT/OT; dysphagia diet."),
    },
    {
        "specialty": "Orthopedic Surgery",
        "los": 3,
        "primary": ("Status post right hip ORIF for intertrochanteric femur fracture "
                    "(mechanical fall at home); weight-bearing as tolerated"),
        "secondary": ["Osteoporosis (untreated)", "Hypertension",
                      "Mild cognitive impairment", "Vitamin D deficiency",
                      "History of recurrent falls"],
        "adm_meds": ["Hydrochlorothiazide 25 mg PO daily", "Donepezil 5 mg PO nightly"],
        "inp_meds": ["Enoxaparin 40 mg SC daily (VTE prophylaxis)",
                     "Acetaminophen 1g PO q8h scheduled", "Oxycodone 5 mg PO q6h PRN",
                     "Senna/docusate"],
        "dis_meds": ["Enoxaparin 40 mg SC daily x 28 days (NEW — post-op VTE)",
                     "Acetaminophen 1g PO q8h", "Oxycodone 5 mg PO q6h PRN (taper)",
                     "Calcium + vitamin D (NEW)", "Alendronate 70 mg PO weekly (NEW — osteoporosis)",
                     "Hydrochlorothiazide 25 mg PO daily"],
        "pt": "Transfers with min assist; ambulates 75 ft with front-wheel walker; stairs not cleared.",
        "ot": "Needs assist with lower-body dressing/bathing; DME (raised toilet seat, tub bench) recommended.",
        "st": "Not indicated.",
        "notes": ("SNF placement recommended for short-term rehab — lives alone, stairs to "
                  "bedroom, fall risk. Fall-prevention + home-safety evaluation needed. "
                  "Osteoporosis treatment initiated."),
        "goals": ("Discharge to SNF for rehab (Medicare 3-midnight criteria met); VTE prophylaxis x28d; "
                  "fall-prevention program; outpatient ortho follow-up in 2 weeks."),
    },
    {
        "specialty": "Hospitalist / Infectious Disease",
        "los": 7,
        "primary": ("Sepsis secondary to community-acquired pneumonia (right lower lobe) — "
                    "resolved with IV antibiotics; completing course"),
        "secondary": ["Type 2 diabetes mellitus (HbA1c 9.4%)",
                      "Acute kidney injury (resolving, Cr 1.4 from peak 2.6)",
                      "Deconditioning", "Hypertension", "Anemia of inflammation"],
        "adm_meds": ["Metformin 1000 mg PO BID", "Lisinopril 20 mg PO daily"],
        "inp_meds": ["Ceftriaxone 1g IV daily", "Azithromycin 500 mg IV daily",
                     "IV fluids", "Insulin sliding scale (metformin held — AKI)"],
        "dis_meds": ["Amoxicillin/clavulanate 875 mg PO BID x 4 more days",
                     "Insulin glargine 10 units SC nightly (NEW — A1c 9.4, metformin held)",
                     "Lisinopril 10 mg PO daily (reduced — AKI)", "Aspirin 81 mg PO daily"],
        "pt": "Ambulates 200 ft with rolling walker, supervision; significant deconditioning.",
        "ot": "Modified-independent ADLs; recommends home-health for endurance.",
        "st": "Not indicated.",
        "notes": ("Finish oral antibiotics; recheck BMP in 1 week (AKI, ACE-I). New insulin — "
                  "diabetes teaching + glucometer provided, teach-back done. Pneumococcal and "
                  "influenza vaccines given."),
        "goals": ("Home with home-health nursing + PT; PCP follow-up in 5-7 days; BMP recheck; "
                  "diabetes education; complete antibiotic course."),
    },
    {
        "specialty": "Cardiothoracic Surgery",
        "los": 6,
        "primary": ("Status post 3-vessel CABG for severe CAD (presented with NSTEMI); "
                    "sternal precautions in place"),
        "secondary": ["Coronary artery disease", "Hypertension", "Hyperlipidemia",
                      "Type 2 diabetes mellitus", "Postoperative atrial fibrillation (resolved)"],
        "adm_meds": ["Aspirin 81 mg PO daily", "Atorvastatin 40 mg PO nightly",
                     "Metoprolol tartrate 25 mg PO BID"],
        "inp_meds": ["Aspirin 81 mg", "Amiodarone (post-op AFib, completed)",
                     "Insulin", "Acetaminophen + oxycodone PRN", "Furosemide IV (post-op)"],
        "dis_meds": ["Aspirin 81 mg PO daily", "Atorvastatin 80 mg PO nightly",
                     "Metoprolol succinate 50 mg PO daily", "Lisinopril 5 mg PO daily (NEW)",
                     "Furosemide 20 mg PO daily x 7 days", "Oxycodone 5 mg PO q6h PRN (taper)",
                     "Metformin 500 mg PO BID"],
        "pt": "Ambulates 250 ft independently; sternal precautions limit UE use; no lifting >5 lbs.",
        "ot": "Independent ADLs within sternal precautions; needs adaptive technique training.",
        "st": "Not indicated.",
        "notes": ("Sternal precautions x 6-8 weeks; cardiac rehab referral placed. Incision "
                  "care taught. Lives with spouse who can assist. Strong rehab candidate for home."),
        "goals": ("Home with home-health; cardiac rehab; CT surgery follow-up in 1-2 weeks; "
                  "sternal precaution adherence; wound monitoring."),
    },
    {
        "specialty": "Nephrology",
        "los": 5,
        "primary": ("End-stage renal disease — initiated on hemodialysis this admission "
                    "(new tunneled catheter); volume overload resolved"),
        "secondary": ["Diabetic nephropathy", "Hypertension (renovascular)",
                      "Anemia of CKD", "Secondary hyperparathyroidism",
                      "Hyperkalemia (resolved)"],
        "adm_meds": ["Insulin glargine 20 units nightly", "Amlodipine 10 mg PO daily",
                     "Carvedilol 12.5 mg PO BID"],
        "inp_meds": ["Hemodialysis (3x this week)", "Sevelamer with meals",
                     "Insulin", "Sodium polystyrene (acute hyperkalemia)"],
        "dis_meds": ["Sevelamer 800 mg PO TID with meals (NEW — phosphate binder)",
                     "Calcitriol 0.25 mcg PO daily (NEW)", "Amlodipine 10 mg PO daily",
                     "Carvedilol 12.5 mg PO BID", "Insulin glargine 16 units nightly (reduced)",
                     "Epoetin alfa per dialysis unit"],
        "pt": "Ambulates independently; mild fatigue post-dialysis.",
        "ot": "Independent ADLs; needs renal-diet + catheter-care education.",
        "st": "Not indicated.",
        "notes": ("Outpatient dialysis chair secured (MWF schedule). Renal/diabetic diet "
                  "and catheter-care taught. Coordinate transport to dialysis. Fistula "
                  "placement referral pending."),
        "goals": ("Home with outpatient hemodialysis MWF; nephrology + access surgery follow-up; "
                  "renal diet; reliable dialysis transport; medication reconciliation."),
    },
    {
        "specialty": "Gastroenterology",
        "los": 4,
        "primary": ("Upper GI bleed from gastric ulcer — endoscopic clipping; hemodynamically "
                    "stable, Hgb stabilized at 8.6 after 2 units PRBC"),
        "secondary": ["H. pylori positive", "Chronic NSAID use (for osteoarthritis)",
                      "Coronary artery disease (on aspirin — held)",
                      "Cirrhosis (compensated, Child-Pugh A)", "Iron-deficiency anemia"],
        "adm_meds": ["Aspirin 81 mg PO daily (HELD)", "Naproxen 500 mg PO BID (DISCONTINUED)"],
        "inp_meds": ["Pantoprazole 40 mg IV BID", "2 units PRBC transfused",
                     "IV fluids", "Octreotide (held — non-variceal)"],
        "dis_meds": ["Pantoprazole 40 mg PO BID x 8 weeks",
                     "H. pylori triple therapy (amoxicillin + clarithromycin + PPI) x 14 days (NEW)",
                     "Ferrous sulfate 325 mg PO daily (NEW)", "Acetaminophen for pain (NSAIDs stopped)",
                     "Aspirin — hold, GI/cardiology to coordinate restart"],
        "pt": "Ambulates independently; no mobility deficits.",
        "ot": "Independent ADLs.",
        "st": "Not indicated.",
        "notes": ("STOP all NSAIDs — counseled. Aspirin restart timing to be coordinated by "
                  "cardiology/GI. Repeat EGD in 8 weeks to confirm ulcer healing. Hgb recheck "
                  "in 1 week. Alcohol-cessation counseling (cirrhosis)."),
        "goals": ("Home; GI follow-up + repeat EGD in 8 weeks; CBC in 1 week; NSAID avoidance "
                  "education; complete H. pylori therapy."),
    },
    {
        "specialty": "Endocrinology",
        "los": 4,
        "primary": ("Diabetic ketoacidosis (new-onset insulin requirement) — resolved on IV "
                    "insulin drip; transitioned to subcutaneous regimen"),
        "secondary": ["Type 2 diabetes mellitus (previously diet-controlled)",
                      "Hypertriglyceridemia", "Obesity (BMI 36)",
                      "Hypertension", "Depression"],
        "adm_meds": ["Metformin 1000 mg PO BID", "Lisinopril 10 mg PO daily",
                     "Fluoxetine 20 mg PO daily"],
        "inp_meds": ["IV insulin drip → transitioned", "IV fluids + electrolyte repletion",
                     "Metformin held"],
        "dis_meds": ["Insulin glargine 24 units SC nightly (NEW)",
                     "Insulin lispro sliding scale with meals (NEW)", "Metformin 1000 mg PO BID",
                     "Lisinopril 10 mg PO daily", "Atorvastatin 20 mg PO nightly (NEW)",
                     "Fluoxetine 20 mg PO daily"],
        "pt": "Independent; no mobility deficit.",
        "ot": "Independent ADLs; requires extensive new-insulin self-management training.",
        "st": "Not indicated.",
        "notes": ("Brand-new insulin user — comprehensive diabetes education, glucometer, and "
                  "injection teach-back completed; sharps disposal reviewed. Endocrinology + "
                  "diabetes-educator follow-up arranged. Insulin copay assistance applied."),
        "goals": ("Home; endocrinology + CDE follow-up within 1 week; glucose log; "
                  "insulin affordability resolved; PCP follow-up."),
    },
    {
        "specialty": "Hospitalist / Wound Care",
        "los": 5,
        "primary": ("Lower-extremity cellulitis with abscess (diabetic foot) — I&D performed; "
                    "completing IV antibiotics; wound vac in place"),
        "secondary": ["Type 2 diabetes mellitus (poorly controlled)",
                      "Peripheral arterial disease", "Diabetic peripheral neuropathy",
                      "Chronic non-healing foot ulcer", "Obesity"],
        "adm_meds": ["Metformin 1000 mg PO BID", "Gabapentin 300 mg PO TID",
                     "Aspirin 81 mg PO daily"],
        "inp_meds": ["Vancomycin IV", "Piperacillin/tazobactam IV", "Insulin sliding scale",
                     "Wound vac (NPWT)"],
        "dis_meds": ["Cephalexin 500 mg PO QID x 7 days", "Insulin glargine 18 units nightly (NEW)",
                     "Metformin 1000 mg PO BID", "Gabapentin 300 mg PO TID",
                     "Aspirin 81 mg PO daily", "Cilostazol 100 mg PO BID (NEW — PAD)"],
        "pt": "Non-weight-bearing on affected foot; ambulates with walker, contact-guard assist.",
        "ot": "Needs offloading + wound-care education; modified-independent ADLs.",
        "st": "Not indicated.",
        "notes": ("Wound vac requires home-health wound nursing 3x/week. Strict offloading. "
                  "Vascular surgery + podiatry follow-up. Diabetic foot-care education. "
                  "High risk for amputation if non-adherent."),
        "goals": ("Home with home-health wound care (NPWT); vascular + podiatry follow-up; "
                  "glycemic control; offloading footwear; complete antibiotics."),
    },
    {
        "specialty": "Oncology",
        "los": 6,
        "primary": ("Newly diagnosed metastatic colon adenocarcinoma — admitted for malignant "
                    "bowel obstruction, now resolved; goals-of-care discussion initiated"),
        "secondary": ["Cancer-related malnutrition", "Cancer-associated VTE (new DVT)",
                      "Anemia", "Cancer pain", "Depression/adjustment reaction"],
        "adm_meds": ["Acetaminophen PRN"],
        "inp_meds": ["NG decompression (removed)", "IV fluids + TPN trial",
                     "Enoxaparin (new DVT)", "Opioid analgesia titration"],
        "dis_meds": ["Enoxaparin 1 mg/kg SC BID (NEW — cancer-associated VTE)",
                     "Extended-release morphine 15 mg PO BID + IR for breakthrough (NEW)",
                     "Ondansetron 8 mg PO q8h PRN", "Senna/docusate (opioid bowel regimen)",
                     "Mirtazapine 15 mg PO nightly (appetite + mood)"],
        "pt": "Ambulates 100 ft with supervision; fatigue-limited.",
        "ot": "Modified-independent; energy conservation + adaptive equipment.",
        "st": "Not indicated.",
        "notes": ("Outpatient oncology established; palliative-care co-management. Goals-of-care "
                  "and advance-directive discussion ongoing — patient leaning toward home with "
                  "support. Anticoagulation for cancer VTE. Symptom management priority."),
        "goals": ("Home with home-health + outpatient palliative care; oncology consult within "
                  "1 week; symptom control; advance-care planning; caregiver support."),
    },
    {
        "specialty": "Pulmonology / Critical Care",
        "los": 9,
        "primary": ("Respiratory failure due to COVID-19 pneumonia — extubated after 4 days on "
                    "ventilator; now on 3L NC; profound ICU-acquired weakness"),
        "secondary": ["ICU-acquired weakness / critical-illness myopathy",
                      "Post-intubation dysphagia", "Delirium (resolving)",
                      "Type 2 diabetes mellitus (steroid-induced hyperglycemia)",
                      "Pressure injury, sacral stage 2"],
        "adm_meds": ["Amlodipine 5 mg PO daily"],
        "inp_meds": ["Dexamethasone 6 mg daily (completed)", "Remdesivir (completed)",
                     "Insulin (steroid hyperglycemia)", "Heparin SC prophylaxis"],
        "dis_meds": ["Insulin glargine 12 units nightly (NEW — taper as steroids stop)",
                     "Amlodipine 5 mg PO daily", "Vitamin C + zinc",
                     "Home O2 3L NC (NEW)", "Acetaminophen PRN"],
        "pt": "Max assist for transfers; ambulates 25 ft with walker + 2 assist; severe deconditioning.",
        "ot": "Dependent for most ADLs; needs intensive rehab.",
        "st": "Post-extubation dysphagia — pureed diet, honey-thick liquids; aspiration precautions.",
        "notes": ("Recommend acute inpatient rehab or high-level SNF — requires intensive PT/OT/SLP. "
                  "Home O2, sacral wound care, modified diet. Family education on transfers. "
                  "Post-ICU syndrome counseling."),
        "goals": ("Discharge to SNF/IRF for intensive rehab; home O2; wound + dysphagia management; "
                  "wean steroids/insulin; pulmonology follow-up."),
    },
    {
        "specialty": "Psychiatry / Medicine",
        "los": 5,
        "primary": ("Decompensated alcohol use disorder with withdrawal (CIWA-managed) and "
                    "alcoholic hepatitis; medically stabilized"),
        "secondary": ["Alcoholic cirrhosis (Child-Pugh B)", "Thiamine deficiency",
                      "Major depressive disorder", "Hypertension",
                      "Thrombocytopenia", "Homelessness / housing instability"],
        "adm_meds": ["None reported (poor access)"],
        "inp_meds": ["Lorazepam per CIWA protocol", "Thiamine 500 mg IV TID then PO",
                     "Folate + multivitamin", "IV fluids"],
        "dis_meds": ["Thiamine 100 mg PO daily", "Folic acid 1 mg PO daily",
                     "Multivitamin daily", "Naltrexone 50 mg PO daily (NEW — AUD)",
                     "Spironolactone 50 mg PO daily (NEW — cirrhosis)",
                     "Sertraline 50 mg PO daily (NEW — depression)"],
        "pt": "Ambulates independently; mild gait unsteadiness.",
        "ot": "Independent ADLs.",
        "st": "Not indicated.",
        "notes": ("Complex disposition — patient is unhoused. Social work engaged for respite/"
                  "shelter placement and substance-use treatment referral (IOP). Strong "
                  "candidate for medical respite. Hepatology follow-up. Relapse-prevention plan."),
        "goals": ("Discharge to medical respite/shelter with case management; SUD treatment (IOP); "
                  "hepatology follow-up; benefits enrollment; MAT for AUD."),
    },
    {
        "specialty": "Vascular Surgery",
        "los": 4,
        "primary": ("Status post right below-knee amputation for non-salvageable diabetic foot "
                    "infection; residual limb healing well"),
        "secondary": ["Type 2 diabetes mellitus", "Peripheral arterial disease",
                      "Coronary artery disease", "Chronic kidney disease stage 3",
                      "Phantom limb pain"],
        "adm_meds": ["Insulin glargine 22 units nightly", "Aspirin 81 mg PO daily",
                     "Atorvastatin 40 mg PO nightly", "Lisinopril 10 mg PO daily"],
        "inp_meds": ["IV antibiotics (completed)", "Insulin", "Opioid analgesia",
                     "Gabapentin (phantom pain)", "Enoxaparin prophylaxis"],
        "dis_meds": ["Insulin glargine 22 units nightly", "Aspirin 81 mg PO daily",
                     "Atorvastatin 40 mg PO nightly", "Lisinopril 10 mg PO daily",
                     "Gabapentin 300 mg PO TID (phantom limb pain)",
                     "Oxycodone 5 mg PO q6h PRN (taper)", "Cilostazol 100 mg PO BID"],
        "pt": "Transfers with min assist; wheelchair-level mobility; pre-prosthetic training started.",
        "ot": "Needs home accessibility eval + adaptive equipment; modified-independent UE ADLs.",
        "st": "Not indicated.",
        "notes": ("SNF for prosthetic rehab and residual-limb care recommended. Home is not "
                  "wheelchair-accessible (steps, narrow doorways) — accessibility modifications "
                  "needed. Prosthetics referral. Diabetic foot-care for contralateral limb."),
        "goals": ("Discharge to SNF for pre-prosthetic rehab; residual-limb care; home "
                  "accessibility modifications; vascular + prosthetics follow-up."),
    },
    {
        "specialty": "Geriatrics",
        "los": 4,
        "primary": ("Urosepsis from complicated UTI with acute delirium superimposed on dementia; "
                    "infection treated, sensorium improving toward baseline"),
        "secondary": ["Major neurocognitive disorder (Alzheimer's, moderate)",
                      "Recurrent UTIs", "Failure to thrive / weight loss",
                      "Polypharmacy", "History of falls"],
        "adm_meds": ["Donepezil 10 mg PO nightly", "Memantine 10 mg PO BID",
                     "Tamsulosin 0.4 mg PO daily", "Mirtazapine 7.5 mg PO nightly"],
        "inp_meds": ["Ceftriaxone IV → PO", "IV fluids", "Avoided anticholinergics/benzodiazepines",
                     "Melatonin for sleep-wake"],
        "dis_meds": ["Cefpodoxime 200 mg PO BID x 4 more days", "Donepezil 10 mg PO nightly",
                     "Memantine 10 mg PO BID", "Mirtazapine 7.5 mg PO nightly",
                     "Vitamin D + calcium", "Deprescribed: tamsulosin continued, sedatives avoided"],
        "pt": "Ambulates 100 ft with rolling walker + supervision; high fall risk.",
        "ot": "Needs cueing for ADLs; caregiver training essential.",
        "st": "Mild dysphagia with pills — crush-compatible meds reviewed; cognitive-communication deficits.",
        "notes": ("Caregiver burden high — daughter overwhelmed. Recommend home-health + adult "
                  "day program; evaluate for higher level of care if caregiver support insufficient. "
                  "Delirium-prevention strategies taught. Goals-of-care/advance-directive review."),
        "goals": ("Home with home-health + caregiver support (vs assisted living if needed); "
                  "delirium prevention; fall precautions; deprescribing; geriatrics follow-up."),
    },
    {
        "specialty": "Obstetrics / Medicine",
        "los": 3,
        "primary": ("Postpartum preeclampsia with severe features (readmitted day 5 postpartum) — "
                    "BP controlled, no end-organ progression"),
        "secondary": ["Gestational hypertension", "Postpartum anemia",
                      "Cesarean section (POD 5, incision healing)", "Anxiety",
                      "First-time parent — limited support"],
        "adm_meds": ["Prenatal vitamin", "Ferrous sulfate 325 mg PO daily"],
        "inp_meds": ["Labetalol IV → PO", "Magnesium sulfate (seizure prophylaxis, 24h)",
                     "Ibuprofen + acetaminophen", "Ferrous sulfate"],
        "dis_meds": ["Labetalol 200 mg PO BID (NEW)", "Nifedipine ER 30 mg PO daily (NEW)",
                     "Ferrous sulfate 325 mg PO daily", "Ibuprofen 600 mg PO q6h PRN",
                     "Acetaminophen 1g PO q6h PRN", "Prenatal vitamin daily"],
        "pt": "Independent; no deficits.",
        "ot": "Independent ADLs; newborn-care + self-care education.",
        "st": "Not indicated.",
        "notes": ("Home BP monitoring with cuff provided; strict return precautions for headache/"
                  "vision changes/RUQ pain taught. OB follow-up in 3-5 days for BP check. "
                  "Lactation + newborn-care support; postpartum depression screening."),
        "goals": ("Home with home BP monitoring; OB follow-up in 3-5 days; preeclampsia return "
                  "precautions; lactation support; PPD screening."),
    },
]

_BASE_DATE = datetime.date(2026, 5, 1)


def _patient(idx: int) -> dict:
    sc = _SCENARIOS[idx % len(_SCENARIOS)]
    female = (idx % 2 == 0)
    first = (_FIRST_F if female else _FIRST_M)[(idx * 7) % 20]
    last = _LAST[(idx * 3) % len(_LAST)]
    name = f"{first} {last}"
    gender = "Female" if female else "Male"
    age = 52 + ((idx * 5) % 44)  # 52–95
    dob = datetime.date(_BASE_DATE.year - age, 1 + (idx % 12), 1 + (idx % 27))
    adm = _BASE_DATE + datetime.timedelta(days=(idx * 2) % 30)
    disc = adm + datetime.timedelta(days=sc["los"])
    lang, lang_note = _LANGS[idx % len(_LANGS)]
    pri_ins, sec_ins, part_a, snf_used = _INSURANCE[idx % len(_INSURANCE)]

    return {
        "id": f"{idx + 1:03d}",
        # Section 1 — Demographics
        "patient_name": name,
        "age": str(age),
        "gender": gender,
        "mrn": f"SP-{2026000 + idx}",
        "admission_date": adm.isoformat(),
        "expected_discharge_date": disc.isoformat(),
        "attending_physician": f"Dr. {_LAST[(idx * 5) % len(_LAST)]}, MD — {sc['specialty']}",
        # Section 2 — Diagnoses
        "primary_diagnosis": sc["primary"],
        "secondary_diagnoses": "\n".join(sc["secondary"]),
        "additional_clinical_notes": sc["notes"],
        # Section 3 — Insurance
        "primary_insurance": pri_ins,
        "secondary_insurance": sec_ins,
        "medicare_part_a": part_a,
        "snf_days_used": str(snf_used),
        # Section 4 — Medications
        "admission_medications": "\n".join(sc["adm_meds"]),
        "inpatient_medications": "\n".join(sc["inp_meds"]),
        "discharge_medications": "\n".join(sc["dis_meds"]),
        # Section 5 — Therapy
        "pt_evaluation": sc["pt"],
        "ot_evaluation": sc["ot"],
        "st_evaluation": sc["st"],
        # Section 6 — Social history
        "living_situation": _LIVING[(idx * 3) % len(_LIVING)],
        "caregiver": _CAREGIVER[(idx * 7) % len(_CAREGIVER)],
        "primary_language": lang_note,
        "transportation": _TRANSPORT[(idx * 5) % len(_TRANSPORT)],
        "housing_type": _HOUSING[(idx * 3) % len(_HOUSING)],
        "bedroom_location": _BEDROOM[(idx * 2) % len(_BEDROOM)],
        # Section 7 — Goals
        "patient_family_preference": (
            f"Patient ({lang} preferred) and family discussed disposition. " + sc["goals"].split(";")[0] + "."
        ),
        "physician_goals": sc["goals"],
        "additional_notes": (
            f"Primary language: {lang_note}. Insurance: {pri_ins}"
            + (f"; secondary: {sec_ins}" if sec_ins and sec_ins != "None" else "")
            + ". All data synthetic — demonstration only."
        ),
    }


# Build the 100 patients once at import.
SAMPLE_PATIENTS: list[dict] = [_patient(i) for i in range(100)]
_BY_ID: dict[str, dict] = {p["id"]: p for p in SAMPLE_PATIENTS}


def list_sample_patients() -> list[dict]:
    """Lightweight list for the picker dropdown: id + label + short fields."""
    out = []
    for p in SAMPLE_PATIENTS:
        dx_short = p["primary_diagnosis"].split("—")[0].split("(")[0].strip()
        if len(dx_short) > 60:
            dx_short = dx_short[:57] + "…"
        out.append({
            "id": p["id"],
            "name": p["patient_name"],
            "age": p["age"],
            "gender": p["gender"],
            "dx_short": dx_short,
            "label": f"{p['id']} · {p['patient_name']} ({p['age']}{p['gender'][0]}) · {dx_short}",
        })
    return out


def get_sample_patient(pid: str) -> Optional[dict]:
    """Full form-shaped patient by id (e.g. '001'). Returns None if not found."""
    return _BY_ID.get(str(pid).zfill(3))
