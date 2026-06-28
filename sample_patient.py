"""Synthetic sample patient data for testing the discharge planning system.

All patient information in this file is entirely fictional and does not
represent any real individual. Used for development and demonstration only.
"""

SAMPLE_PATIENT: dict = {
    # -------------------------------------------------------------------------
    # Demographics
    # -------------------------------------------------------------------------
    "patient_name": "James Mitchell",
    "age": 74,
    "sex": "Male",
    "mrn": "JM-2024-8847",
    "date_of_birth": "1950-03-12",
    "admission_date": "2024-05-13",
    "anticipated_discharge_date": "2024-05-17",

    # -------------------------------------------------------------------------
    # Diagnoses
    # -------------------------------------------------------------------------
    "primary_diagnosis": (
        "Acute Decompensated Heart Failure (ADHF) with reduced ejection fraction — "
        "EF 30% on echo, bilateral lower extremity edema, orthopnea, dyspnea on exertion"
    ),
    "secondary_diagnoses": [
        "Type 2 Diabetes Mellitus (T2DM) — on insulin during admission",
        "Hypertension (HTN) — BP controlled with current regimen",
        "Chronic Kidney Disease (CKD) Stage 3 — baseline Cr ~1.6",
        "Atrial Fibrillation — rate-controlled, on anticoagulation",
        "Obesity — BMI 34.2",
        "Hyperlipidemia",
    ],

    # -------------------------------------------------------------------------
    # Vitals (current, at time of discharge planning)
    # -------------------------------------------------------------------------
    "vitals": {
        "Blood Pressure": "118/72 mmHg",
        "Heart Rate": "74 bpm (rate-controlled AFib)",
        "Respiratory Rate": "16 breaths/min",
        "O2 Saturation": "96% on room air",
        "Temperature": "98.4°F",
        "Weight (admission)": "218 lbs",
        "Weight (current)": "207 lbs (net -11 lbs after diuresis)",
    },

    # -------------------------------------------------------------------------
    # Lab results
    # -------------------------------------------------------------------------
    "labs": {
        "BNP": "420 pg/mL (down from 1,840 on admission)",
        "Creatinine": "1.8 mg/dL (baseline ~1.6; slight uptick post-diuresis)",
        "eGFR": "38 mL/min/1.73m²",
        "Potassium": "3.9 mEq/L",
        "Sodium": "138 mEq/L",
        "HbA1c": "7.9% (drawn on admission)",
        "INR": "Not applicable — on direct oral anticoagulant (apixaban)",
        "CBC": "WBC 8.2, Hgb 11.4 (mild anemia), Plt 192",
        "Troponin": "0.04 (stable, no acute MI pattern)",
        "TSH": "2.1 (normal)",
    },

    # -------------------------------------------------------------------------
    # Functional status
    # -------------------------------------------------------------------------
    "functional_status": {
        "mobility": (
            "Ambulates with rolling walker; requires supervision on stairs; "
            "walked 150 ft in hallway without stopping; mildly short of breath at exertion"
        ),
        "adls": (
            "Requires minimal assistance with bathing and lower-body dressing; "
            "independent with grooming, feeding, and toileting when equipment available"
        ),
        "iadls": (
            "Requires assistance with meal preparation, housekeeping, medication management; "
            "not driving"
        ),
        "cognition": (
            "Alert and oriented x4; MMSE 27/30 (mild age-related changes); "
            "no acute confusion; understands discharge instructions"
        ),
        "fall_risk": "HIGH — rolling walker required, history of near-fall 3 months ago, diuretic use",
        "prior_functional_baseline": (
            "Prior to admission: independent ADLs with some fatigue; used walker for long distances"
        ),
    },

    # -------------------------------------------------------------------------
    # Therapy evaluations
    # -------------------------------------------------------------------------
    "therapy_evaluations": {
        "PT": (
            "Evaluated on HD3. Ambulates 150 ft with rolling walker. Stairs require supervision. "
            "Recommends home PT 3x/week x4 weeks, gait training, stair safety, HEP. Fall risk HIGH."
        ),
        "OT": (
            "Evaluated on HD3. Independent with adaptive equipment for upper body ADLs; "
            "min assist for lower body bathing/dressing. Recommends home OT 2x/week x3 weeks, "
            "ADL training, energy conservation, home safety eval. Recommend grab bars, tub bench."
        ),
        "ST": "Not evaluated — no swallowing or communication concerns identified.",
    },

    # -------------------------------------------------------------------------
    # Medications
    # -------------------------------------------------------------------------
    "allergies": [
        "Sulfa drugs — rash (documented)",
        "Codeine — nausea/vomiting",
    ],
    "admission_medications": [
        "Furosemide 40 mg PO daily",
        "Metoprolol succinate 50 mg PO daily",
        "Lisinopril 10 mg PO daily",
        "Metformin 1000 mg PO BID",
        "Apixaban 5 mg PO BID",
        "Atorvastatin 40 mg PO nightly",
        "Potassium chloride 20 mEq PO daily",
    ],
    "inpatient_medications": [
        "Furosemide IV 80 mg BID (acute diuresis phase)",
        "Metoprolol IV (rate control for AFib with RVR on day 1)",
        "Metformin — HELD (CKD/contrast risk)",
        "Lisinopril — HELD (acute renal worsening post-diuresis)",
        "Spironolactone 25 mg PO daily — NEW (added for HFrEF guideline-directed therapy)",
        "Apixaban 5 mg PO BID — continued",
        "Atorvastatin 40 mg PO nightly — continued",
        "Potassium chloride 40 mEq PO BID — increased (monitoring with spironolactone)",
        "Insulin sliding scale — for inpatient glucose management",
    ],
    "discharge_medications": [
        "Furosemide 80 mg PO daily (INCREASED from 40 mg — for outpatient volume management)",
        "Metoprolol succinate 50 mg PO daily (continued)",
        "Lisinopril 10 mg PO daily (RESUMED — Cr stable at 1.8)",
        "Spironolactone 25 mg PO daily (NEW — HFrEF guideline-directed therapy)",
        "Apixaban 5 mg PO BID (continued — AFib anticoagulation)",
        "Atorvastatin 40 mg PO nightly (continued)",
        "Potassium chloride 20 mEq PO BID (INCREASED from daily — with spironolactone caution)",
        "Metformin 500 mg PO BID (RESUMED at lower dose — CKD dose adjustment, recheck Cr in 1 week)",
    ],

    # -------------------------------------------------------------------------
    # Insurance
    # -------------------------------------------------------------------------
    "insurance": {
        "primary": {
            "payer_name": "Medicare",
            "plan_type": "Medicare Part A & Part B (Traditional Fee-for-Service)",
            "member_id": "1EG4-TE5-MK72",
            "group_number": "N/A — Traditional Medicare",
            "medicare_type": "Traditional (not Medicare Advantage)",
            "snf_days_used_this_benefit_period": 0,
            "snf_days_remaining": 100,
            "notes": "Patient has met 3-day qualifying inpatient stay requirement for SNF coverage",
        },
        "secondary": {
            "payer_name": "Medigap Plan G",
            "carrier": "AARP / UnitedHealthcare",
            "member_id": "MG-44821-G",
            "covers": (
                "Medicare Part A deductible, coinsurance, SNF days 21-100 coinsurance, "
                "Part B coinsurance (except Part B deductible)"
            ),
            "part_b_deductible_met": True,
        },
        "part_d": {
            "payer_name": "SilverScript Choice (Part D)",
            "member_id": "SS-7714-CH",
            "formulary_tier_notes": "Furosemide, metoprolol, lisinopril, metformin on Tier 1; "
                                    "Apixaban (Eliquis) on Tier 3 — patient pays ~$47/month",
        },
    },
    "anticipated_post_discharge_needs": [
        "Home health nursing 3x/week — wound check, weight monitoring, medication management",
        "Home PT 3x/week x 4 weeks",
        "Home OT 2x/week x 3 weeks",
        "Durable Medical Equipment: hospital bed (for bedroom relocation), rolling walker, tub bench, grab bars",
        "Cardiology follow-up within 7 days",
        "PCP follow-up within 5 days",
        "BMP (electrolytes, creatinine) within 3-5 days post-discharge",
    ],

    # -------------------------------------------------------------------------
    # Home environment
    # -------------------------------------------------------------------------
    "home_environment": {
        "housing_type": "Single-family home, 2-story",
        "ownership": "Owns home (no mortgage)",
        "bedroom_location": "Second floor — significant barrier given functional status",
        "bathroom_location": "One full bath on second floor; half bath on first floor (no shower)",
        "stairs_to_entry": "3 steps to front door, no ramp",
        "elevator": "No",
        "grab_bars": "None currently installed",
        "concerns": (
            "Bedroom on second floor is major safety concern. Patient cannot safely navigate stairs "
            "unsupervised. First-floor bedroom relocation needed before discharge. "
            "No grab bars in bathroom."
        ),
    },

    # -------------------------------------------------------------------------
    # Support system
    # -------------------------------------------------------------------------
    "support_system": {
        "living_situation": "Lives alone",
        "primary_caregiver": "Daughter — Susan Mitchell-Torres",
        "caregiver_relationship": "Daughter",
        "caregiver_contact": "(555) 847-2193",
        "caregiver_availability": (
            "Lives 20 minutes away; works full-time Monday-Friday; available evenings and weekends; "
            "willing to take 1 week off work for discharge transition"
        ),
        "caregiver_health_status": "Healthy adult, no limitations",
        "other_support": "Church community — meals 2x/week, neighbor checks in",
        "concerns": (
            "Patient lives alone — coverage gaps on weekdays during work hours. "
            "Daughter is primary but not full-time available. May need paid home health aide for ADLs."
        ),
    },

    # -------------------------------------------------------------------------
    # Transportation
    # -------------------------------------------------------------------------
    "transportation": {
        "patient_drives": False,
        "reason": "Voluntarily stopped driving 2 years ago due to vision and fatigue",
        "primary_transportation": "Daughter provides transportation",
        "daughter_availability_for_discharge": "Available to pick up on discharge day",
        "medical_transport_eligibility": "Eligible for Medicaid transport if needed (not enrolled)",
        "follow_up_transport": "Daughter can take to appointments; backup — call local senior transport",
    },

    # -------------------------------------------------------------------------
    # Financial information
    # -------------------------------------------------------------------------
    "financial_info": {
        "income_sources": "Social Security ($1,820/month), small pension ($340/month)",
        "total_monthly_income_approx": "$2,160/month",
        "part_b_premium": "$174.70/month (deducted from SS)",
        "part_d_premium": "$28/month",
        "financial_concerns": "Fixed income; Eliquis co-pay is notable expense (~$47/month on Part D)",
        "pharmaceutical_assistance": "May qualify for Eliquis manufacturer copay card (not yet applied)",
        "snap_enrollment": "Not enrolled — may be eligible based on income",
    },

    # -------------------------------------------------------------------------
    # Food security
    # -------------------------------------------------------------------------
    "food_security": (
        "Adequate — cooks own meals with some difficulty; daughter brings meals 3x/week; "
        "church community delivers meals 2x/week. Low-sodium diet adherence is inconsistent."
    ),

    # -------------------------------------------------------------------------
    # Safety concerns
    # -------------------------------------------------------------------------
    "safety_concerns": [
        "High fall risk — rolling walker required, stairs without ramp, no grab bars",
        "Lives alone with daytime coverage gaps",
        "Medication complexity — 8 medications with recent changes",
        "Second-floor bedroom — unsafe for current functional level",
    ],

    # -------------------------------------------------------------------------
    # Language and literacy
    # -------------------------------------------------------------------------
    "language_literacy": {
        "primary_language": "English",
        "interpreter_needed": False,
        "health_literacy": "Adequate — patient reads at approximately 10th grade level",
        "technology_literacy": "Basic — has smartphone, uses it for calls; daughter helps with apps",
        "preferred_learning_style": "Verbal with written summary; large print preferred",
    },

    # -------------------------------------------------------------------------
    # Social history
    # -------------------------------------------------------------------------
    "social_history": {
        "tobacco": "Former smoker — quit 15 years ago (30 pack-year history)",
        "alcohol": "Rare — 1-2 drinks/month socially",
        "illicit_substances": "Denies",
        "exercise": "Sedentary prior to admission; previously walked around neighborhood",
        "diet": "Low-sodium diet prescribed; adherence inconsistent (patient admits eating canned soups)",
        "occupation": "Retired electrician",
        "education": "High school diploma + vocational training",
        "advance_directives": "Has healthcare proxy (daughter Susan); no living will on file",
        "code_status": "Full code",
    },

    # -------------------------------------------------------------------------
    # Hospital course summary
    # -------------------------------------------------------------------------
    "hospital_course": (
        "Mr. Mitchell is a 74-year-old male with HFrEF (EF 30%), T2DM, HTN, CKD3, and AFib who "
        "presented with a 5-day history of worsening bilateral leg swelling, orthopnea, and dyspnea "
        "on exertion. On admission, he was 11 lbs above dry weight with significant pulmonary "
        "congestion on CXR and BNP of 1,840. He was initiated on IV furosemide with good response — "
        "net -11 lbs over 4 days. Metformin and lisinopril held initially; lisinopril was resumed "
        "on HD4 after creatinine stabilized. Spironolactone 25 mg was added per HFrEF guidelines. "
        "Cardiology evaluated patient on HD2 and recommended intensified outpatient follow-up. "
        "Echocardiogram confirmed EF 30% (known HFrEF, no new wall motion abnormalities). "
        "Patient is now clinically improved, hemodynamically stable, and near dry weight. "
        "Physical and occupational therapy evaluated patient on HD3 with recommendations for home "
        "therapy services. Discharge is anticipated on HD5 pending social work clearance and "
        "completion of home health authorization."
    ),

    # -------------------------------------------------------------------------
    # Clinical notes / pending items
    # -------------------------------------------------------------------------
    "clinical_notes": (
        "Pending items before discharge: (1) BMP to be drawn morning of discharge day to confirm "
        "potassium and creatinine stable before increasing furosemide dose. "
        "(2) Cardiology to sign discharge summary and complete ambulatory referral. "
        "(3) Social work to confirm home health agency authorization. "
        "(4) Patient and daughter education session on heart failure daily weight log, "
        "fluid restriction (1.5L/day), sodium restriction (2g/day), and when to call 911. "
        "(5) Advance directive discussion — patient interested in completing living will."
    ),
}

