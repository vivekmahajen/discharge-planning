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
import re
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

# ── Per-scenario structured clinical specifics (aligned to _SCENARIOS order) ────
# Adds the discharge-relevant structured data the rich record + Snapshot panel use:
# disposition, complexity, LACE/risk band, TCM eligibility, ICD-10, labs, vitals,
# allergy, functional status, DME, and follow-ups. Kept coherent with the scenario.
_CLIN = [
    {  # 0 CHF
        "dx_short": "CHF exacerbation (HFrEF)", "disposition": "Home with home health",
        "complexity": "high", "lace": 13, "risk_band": "high",
        "primary_icd10": "I50.21", "secondary_icd10": ["E11.9", "I10", "N18.3", "I48.91", "E78.5"],
        "labs": [{"test": "BNP", "value": "420", "unit": "pg/mL", "flag": "H"},
                 {"test": "Creatinine", "value": "1.8", "unit": "mg/dL", "flag": "H"},
                 {"test": "Potassium", "value": "3.9", "unit": "mEq/L", "flag": ""},
                 {"test": "HbA1c", "value": "7.9", "unit": "%", "flag": "H"}],
        "vitals": {"bp": "118/72", "hr": 74, "rr": 16, "spo2": 96, "temp": 98.4, "weight_kg": 94},
        "allergy": "Sulfa — rash", "functional": {"mobility": "Ambulates 150 ft w/ rolling walker, CGA",
            "fall_risk": "Moderate", "cognition": "Intact", "adls": "Modified independent"},
        "dme": ["Rolling walker", "Bedside commode", "Bathroom scale (daily weights)"],
        "follow_up": [{"with": "Cardiology", "when": "within 7 days"},
                      {"with": "PCP", "when": "within 5 days"}],
        "goals_of_care": "Full code",
    },
    {  # 1 COPD
        "dx_short": "COPD exacerbation w/ resp failure", "disposition": "Home with home health + home O2",
        "complexity": "high", "lace": 12, "risk_band": "high",
        "primary_icd10": "J44.1", "secondary_icd10": ["F17.210", "I27.81", "G47.33", "E66.9"],
        "labs": [{"test": "pCO2", "value": "58", "unit": "mmHg", "flag": "H"},
                 {"test": "pH", "value": "7.34", "unit": "", "flag": "L"},
                 {"test": "SpO2 (RA)", "value": "87", "unit": "%", "flag": "L"}],
        "vitals": {"bp": "132/80", "hr": 92, "rr": 22, "spo2": 90, "temp": 98.6, "weight_kg": 54},
        "allergy": "NKDA", "functional": {"mobility": "Ambulates 100 ft w/ O2, desats to 86% on exertion",
            "fall_risk": "Moderate", "cognition": "Intact", "adls": "Modified independent"},
        "dme": ["Home oxygen 2L concentrator + portable", "Rolling walker", "Pulse oximeter"],
        "follow_up": [{"with": "Pulmonology", "when": "within 1 week"},
                      {"with": "Pulmonary rehab intake", "when": "within 2 weeks"}],
        "goals_of_care": "Full code",
    },
    {  # 2 Stroke
        "dx_short": "Acute ischemic stroke (L MCA)", "disposition": "Inpatient rehab (IRF)",
        "complexity": "high", "lace": 14, "risk_band": "high",
        "primary_icd10": "I63.512", "secondary_icd10": ["I10", "I48.91", "E78.5", "E11.9", "R13.10"],
        "labs": [{"test": "LDL", "value": "142", "unit": "mg/dL", "flag": "H"},
                 {"test": "HbA1c", "value": "7.2", "unit": "%", "flag": "H"},
                 {"test": "INR", "value": "1.1", "unit": "", "flag": ""}],
        "vitals": {"bp": "150/88", "hr": 78, "rr": 18, "spo2": 97, "temp": 98.2, "weight_kg": 80},
        "allergy": "NKDA", "functional": {"mobility": "Ambulates 50 ft w/ hemi-walker + 1 assist",
            "fall_risk": "High", "cognition": "Expressive aphasia; alert", "adls": "Max assist (R hemiparesis)"},
        "dme": ["Hemi-walker", "Wheelchair", "Ankle-foot orthosis (pending)"],
        "follow_up": [{"with": "Neurology / Stroke clinic", "when": "within 2 weeks"},
                      {"with": "Anticoagulation clinic", "when": "within 1 week"}],
        "goals_of_care": "Full code",
    },
    {  # 3 Hip ORIF
        "dx_short": "Hip fracture s/p ORIF", "disposition": "Skilled nursing facility (SNF)",
        "complexity": "moderate", "lace": 11, "risk_band": "medium",
        "primary_icd10": "S72.141A", "secondary_icd10": ["M81.0", "I10", "G31.84", "E55.9", "Z91.81"],
        "labs": [{"test": "Hemoglobin", "value": "9.8", "unit": "g/dL", "flag": "L"},
                 {"test": "Vitamin D", "value": "18", "unit": "ng/mL", "flag": "L"},
                 {"test": "Calcium", "value": "8.9", "unit": "mg/dL", "flag": ""}],
        "vitals": {"bp": "128/76", "hr": 82, "rr": 16, "spo2": 97, "temp": 98.7, "weight_kg": 68},
        "allergy": "Codeine — nausea", "functional": {"mobility": "Transfers min assist; 75 ft w/ FWW; stairs not cleared",
            "fall_risk": "High", "cognition": "Mild impairment", "adls": "Assist w/ lower-body dressing/bathing"},
        "dme": ["Front-wheel walker", "Raised toilet seat", "Tub transfer bench"],
        "follow_up": [{"with": "Orthopedic surgery", "when": "in 2 weeks"},
                      {"with": "PCP", "when": "within 1 week of SNF discharge"}],
        "goals_of_care": "Full code",
    },
    {  # 4 Sepsis / PNA
        "dx_short": "Sepsis from pneumonia", "disposition": "Home with home health",
        "complexity": "moderate", "lace": 11, "risk_band": "medium",
        "primary_icd10": "A41.9", "secondary_icd10": ["J18.9", "E11.65", "N17.9", "I10"],
        "labs": [{"test": "WBC", "value": "8.2", "unit": "10^3/uL", "flag": ""},
                 {"test": "Lactate", "value": "1.4", "unit": "mmol/L", "flag": ""},
                 {"test": "Creatinine", "value": "1.4", "unit": "mg/dL", "flag": "H"},
                 {"test": "HbA1c", "value": "9.4", "unit": "%", "flag": "H"}],
        "vitals": {"bp": "124/74", "hr": 84, "rr": 18, "spo2": 95, "temp": 99.1, "weight_kg": 88},
        "allergy": "Penicillin — hives", "functional": {"mobility": "Ambulates 200 ft w/ walker, supervision",
            "fall_risk": "Moderate", "cognition": "Intact", "adls": "Modified independent"},
        "dme": ["Rolling walker", "Glucometer"],
        "follow_up": [{"with": "PCP", "when": "within 5-7 days"},
                      {"with": "Diabetes educator", "when": "within 1 week"}],
        "goals_of_care": "Full code",
    },
    {  # 5 CABG
        "dx_short": "s/p CABG x3 (NSTEMI)", "disposition": "Home with home health",
        "complexity": "moderate", "lace": 10, "risk_band": "medium",
        "primary_icd10": "I25.10", "secondary_icd10": ["I21.4", "I10", "E78.5", "E11.9"],
        "labs": [{"test": "Troponin", "value": "0.06", "unit": "ng/mL", "flag": ""},
                 {"test": "Hemoglobin", "value": "10.2", "unit": "g/dL", "flag": "L"},
                 {"test": "LDL", "value": "96", "unit": "mg/dL", "flag": "H"}],
        "vitals": {"bp": "122/70", "hr": 76, "rr": 16, "spo2": 96, "temp": 98.5, "weight_kg": 85},
        "allergy": "NKDA", "functional": {"mobility": "Ambulates 250 ft independent; sternal precautions",
            "fall_risk": "Low", "cognition": "Intact", "adls": "Independent within sternal precautions"},
        "dme": ["Front-wheel walker (transition)", "Incentive spirometer", "Heart pillow"],
        "follow_up": [{"with": "Cardiothoracic surgery", "when": "in 1-2 weeks"},
                      {"with": "Cardiac rehab intake", "when": "within 2 weeks"}],
        "goals_of_care": "Full code",
    },
    {  # 6 ESRD / HD
        "dx_short": "ESRD, new hemodialysis", "disposition": "Home with outpatient dialysis",
        "complexity": "high", "lace": 13, "risk_band": "high",
        "primary_icd10": "N18.6", "secondary_icd10": ["E11.22", "I12.0", "D63.1", "N25.81", "E87.5"],
        "labs": [{"test": "Creatinine", "value": "6.8", "unit": "mg/dL", "flag": "H"},
                 {"test": "Potassium", "value": "5.1", "unit": "mEq/L", "flag": "H"},
                 {"test": "Hemoglobin", "value": "9.1", "unit": "g/dL", "flag": "L"},
                 {"test": "Phosphorus", "value": "5.6", "unit": "mg/dL", "flag": "H"}],
        "vitals": {"bp": "146/86", "hr": 80, "rr": 16, "spo2": 97, "temp": 98.3, "weight_kg": 78},
        "allergy": "NKDA", "functional": {"mobility": "Ambulates independent; fatigued post-dialysis",
            "fall_risk": "Low", "cognition": "Intact", "adls": "Independent"},
        "dme": ["None — needs dialysis transport"],
        "follow_up": [{"with": "Nephrology", "when": "within 1 week"},
                      {"with": "Vascular access surgery (fistula)", "when": "within 2 weeks"}],
        "goals_of_care": "Full code",
    },
    {  # 7 GI bleed
        "dx_short": "Upper GI bleed (gastric ulcer)", "disposition": "Home (self-care)",
        "complexity": "moderate", "lace": 9, "risk_band": "medium",
        "primary_icd10": "K25.4", "secondary_icd10": ["B96.81", "I25.10", "K74.60", "D50.9"],
        "labs": [{"test": "Hemoglobin", "value": "8.6", "unit": "g/dL", "flag": "L"},
                 {"test": "Platelets", "value": "118", "unit": "10^3/uL", "flag": "L"},
                 {"test": "INR", "value": "1.3", "unit": "", "flag": ""}],
        "vitals": {"bp": "118/72", "hr": 88, "rr": 16, "spo2": 98, "temp": 98.2, "weight_kg": 72},
        "allergy": "NKDA", "functional": {"mobility": "Independent", "fall_risk": "Low",
            "cognition": "Intact", "adls": "Independent"},
        "dme": [],
        "follow_up": [{"with": "Gastroenterology (repeat EGD)", "when": "in 8 weeks"},
                      {"with": "PCP (CBC recheck)", "when": "within 1 week"}],
        "goals_of_care": "Full code",
    },
    {  # 8 DKA
        "dx_short": "DKA, new insulin requirement", "disposition": "Home (self-care)",
        "complexity": "moderate", "lace": 9, "risk_band": "medium",
        "primary_icd10": "E11.10", "secondary_icd10": ["E78.1", "E66.9", "I10", "F32.9"],
        "labs": [{"test": "Glucose", "value": "142", "unit": "mg/dL", "flag": "H"},
                 {"test": "Anion gap", "value": "10", "unit": "", "flag": ""},
                 {"test": "Bicarbonate", "value": "24", "unit": "mEq/L", "flag": ""},
                 {"test": "HbA1c", "value": "11.2", "unit": "%", "flag": "H"}],
        "vitals": {"bp": "126/78", "hr": 84, "rr": 16, "spo2": 99, "temp": 98.4, "weight_kg": 102},
        "allergy": "NKDA", "functional": {"mobility": "Independent", "fall_risk": "Low",
            "cognition": "Intact", "adls": "Independent"},
        "dme": ["Glucometer + test strips", "Sharps container"],
        "follow_up": [{"with": "Endocrinology", "when": "within 1 week"},
                      {"with": "Certified diabetes educator", "when": "within 1 week"}],
        "goals_of_care": "Full code",
    },
    {  # 9 Diabetic foot
        "dx_short": "Diabetic foot cellulitis + abscess", "disposition": "Home with home health (wound care)",
        "complexity": "high", "lace": 12, "risk_band": "high",
        "primary_icd10": "L03.115", "secondary_icd10": ["E11.621", "I73.9", "E11.42", "L97.509"],
        "labs": [{"test": "WBC", "value": "11.4", "unit": "10^3/uL", "flag": "H"},
                 {"test": "HbA1c", "value": "10.1", "unit": "%", "flag": "H"},
                 {"test": "ESR", "value": "62", "unit": "mm/hr", "flag": "H"}],
        "vitals": {"bp": "134/82", "hr": 88, "rr": 16, "spo2": 97, "temp": 99.0, "weight_kg": 96},
        "allergy": "NKDA", "functional": {"mobility": "Non-weight-bearing affected foot; walker CGA",
            "fall_risk": "High", "cognition": "Intact", "adls": "Modified independent"},
        "dme": ["Wound vac (NPWT)", "Knee scooter", "Offloading boot"],
        "follow_up": [{"with": "Vascular surgery", "when": "within 1 week"},
                      {"with": "Podiatry", "when": "within 1 week"}],
        "goals_of_care": "Full code",
    },
    {  # 10 Oncology
        "dx_short": "Metastatic colon cancer (bowel obstruction)", "disposition": "Home with home health + palliative",
        "complexity": "high", "lace": 13, "risk_band": "high",
        "primary_icd10": "C18.9", "secondary_icd10": ["C78.5", "I82.409", "D63.0", "G89.3", "R63.6"],
        "labs": [{"test": "Hemoglobin", "value": "9.4", "unit": "g/dL", "flag": "L"},
                 {"test": "Albumin", "value": "2.8", "unit": "g/dL", "flag": "L"},
                 {"test": "CEA", "value": "84", "unit": "ng/mL", "flag": "H"}],
        "vitals": {"bp": "112/68", "hr": 90, "rr": 18, "spo2": 96, "temp": 98.4, "weight_kg": 58},
        "allergy": "NKDA", "functional": {"mobility": "Ambulates 100 ft supervision; fatigue-limited",
            "fall_risk": "Moderate", "cognition": "Intact", "adls": "Modified independent"},
        "dme": ["Rolling walker", "Bedside commode", "Hospital bed (pending)"],
        "follow_up": [{"with": "Oncology", "when": "within 1 week"},
                      {"with": "Outpatient palliative care", "when": "within 1 week"}],
        "goals_of_care": "Full code (revisiting; leaning comfort-focused)",
    },
    {  # 11 COVID resp failure
        "dx_short": "COVID-19 resp failure, post-extubation", "disposition": "Skilled nursing facility (SNF)",
        "complexity": "high", "lace": 14, "risk_band": "high",
        "primary_icd10": "U07.1", "secondary_icd10": ["J96.01", "G72.81", "R13.10", "E11.65", "L89.152"],
        "labs": [{"test": "SpO2 (3L)", "value": "94", "unit": "%", "flag": ""},
                 {"test": "Glucose", "value": "168", "unit": "mg/dL", "flag": "H"},
                 {"test": "Albumin", "value": "2.6", "unit": "g/dL", "flag": "L"}],
        "vitals": {"bp": "120/72", "hr": 96, "rr": 22, "spo2": 93, "temp": 98.8, "weight_kg": 70},
        "allergy": "NKDA", "functional": {"mobility": "25 ft w/ walker + 2 assist; severe deconditioning",
            "fall_risk": "High", "cognition": "Resolving delirium", "adls": "Dependent for most ADLs"},
        "dme": ["Home oxygen 3L", "Wheelchair", "Hospital bed", "Sacral wound supplies"],
        "follow_up": [{"with": "Pulmonology", "when": "within 1-2 weeks"},
                      {"with": "Wound care", "when": "at SNF"}],
        "goals_of_care": "Full code",
    },
    {  # 12 AUD / cirrhosis
        "dx_short": "Alcohol withdrawal + alcoholic hepatitis", "disposition": "Medical respite / shelter",
        "complexity": "high", "lace": 12, "risk_band": "high",
        "primary_icd10": "F10.231", "secondary_icd10": ["K70.30", "E51.11", "F32.9", "I10", "D69.6"],
        "labs": [{"test": "AST", "value": "188", "unit": "U/L", "flag": "H"},
                 {"test": "ALT", "value": "92", "unit": "U/L", "flag": "H"},
                 {"test": "Platelets", "value": "96", "unit": "10^3/uL", "flag": "L"},
                 {"test": "INR", "value": "1.6", "unit": "", "flag": "H"}],
        "vitals": {"bp": "138/86", "hr": 98, "rr": 18, "spo2": 98, "temp": 98.6, "weight_kg": 64},
        "allergy": "NKDA", "functional": {"mobility": "Ambulates independent; mild gait unsteadiness",
            "fall_risk": "Moderate", "cognition": "Intact (CIWA resolved)", "adls": "Independent"},
        "dme": [],
        "follow_up": [{"with": "Hepatology", "when": "within 2 weeks"},
                      {"with": "Substance-use IOP intake", "when": "within 1 week"}],
        "goals_of_care": "Full code",
    },
    {  # 13 BKA
        "dx_short": "s/p right below-knee amputation", "disposition": "Skilled nursing facility (SNF)",
        "complexity": "high", "lace": 13, "risk_band": "high",
        "primary_icd10": "Z89.511", "secondary_icd10": ["E11.52", "I73.9", "I25.10", "N18.3", "G54.6"],
        "labs": [{"test": "Hemoglobin", "value": "10.0", "unit": "g/dL", "flag": "L"},
                 {"test": "HbA1c", "value": "8.6", "unit": "%", "flag": "H"},
                 {"test": "Creatinine", "value": "1.5", "unit": "mg/dL", "flag": "H"}],
        "vitals": {"bp": "130/78", "hr": 82, "rr": 16, "spo2": 97, "temp": 98.5, "weight_kg": 90},
        "allergy": "NKDA", "functional": {"mobility": "Transfers min assist; wheelchair-level; pre-prosthetic training",
            "fall_risk": "High", "cognition": "Intact", "adls": "Modified independent UE"},
        "dme": ["Wheelchair", "Slide board", "Residual-limb shrinker"],
        "follow_up": [{"with": "Vascular surgery", "when": "within 1-2 weeks"},
                      {"with": "Prosthetics", "when": "after residual-limb healing"}],
        "goals_of_care": "Full code",
    },
    {  # 14 Geriatric urosepsis / dementia
        "dx_short": "Urosepsis + delirium on dementia", "disposition": "Home with home health (caregiver support)",
        "complexity": "high", "lace": 12, "risk_band": "high",
        "primary_icd10": "A41.9", "secondary_icd10": ["G30.9", "N39.0", "R62.7", "Z91.14", "Z91.81"],
        "labs": [{"test": "WBC", "value": "9.0", "unit": "10^3/uL", "flag": ""},
                 {"test": "Sodium", "value": "133", "unit": "mEq/L", "flag": "L"},
                 {"test": "Albumin", "value": "3.0", "unit": "g/dL", "flag": "L"}],
        "vitals": {"bp": "122/70", "hr": 80, "rr": 16, "spo2": 97, "temp": 98.4, "weight_kg": 52},
        "allergy": "NKDA", "functional": {"mobility": "100 ft w/ rolling walker + supervision",
            "fall_risk": "High", "cognition": "Moderate dementia; delirium improving", "adls": "Needs cueing"},
        "dme": ["Rolling walker", "Bedside commode", "Shower chair"],
        "follow_up": [{"with": "Geriatrics / PCP", "when": "within 1 week"},
                      {"with": "Adult day program intake", "when": "within 2 weeks"}],
        "goals_of_care": "DNR/DNI (per family + advance directive)",
    },
    {  # 15 Postpartum preeclampsia
        "dx_short": "Postpartum preeclampsia (severe features)", "disposition": "Home (self-care)",
        "complexity": "moderate", "lace": 8, "risk_band": "medium",
        "primary_icd10": "O14.13", "secondary_icd10": ["O13.9", "O90.81", "O82", "F41.9"],
        "labs": [{"test": "Platelets", "value": "128", "unit": "10^3/uL", "flag": "L"},
                 {"test": "AST", "value": "44", "unit": "U/L", "flag": "H"},
                 {"test": "Hemoglobin", "value": "10.4", "unit": "g/dL", "flag": "L"}],
        "vitals": {"bp": "148/94", "hr": 84, "rr": 16, "spo2": 99, "temp": 98.6, "weight_kg": 74},
        "allergy": "NKDA", "functional": {"mobility": "Independent", "fall_risk": "Low",
            "cognition": "Intact", "adls": "Independent"},
        "dme": ["Home blood-pressure cuff"],
        "follow_up": [{"with": "Obstetrics (BP check)", "when": "in 3-5 days"},
                      {"with": "PCP", "when": "within 2 weeks"}],
        "goals_of_care": "Full code",
    },
]

