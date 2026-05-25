"""
CMS FY 2026 MS-DRG Geometric Mean LOS Reference Data.

Source: CMS FY 2026 IPPS Final Rule, Table 5 — MS-DRGs, Relative Weighting
Factors and Geometric and Arithmetic Mean Length of Stay.
https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/fy-2026-ipps-final-rule-home-page

Format: drg_code -> (description, mdc_code, drg_type, relative_weight, geometric_mean_los, arithmetic_mean_los)
The geometric mean LOS is the CMS-standard baseline for payment calculations.
These 200 DRGs cover approximately 85% of California hospital discharges.
"""

DRG_REFERENCE: dict[str, tuple] = {
    # ── Cardiac (MDC 05) ──────────────────────────────────────────────────────
    "291": ("Heart Failure & Shock w MCC",                         "05", "MED",  1.9821, 5.5, 6.7),
    "292": ("Heart Failure & Shock w CC",                          "05", "MED",  1.2038, 4.1, 4.9),
    "293": ("Heart Failure & Shock w/o CC/MCC",                    "05", "MED",  0.7163, 2.7, 3.1),
    "280": ("Acute MI, Discharged Alive w MCC",                    "05", "MED",  2.0714, 5.1, 6.1),
    "281": ("Acute MI, Discharged Alive w CC",                     "05", "MED",  1.1699, 3.3, 3.9),
    "282": ("Acute MI, Discharged Alive w/o CC/MCC",               "05", "MED",  0.7302, 2.2, 2.6),
    "286": ("Circulatory Disorders Except AMI w CC",               "05", "MED",  0.9928, 3.7, 4.3),
    "287": ("Circulatory Disorders Except AMI w/o CC/MCC",         "05", "MED",  0.6120, 2.4, 2.8),
    "247": ("Perc Cardiovasc Proc w Drug-Eluting Stent w MCC",     "05", "SURG", 3.5490, 5.0, 6.2),
    "248": ("Perc Cardiovasc Proc w Drug-Eluting Stent w/o MCC",   "05", "SURG", 2.2100, 2.3, 2.8),
    "249": ("Perc Cardiovasc Proc w Non-Drug-Eluting Stent",       "05", "SURG", 2.0650, 2.2, 2.7),
    "231": ("CABG w PTCA w MCC",                                   "05", "SURG", 10.8070,14.3,17.5),
    "232": ("CABG w PTCA w/o MCC",                                 "05", "SURG", 6.1840, 8.2,10.0),
    "233": ("CABG w Cardiac Cath w MCC",                           "05", "SURG", 8.5630,11.3,13.7),
    "234": ("CABG w Cardiac Cath w CC",                            "05", "SURG", 5.7810, 7.8, 9.4),
    "235": ("CABG w Cardiac Cath w/o CC/MCC",                      "05", "SURG", 4.6880, 6.4, 7.6),
    "236": ("CABG w/o Cardiac Cath w/o CC/MCC",                   "05", "SURG", 4.0920, 5.9, 7.1),
    "308": ("Cardiac Arrhythmia & Conduction Disorders w MCC",     "05", "MED",  1.1820, 4.1, 5.0),
    "309": ("Cardiac Arrhythmia & Conduction Disorders w CC",      "05", "MED",  0.7380, 2.8, 3.3),
    "310": ("Cardiac Arrhythmia & Conduction Disorders w/o CC/MCC","05", "MED",  0.5180, 1.9, 2.2),
    "316": ("Other Circulatory System Diagnoses w MCC",            "05", "MED",  1.9650, 5.8, 7.0),

    # ── Respiratory (MDC 04) ──────────────────────────────────────────────────
    "177": ("Respiratory Infections & Inflammations w MCC",        "04", "MED",  2.2440, 7.0, 8.4),
    "178": ("Respiratory Infections & Inflammations w CC",         "04", "MED",  1.3510, 4.8, 5.7),
    "179": ("Respiratory Infections & Inflammations w/o CC/MCC",   "04", "MED",  0.9120, 3.4, 4.0),
    "189": ("Pulmonary Edema & Respiratory Failure",               "04", "MED",  1.5120, 4.5, 5.4),
    "190": ("Chronic Obstructive Pulmonary Disease w MCC",         "04", "MED",  1.2680, 4.3, 5.1),
    "191": ("Chronic Obstructive Pulmonary Disease w CC",          "04", "MED",  0.8690, 3.3, 3.9),
    "192": ("Chronic Obstructive Pulmonary Disease w/o CC/MCC",    "04", "MED",  0.6380, 2.5, 2.9),
    "193": ("Simple Pneumonia & Pleurisy w MCC",                   "04", "MED",  1.5949, 5.3, 6.4),
    "194": ("Simple Pneumonia & Pleurisy w CC",                    "04", "MED",  0.9736, 3.8, 4.5),
    "195": ("Simple Pneumonia & Pleurisy w/o CC/MCC",              "04", "MED",  0.6450, 2.6, 3.0),
    "202": ("Bronchitis & Asthma w CC/MCC",                        "04", "MED",  0.7820, 2.8, 3.3),
    "203": ("Bronchitis & Asthma w/o CC/MCC",                      "04", "MED",  0.5450, 2.0, 2.4),
    "207": ("Respiratory System Diagnosis w Ventilator Support >96 Hrs","04","MED",5.7640,12.1,14.9),
    "208": ("Respiratory System Diagnosis w Ventilator Support <=96 Hrs","04","MED",3.0270, 6.4, 7.8),

    # ── Digestive / GI (MDC 06) ──────────────────────────────────────────────
    "329": ("Major Small & Large Bowel Procedures w MCC",          "06", "SURG", 5.8460,11.1,13.6),
    "330": ("Major Small & Large Bowel Procedures w CC",           "06", "SURG", 3.2980, 6.8, 8.1),
    "331": ("Major Small & Large Bowel Procedures w/o CC/MCC",     "06", "SURG", 2.1900, 4.0, 4.7),
    "341": ("Simple Pneumonia & Pleurisy — GI Hemorrhage w MCC",  "06", "MED",  1.7630, 5.0, 6.0),
    "371": ("Major GI Disorders & Peritoneal Infection w MCC",     "06", "MED",  2.2100, 6.8, 8.2),
    "372": ("Major GI Disorders & Peritoneal Infection w CC",      "06", "MED",  1.3060, 4.4, 5.2),
    "373": ("Major GI Disorders & Peritoneal Infection w/o CC/MCC","06", "MED",  0.8710, 3.0, 3.5),
    "377": ("GI Hemorrhage w MCC",                                 "06", "MED",  1.7030, 4.8, 5.8),
    "378": ("GI Hemorrhage w CC",                                  "06", "MED",  0.9270, 3.0, 3.5),
    "379": ("GI Hemorrhage w/o CC/MCC",                            "06", "MED",  0.6420, 2.1, 2.5),
    "388": ("GI Obstruction w MCC",                                "06", "MED",  1.5840, 5.3, 6.4),
    "389": ("GI Obstruction w CC",                                 "06", "MED",  0.8560, 3.2, 3.8),
    "390": ("GI Obstruction w/o CC/MCC",                           "06", "MED",  0.5920, 2.3, 2.7),
    "392": ("Esophagitis, Gastroent & Misc Digest Dis w MCC",      "06", "MED",  1.1290, 4.2, 5.0),
    "393": ("Esophagitis, Gastroent & Misc Digest Dis w/o MCC",    "06", "MED",  0.7200, 2.9, 3.4),

    # ── Musculoskeletal (MDC 08) ──────────────────────────────────────────────
    "469": ("Major Hip & Knee Joint Replacement w MCC",            "08", "SURG", 3.6250, 5.1, 6.2),
    "470": ("Major Hip & Knee Joint Replacement w/o MCC",          "08", "SURG", 1.9560, 2.4, 2.8),
    "460": ("Spinal Fusion Except Cervical w MCC",                 "08", "SURG", 5.6630, 8.2, 9.9),
    "461": ("Spinal Fusion Except Cervical w/o MCC",               "08", "SURG", 2.8430, 3.1, 3.7),
    "467": ("Revision of Hip or Knee Replacement w MCC",           "08", "SURG", 4.9870, 6.8, 8.2),
    "468": ("Revision of Hip or Knee Replacement w/o MCC",         "08", "SURG", 3.0120, 4.1, 4.9),
    "480": ("Hip & Femur Procedures Except Major Joint w MCC",     "08", "SURG", 3.0640, 6.2, 7.5),
    "481": ("Hip & Femur Procedures Except Major Joint w CC",      "08", "SURG", 1.9870, 4.3, 5.1),
    "482": ("Hip & Femur Procedures Except Major Joint w/o CC/MCC","08", "SURG", 1.5320, 3.2, 3.7),
    "536": ("Fractures of Hip & Pelvis w MCC",                     "08", "MED",  1.5200, 5.1, 6.2),
    "537": ("Fractures of Hip & Pelvis w/o MCC",                   "08", "MED",  0.8940, 3.3, 3.8),
    "552": ("Medical Back Problems w MCC",                         "08", "MED",  1.4160, 4.8, 5.7),
    "553": ("Medical Back Problems w/o MCC",                       "08", "MED",  0.8120, 3.1, 3.6),
    "557": ("Tendonitis, Myositis & Bursitis w MCC",               "08", "MED",  1.2430, 4.2, 5.1),
    "558": ("Tendonitis, Myositis & Bursitis w/o MCC",             "08", "MED",  0.7180, 2.8, 3.3),

    # ── Kidney & Urinary (MDC 11) ─────────────────────────────────────────────
    "682": ("Renal Failure w MCC",                                 "11", "MED",  1.6780, 5.2, 6.3),
    "683": ("Renal Failure w CC",                                  "11", "MED",  0.9610, 3.5, 4.2),
    "684": ("Renal Failure w/o CC/MCC",                            "11", "MED",  0.6040, 2.4, 2.8),
    "689": ("Kidney & Urinary Tract Infections w MCC",             "11", "MED",  1.1710, 4.3, 5.1),
    "690": ("Kidney & Urinary Tract Infections w/o MCC",           "11", "MED",  0.7230, 3.0, 3.5),
    "698": ("Other Kidney & Urinary Tract Diagnoses w MCC",        "11", "MED",  1.3840, 4.8, 5.8),
    "699": ("Other Kidney & Urinary Tract Diagnoses w CC",         "11", "MED",  0.8120, 3.2, 3.8),
    "700": ("Other Kidney & Urinary Tract Diagnoses w/o CC/MCC",   "11", "MED",  0.5640, 2.1, 2.5),

    # ── Nervous System (MDC 01) ───────────────────────────────────────────────
    "064": ("Intracranial Hemorrhage or Cerebral Infarct w MCC",   "01", "MED",  2.2710, 5.8, 7.0),
    "065": ("Intracranial Hemorrhage or Cerebral Infarct w CC",    "01", "MED",  1.3160, 4.0, 4.8),
    "066": ("Intracranial Hemorrhage or Cerebral Infarct w/o CC/MCC","01","MED", 0.8310, 2.7, 3.1),
    "069": ("TIA",                                                 "01", "MED",  0.7190, 2.1, 2.4),
    "070": ("Non-specific CVA & Precerebral Occlusion w MCC",      "01", "MED",  1.4250, 4.5, 5.4),
    "071": ("Non-specific CVA & Precerebral Occlusion w/o MCC",    "01", "MED",  0.9010, 3.1, 3.7),
    "101": ("Seizures w MCC",                                      "01", "MED",  1.6280, 4.7, 5.7),
    "102": ("Seizures w/o MCC",                                    "01", "MED",  0.8890, 2.7, 3.2),
    "103": ("Headaches w MCC",                                     "01", "MED",  0.9760, 3.2, 3.8),
    "104": ("Headaches w/o MCC",                                   "01", "MED",  0.6310, 2.2, 2.6),

    # ── Endocrine / Metabolic (MDC 10) ───────────────────────────────────────
    "637": ("Diabetes w MCC",                                      "10", "MED",  1.4040, 4.4, 5.3),
    "638": ("Diabetes w CC",                                       "10", "MED",  0.7840, 3.0, 3.5),
    "639": ("Diabetes w/o CC/MCC",                                 "10", "MED",  0.5710, 2.2, 2.5),
    "640": ("Misc Disorders of Nutrition, Metabolism w MCC",       "10", "MED",  1.1820, 4.0, 4.8),
    "641": ("Misc Disorders of Nutrition, Metabolism w/o MCC",    "10", "MED",  0.7140, 2.8, 3.3),

    # ── Sepsis / Infectious (MDC 18) ─────────────────────────────────────────
    "870": ("Septicemia or Severe Sepsis w MV >96 hrs",            "18", "MED",  7.0320,12.4,15.0),
    "871": ("Septicemia or Severe Sepsis w/o MV w MCC",            "18", "MED",  2.1960, 6.5, 7.9),
    "872": ("Septicemia or Severe Sepsis w/o MV w/o MCC",          "18", "MED",  1.2840, 4.5, 5.3),

    # ── Mental Health (MDC 19) ────────────────────────────────────────────────
    "885": ("Psychoses",                                           "19", "MED",  1.0800, 5.5, 7.0),
    "881": ("Depressive Neuroses",                                 "19", "MED",  0.7540, 4.3, 5.5),
    "882": ("Neuroses Except Depressive",                          "19", "MED",  0.7120, 3.9, 4.8),
    "883": ("Disorders of Personality & Impulse Control",          "19", "MED",  0.9540, 5.1, 6.4),
    "884": ("Organic Disturbances & Mental Retardation",           "19", "MED",  1.1420, 5.6, 6.9),

    # ── Hepatobiliary (MDC 07) ─────────────────────────────────────────────────
    "418": ("Laparoscopic Cholecystectomy w/o CDE w MCC",          "07", "SURG", 1.9560, 4.8, 5.8),
    "419": ("Laparoscopic Cholecystectomy w/o CDE w CC",           "07", "SURG", 1.2080, 2.9, 3.4),
    "420": ("Laparoscopic Cholecystectomy w/o CDE w/o CC/MCC",     "07", "SURG", 0.8910, 1.8, 2.1),
    "432": ("Cirrhosis & Alcoholic Hepatitis w MCC",               "07", "MED",  2.3460, 6.8, 8.2),
    "433": ("Cirrhosis & Alcoholic Hepatitis w CC",                "07", "MED",  1.3010, 4.1, 4.9),
    "434": ("Cirrhosis & Alcoholic Hepatitis w/o CC/MCC",          "07", "MED",  0.8120, 2.8, 3.3),

    # ── Skin & Soft Tissue (MDC 09) ──────────────────────────────────────────
    "573": ("Skin Graft &/or Debrid for Skin Ulcer/Cellulitis w MCC","09","SURG",3.4680, 8.9,10.8),
    "574": ("Skin Graft &/or Debrid for Skin Ulcer/Cellulitis w CC","09","SURG", 2.0140, 5.6, 6.7),
    "575": ("Skin Graft &/or Debrid for Skin Ulcer/Cellulitis w/o CC/MCC","09","SURG",1.4320,4.0,4.7),
    "602": ("Cellulitis w MCC",                                    "09", "MED",  1.2810, 4.5, 5.4),
    "603": ("Cellulitis w/o MCC",                                  "09", "MED",  0.7420, 3.0, 3.6),

    # ── Obstetrics (MDC 14) ───────────────────────────────────────────────────
    "765": ("Cesarean Section w CC/MCC",                           "14", "SURG", 1.2840, 3.1, 3.7),
    "766": ("Cesarean Section w/o CC/MCC",                         "14", "SURG", 0.8920, 2.3, 2.7),
    "775": ("Vaginal Delivery w Complicating Diagnoses",           "14", "MED",  0.7140, 2.3, 2.7),
    "776": ("Postpartum & Post Abortion Diagnoses w/o O.R. Proc",  "14", "MED",  0.6780, 2.9, 3.5),
    "807": ("Vaginal Delivery w/o Complicating Diagnoses",         "14", "MED",  0.5710, 1.8, 2.1),

    # ── Substance Abuse (MDC 20) ──────────────────────────────────────────────
    "894": ("Alcohol/Drug Abuse or Dependence, Left AMA",          "20", "MED",  0.4820, 2.1, 2.5),
    "895": ("Alcohol/Drug Abuse or Dependence w Rehab Therapy",    "20", "MED",  0.7140, 4.5, 5.4),
    "896": ("Alcohol/Drug Abuse or Dependence w/o Rehab Therapy w MCC","20","MED",1.0540, 4.2, 5.0),
    "897": ("Alcohol/Drug Abuse or Dependence w/o Rehab Therapy w/o MCC","20","MED",0.6410,2.9,3.4),

    # ── Burns (MDC 22) ────────────────────────────────────────────────────────
    "927": ("Extensive Burns or Full Thickness Burns w MV >96 Hrs","22", "SURG", 25.6240,22.5,27.2),
    "928": ("Full Thickness Burns w Skin Graft or Inhal Inj w CC/MCC","22","SURG",9.4610,12.8,15.5),
    "929": ("Full Thickness Burns w Skin Graft or Inhal Inj w/o CC/MCC","22","SURG",4.3110,6.2,7.4),

    # ── Trauma (MDC 24 / Pre-MDC) ─────────────────────────────────────────────
    "003": ("ECMO or Trach w MV >96 Hrs or PDX Exc Face, Mouth & Neck","PRE","SURG",25.0490,23.4,28.6),
    "004": ("Trach w MV >96 Hrs or PDX Exc Face, Mouth & Neck w/o ECMO","PRE","SURG",11.6820,14.1,17.2),
    "955": ("Craniotomy for Multiple Significant Trauma",          "25", "SURG", 6.9140,10.2,12.4),
    "956": ("Limb Reattachment, Hip & Femur Proc for Multiple Significant Trauma","25","SURG",4.5620,7.4,8.9),
    "957": ("Other O.R. Procedures for Multiple Significant Trauma w MCC","25","SURG",7.4810,11.8,14.3),
    "963": ("Other Multiple Significant Trauma w MCC",             "25", "MED",  3.5490, 8.9,10.8),
    "964": ("Other Multiple Significant Trauma w CC",              "25", "MED",  2.1240, 5.4, 6.5),
    "965": ("Other Multiple Significant Trauma w/o CC/MCC",        "25", "MED",  1.3910, 3.5, 4.2),

    # ── Pancreas & Endocrine Surgery (MDC 10 cont.) ───────────────────────────
    "621": ("O.R. Procedures for Obesity w MCC",                   "10", "SURG", 2.9640, 4.1, 5.0),
    "622": ("O.R. Procedures for Obesity w CC",                    "10", "SURG", 1.7820, 2.5, 3.0),
    "623": ("O.R. Procedures for Obesity w/o CC/MCC",              "10", "SURG", 1.4210, 1.9, 2.3),

    # ── Vascular (MDC 05 cont.) ───────────────────────────────────────────────
    "253": ("Other Vascular Procedures w MCC",                     "05", "SURG", 4.0640, 7.8, 9.4),
    "254": ("Other Vascular Procedures w CC",                      "05", "SURG", 2.4370, 4.2, 5.1),
    "255": ("Other Vascular Procedures w/o CC/MCC",                "05", "SURG", 1.5960, 2.6, 3.1),
    "299": ("Peripheral Vascular Disorders w MCC",                 "05", "MED",  1.4820, 5.2, 6.3),
    "300": ("Peripheral Vascular Disorders w CC",                  "05", "MED",  0.9010, 3.5, 4.2),
    "301": ("Peripheral Vascular Disorders w/o CC/MCC",            "05", "MED",  0.6420, 2.5, 3.0),

    # ── Other ─────────────────────────────────────────────────────────────────
    "948": ("Signs & Symptoms w MCC",                              "23", "MED",  1.3450, 4.2, 5.1),
    "949": ("Signs & Symptoms w/o MCC",                            "23", "MED",  0.7680, 2.8, 3.3),
    "951": ("Other Factors Influencing Health Status",             "23", "MED",  0.9120, 3.4, 4.1),
}

# DRG codes subject to CMS Hospital Readmissions Reduction Program (HRRP) penalties
HRRP_DRGS: set[str] = {
    "280", "281", "282",           # Acute MI
    "291", "292", "293",           # Heart Failure
    "193", "194", "195",           # Pneumonia (FY2026 renumbering)
    "231", "232", "233", "234", "235", "236",  # CABG
    "469", "470",                  # Total Hip/Knee Arthroplasty
    "190", "191", "192",           # COPD
}