# ---------------------------------------------------------------------------
# Web form field mapping — flat string values for the browser intake form.
# ---------------------------------------------------------------------------
SAMPLE_PATIENT_WEB: dict = {
    # Section 1 — Patient Demographics
    "patient_name": SAMPLE_PATIENT["patient_name"],
    "age": str(SAMPLE_PATIENT["age"]),
    "gender": SAMPLE_PATIENT["sex"],
    "mrn": SAMPLE_PATIENT["mrn"],
    "admission_date": SAMPLE_PATIENT["admission_date"],
    "expected_discharge_date": SAMPLE_PATIENT["anticipated_discharge_date"],
    "attending_physician": "Dr. Sarah Chen, MD — Cardiology",

    # Section 2 — Diagnoses
    "primary_diagnosis": SAMPLE_PATIENT["primary_diagnosis"],
    "secondary_diagnoses": "\n".join(SAMPLE_PATIENT["secondary_diagnoses"]),
    "additional_clinical_notes": SAMPLE_PATIENT["clinical_notes"],

    # Section 3 — Insurance
    "patient_first_name": SAMPLE_PATIENT["patient_name"].split(" ", 1)[0],
    "patient_last_name": SAMPLE_PATIENT["patient_name"].split(" ", 1)[-1],
    "date_of_birth": SAMPLE_PATIENT["date_of_birth"],
    "insurance_member_id": SAMPLE_PATIENT["insurance"]["primary"]["member_id"],
    "primary_insurance": SAMPLE_PATIENT["insurance"]["primary"]["payer_name"],
    "secondary_insurance": (
        SAMPLE_PATIENT["insurance"]["secondary"]["payer_name"]
        + " — "
        + SAMPLE_PATIENT["insurance"]["secondary"]["carrier"]
    ),
    "medicare_part_a": "Yes",
    "snf_days_used": str(
        SAMPLE_PATIENT["insurance"]["primary"]["snf_days_used_this_benefit_period"]
    ),

    # Section 4 — Medications
    "admission_medications": "\n".join(SAMPLE_PATIENT["admission_medications"]),
    "inpatient_medications": "\n".join(SAMPLE_PATIENT["inpatient_medications"]),
    "discharge_medications": "\n".join(SAMPLE_PATIENT["discharge_medications"]),

    # Section 5 — Therapy Evaluations
    "pt_evaluation": SAMPLE_PATIENT["therapy_evaluations"]["PT"],
    "ot_evaluation": SAMPLE_PATIENT["therapy_evaluations"]["OT"],
    "st_evaluation": SAMPLE_PATIENT["therapy_evaluations"]["ST"],

    # Section 6 — Social History
    "living_situation": SAMPLE_PATIENT["support_system"]["living_situation"],
    "caregiver": (
        SAMPLE_PATIENT["support_system"]["primary_caregiver"]
        + " — "
        + SAMPLE_PATIENT["support_system"]["caregiver_availability"]
    ),
    "primary_language": SAMPLE_PATIENT["language_literacy"]["primary_language"],
    "transportation": SAMPLE_PATIENT["transportation"]["primary_transportation"],
    "housing_type": "House",
    "bedroom_location": "Second floor",

    # Section 7 — Discharge Goals
    "patient_family_preference": (
        "Patient and daughter prefer discharge to home with home health services. "
        "Daughter (Susan Mitchell-Torres) willing to take 1 week off work to support transition. "
        "Patient does not want to go to a nursing facility."
    ),
    "physician_goals": (
        "Discharge home with home health nursing, PT, and OT. "
        "Cardiology follow-up within 7 days. PCP follow-up within 5 days. "
        "BMP (electrolytes, creatinine) within 3-5 days post-discharge. "
        "First-floor bedroom relocation required before discharge."
    ),
    "additional_notes": (
        "Advance directive discussion needed — patient interested in completing living will. "
        "Eliquis manufacturer copay card application pending. "
        "Church community provides meal support 2x/week."
    ),
}