_BASE_DATE = datetime.date(2026, 5, 1)
_SYN_DISCLAIMER = "Synthetic data for development/demo only — not a real person."


def _reconcile(adm_meds: list, dis_meds: list) -> list:
    """Approximate med reconciliation from admission vs discharge lists (by drug name)."""
    def name(m):
        return m.split()[0].lower().strip("(,")
    adm = {name(m): m for m in adm_meds}
    dis_names = {name(m) for m in dis_meds}
    rec = []
    for m in dis_meds:
        n = name(m)
        if "(new" in m.lower() or n not in adm:
            rec.append({"med": m, "action": "new", "reason": "Started this admission"})
        else:
            rec.append({"med": m, "action": "continue", "reason": "Home medication continued"})
    for n, m in adm.items():
        if n not in dis_names:
            rec.append({"med": m, "action": "stop", "reason": "Discontinued / not on discharge list"})
    return rec


def _vital_trend(v: dict) -> list:
    """Synthesize a 3-point trend (admission → midpoint → current) deterministically."""
    try:
        sys_bp = int(str(v["bp"]).split("/")[0]); dia_bp = int(str(v["bp"]).split("/")[1])
    except Exception:
        sys_bp, dia_bp = 130, 80
    pts = []
    for i, lbl in enumerate(["admission", "midpoint", "current"]):
        f = (2 - i)  # worse at admission
        pts.append({
            "label": lbl,
            "bp": f"{sys_bp + f * 8}/{dia_bp + f * 4}",
            "hr": v["hr"] + f * 6,
            "spo2": max(85, v["spo2"] - f * 2),
            "temp": round(v["temp"] + f * 0.5, 1),
        })
    return pts


def _form_data(idx: int, sc: dict, clin: dict, demo: dict) -> dict:
    """The flat SAMPLE_PATIENT_WEB-shaped fields the Planner form + agents consume."""
    return {
        "patient_name": demo["name"], "age": str(demo["age"]), "gender": demo["gender"],
        "mrn": demo["mrn"], "admission_date": demo["adm"], "expected_discharge_date": demo["disc"],
        "attending_physician": demo["attending"],
        "primary_diagnosis": sc["primary"], "secondary_diagnoses": "\n".join(sc["secondary"]),
        "additional_clinical_notes": sc["notes"],
        "primary_insurance": demo["pri_ins"], "secondary_insurance": demo["sec_ins"],
        "medicare_part_a": demo["part_a"], "snf_days_used": str(demo["snf_used"]),
        "admission_medications": "\n".join(sc["adm_meds"]),
        "inpatient_medications": "\n".join(sc["inp_meds"]),
        "discharge_medications": "\n".join(sc["dis_meds"]),
        "pt_evaluation": sc["pt"], "ot_evaluation": sc["ot"], "st_evaluation": sc["st"],
        "living_situation": demo["living"], "caregiver": demo["caregiver"],
        "primary_language": demo["lang_note"], "transportation": demo["transport"],
        "housing_type": demo["housing"], "bedroom_location": demo["bedroom"],
        "patient_family_preference": (
            f"Patient ({demo['lang']} preferred) and family discussed disposition: {clin['disposition']}."
        ),
        "physician_goals": sc["goals"],
        "additional_notes": (
            f"Primary language: {demo['lang_note']}. Insurance: {demo['pri_ins']}"
            + (f"; secondary: {demo['sec_ins']}" if demo["sec_ins"] and demo["sec_ins"] != "None" else "")
            + f". Disposition: {clin['disposition']}. Complexity: {clin['complexity']}. "
            + _SYN_DISCLAIMER
        ),
    }


def _rich_record(idx: int) -> dict:
    sc = _SCENARIOS[idx % len(_SCENARIOS)]
    clin = _CLIN[idx % len(_CLIN)]
    female = (idx % 2 == 0)
    first = (_FIRST_F if female else _FIRST_M)[(idx * 7) % 20]
    last = _LAST[(idx * 3) % len(_LAST)]
    gender = "Female" if female else "Male"
    age = 52 + ((idx * 5) % 44)
    dob = datetime.date(_BASE_DATE.year - age, 1 + (idx % 12), 1 + (idx % 27))
    adm = _BASE_DATE + datetime.timedelta(days=(idx * 2) % 30)
    disc = adm + datetime.timedelta(days=sc["los"])
    lang, lang_note = _LANGS[idx % len(_LANGS)]
    pri_ins, sec_ins, part_a, snf_used = _INSURANCE[idx % len(_INSURANCE)]
    payer_short = pri_ins.split("—")[0].split("(")[0].strip()
    dual = ("dual" in pri_ins.lower()) or ("Medi-Cal" in (sec_ins or ""))

    demo = {
        "name": f"{first} {last}", "age": age, "gender": gender,
        "mrn": f"SYN-{200000 + idx}", "adm": adm.isoformat(), "disc": disc.isoformat(),
        "attending": f"Dr. {_LAST[(idx * 5) % len(_LAST)]}, MD — {sc['specialty']}",
        "pri_ins": pri_ins, "sec_ins": sec_ins, "part_a": part_a, "snf_used": snf_used,
        "lang": lang, "lang_note": lang_note, "living": _LIVING[(idx * 3) % len(_LIVING)],
        "caregiver": _CAREGIVER[(idx * 7) % len(_CAREGIVER)], "transport": _TRANSPORT[(idx * 5) % len(_TRANSPORT)],
        "housing": _HOUSING[(idx * 3) % len(_HOUSING)], "bedroom": _BEDROOM[(idx * 2) % len(_BEDROOM)],
    }

    form = _form_data(idx, sc, clin, demo)
    interpreter = "interpreter" in lang_note.lower()

    # Problem list: primary + secondaries (icd10 paired where available)
    problems = [{"icd10": clin["primary_icd10"], "label": sc["primary"], "status": "active", "primary": True}]
    for i, label in enumerate(sc["secondary"]):
        code = clin["secondary_icd10"][i] if i < len(clin["secondary_icd10"]) else ""
        problems.append({"icd10": code, "label": label, "status": "active", "primary": False})

    tcm_eligible = clin["disposition"].lower().startswith(("home", "medical respite"))
    tcm_cpt = "99496" if clin["complexity"] == "high" else "99495"

    return {
        "id": f"{idx + 1:03d}",
        "synthetic": True,
        "disclaimer": _SYN_DISCLAIMER,
        "form_data": form,                # flat fields for the Planner form + agents
        "demographics": {
            "name": demo["name"], "dob": dob.isoformat(), "age": age, "sex": gender,
            "preferred_language": lang, "interpreter_needed": interpreter,
            "mrn": demo["mrn"], "code_status": clin["goals_of_care"],
            "race_ethnicity": "Synthetic — not specified",
        },
        "encounter": {
            "type": "inpatient", "admit_date": adm.isoformat(), "los_days": sc["los"],
            "admitting_dx": clin["dx_short"], "attending": demo["attending"],
            "unit": sc["specialty"], "expected_discharge_date": disc.isoformat(),
        },
        "problem_list": problems,
        "medications": {
            "home": sc["adm_meds"], "inpatient": sc["inp_meds"], "discharge": sc["dis_meds"],
            "reconciliation": _reconcile(sc["adm_meds"], sc["dis_meds"]),
        },
        "allergies": ([] if clin["allergy"] == "NKDA"
                      else [{"substance": clin["allergy"].split("—")[0].strip(),
                             "reaction": (clin["allergy"].split("—")[1].strip() if "—" in clin["allergy"] else ""),
                             "severity": "moderate"}]),
        "vitals": {"latest": clin["vitals"], "trend": _vital_trend(clin["vitals"])},
        "labs": clin["labs"],
        "functional_status": clin["functional"],
        "sdoh": {
            "housing": demo["housing"], "lives_with": demo["living"],
            "primary_caregiver": demo["caregiver"], "transportation": demo["transport"],
            "health_literacy": ("Limited" if interpreter else "Adequate"),
            "calaim_ecm_eligible": ("Medi-Cal" in pri_ins or dual),
        },
        "payer": {
            "primary": pri_ins, "secondary": sec_ins, "payer_short": payer_short,
            "dual_eligible": dual, "member_id": f"SYN-{900000 + idx}",
            "prior_auth": ([{"service": "SNF admission", "status": "pending"}]
                           if "SNF" in clin["disposition"] or "rehab" in clin["disposition"].lower() else []),
        },
        "discharge": {
            "disposition": clin["disposition"], "readiness": "Pending post-acute setup",
            "dme_needs": clin["dme"], "follow_up": clin["follow_up"],
            "barriers": ([] if demo["caregiver"].startswith(("Daughter", "Spouse", "Son"))
                         else ["Caregiver/support limited"]),
        },
        "risk": {
            "readmission_lace": clin["lace"], "readmission_band": clin["risk_band"],
            "complexity": clin["complexity"],
        },
        "tcm": {
            "eligible": tcm_eligible, "complexity": clin["complexity"],
            "cpt": (tcm_cpt if tcm_eligible else None),
            "rationale": ("Discharged to community; follow-up within TCM window"
                          if tcm_eligible else "Not eligible — discharged to an institutional setting"),
        },
        "preferences": {"goals_of_care": clin["goals_of_care"], "language_for_education": lang},
    }


# Build the 100 rich records once at import; derive the flat list for back-compat.
RICH_PATIENTS: list[dict] = [_rich_record(i) for i in range(100)]
_BY_ID_RICH: dict[str, dict] = {r["id"]: r for r in RICH_PATIENTS}
SAMPLE_PATIENTS: list[dict] = [{**r["form_data"], "id": r["id"]} for r in RICH_PATIENTS]
_BY_ID: dict[str, dict] = {p["id"]: p for p in SAMPLE_PATIENTS}


def list_sample_patients() -> list[dict]:
    """Lightweight list for the picker dropdown: id, name, demo + label fields."""
    out = []
    for r in RICH_PATIENTS:
        clin = r["risk"]
        out.append({
            "id": r["id"],
            "name": r["demographics"]["name"],
            "age": r["demographics"]["age"],
            "gender": r["demographics"]["sex"],
            "dx_short": r["encounter"]["admitting_dx"],
            "disposition": r["discharge"]["disposition"],
            "payer_short": r["payer"]["payer_short"],
            "complexity": clin["complexity"],
            "language": r["demographics"]["preferred_language"],
            "label": (f"{r['id']} · {r['demographics']['name']} "
                      f"({r['demographics']['age']}{r['demographics']['sex'][0]}) · "
                      f"{r['encounter']['admitting_dx']} · {r['discharge']['disposition']} · "
                      f"{r['payer']['payer_short']}"),
        })
    return out


def get_sample_patient(pid: str) -> Optional[dict]:
    """Flat form-shaped patient by id (e.g. '001'). Returns None if not found."""
    return _BY_ID.get(str(pid).zfill(3))


def get_sample_record(pid: str) -> Optional[dict]:
    """Full rich nested record by id (for the Patient Snapshot panel)."""
    return _BY_ID_RICH.get(str(pid).zfill(3))


def validate_coherence(record: dict) -> list[str]:
    """Return a list of coherence issues for a rich record (empty == coherent).
    Pragmatic checks — meant to catch contradictions, not enforce exhaustive realism."""
    issues: list[str] = []
    pid = record.get("id", "?")
    disp = record["discharge"]["disposition"].lower()
    func = record["functional_status"]

    # 1. Allergy must not appear in active (discharge) meds.
    dis_meds = " ".join(record["medications"]["discharge"]).lower()
    for a in record["allergies"]:
        sub = a["substance"].lower()
        if sub and sub in dis_meds:
            issues.append(f"{pid}: allergy '{a['substance']}' appears in discharge meds")

    # 2. Dependent/severe functional status should not discharge to plain self-care.
    #    Use a word boundary so "independent"/"modified independent" never matches.
    adls = str(func.get("adls", "")).lower()
    dependent = re.search(r"\bdependent\b", adls) is not None
    if (dependent or "max assist" in adls) and "self-care" in disp:
        issues.append(f"{pid}: dependent ADLs but disposition is home self-care")

    # 3. TCM eligibility must follow disposition (community vs institutional).
    tcm = record["tcm"]
    institutional = any(k in disp for k in ("snf", "skilled nursing", "irf", "inpatient rehab", "ltach"))
    if tcm["eligible"] and institutional:
        issues.append(f"{pid}: TCM marked eligible but disposition is institutional")
    if (not tcm["eligible"]) and ("home" in disp) and ("hospice" not in disp):
        issues.append(f"{pid}: discharged home but TCM not eligible")

    # 4. Must have a primary problem and at least one discharge med (data richness).
    if not any(p.get("primary") for p in record["problem_list"]):
        issues.append(f"{pid}: no primary problem")
    if not record["medications"]["discharge"]:
        issues.append(f"{pid}: no discharge medications")

    # 5. Labs present for richness.
    if not record["labs"]:
        issues.append(f"{pid}: no labs")

    return issues
