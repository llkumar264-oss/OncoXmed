"""Clinical knowledge base for OncoReady.

IMPORTANT: everything here is an editable, rule-based *decision-support default*
authored for this prototype. It must be reviewed and signed off by the treating
oncology team (ideally against their institutional / NCG protocols) before
any real-world use. Nothing here is a treatment recommendation.
"""

# ---------------------------------------------------------------- journey
JOURNEY_EVENTS = [
    ("first_contact", "First medical contact"),
    ("imaging", "Imaging"),
    ("biopsy", "Biopsy / tissue sampling"),
    ("pathology_report", "Pathology report (diagnosis)"),
    ("oncology_consult", "Oncology consultation"),
    ("treatment_start", "Treatment start"),
]
EVENT_LABELS = dict(JOURNEY_EVENTS)

# Interval definitions: key -> (label, start_event, end_event, default target days)
INTERVALS = {
    "symptom_to_contact": ("Symptom onset → first contact", "symptom_onset", "first_contact", 14),
    "contact_to_biopsy": ("First contact → biopsy", "first_contact", "biopsy", 14),
    "biopsy_to_report": ("Biopsy → pathology report", "biopsy", "pathology_report", 7),
    "report_to_consult": ("Pathology report → oncology consult", "pathology_report", "oncology_consult", 7),
    "report_to_treatment": ("Diagnosis → treatment start", "pathology_report", "treatment_start", 30),
}
DEFAULT_TARGETS = {k: v[3] for k, v in INTERVALS.items()}

# ---------------------------------------------------------------- red flags
SYMPTOM_VOCAB = {
    "bleeding": ("Active / significant bleeding", True),
    "airway_obstruction": ("Stridor / airway compromise", True),
    "cannot_swallow": ("Unable to swallow liquids / saliva", True),
    "cord_compression_signs": ("Back pain with limb weakness / sphincter change", True),
    "bowel_obstruction": ("Features of bowel obstruction", True),
    "jaundice": ("Obstructive jaundice", True),
    "neuro_deficit": ("New focal neuro deficit / seizure", True),
    "urinary_obstruction": ("Anuria / hydronephrosis symptoms", True),
    "haemoptysis": ("Haemoptysis", True),
    "fever": ("Fever (possible neutropenic / infective)", True),
    "severe_pain": ("Uncontrolled pain", True),
    "breathlessness": ("Breathlessness at rest", True),
    "lump": ("Palpable lump / mass", False),
    "weight_loss": ("Unintentional weight loss", False),
    "fatigue": ("Fatigue", False),
    "cough": ("Persistent cough", False),
    "change_bowel_habit": ("Change in bowel habit", False),
    "non_healing_ulcer": ("Non-healing ulcer", False),
    "dysphagia": ("Difficulty swallowing", False),
    "abnormal_discharge": ("Abnormal discharge / PV bleeding spotting", False),
    "urinary_symptoms": ("Urinary symptoms", False),
    "abdominal_pain": ("Abdominal pain", False),
}
URGENT_SYMPTOMS = {k for k, (_, u) in SYMPTOM_VOCAB.items() if u}

# ---------------------------------------------------------------- checklists
# (key, label, category, weight, critical, min_stage, owner, hint)
def I(key, label, cat, weight, critical=False, min_stage=None, owner="referring_doctor", hint=""):
    return dict(key=key, label=label, category=cat, weight=weight, critical=critical,
                min_stage=min_stage, owner=owner, hint=hint)


COMMON = [
    I("referral", "Referral letter / treating-doctor summary", "Documents", 3, False, None, "referring_doctor"),
    I("ecog", "Performance status (ECOG) recorded", "Clinical", 3, False, None, "referring_doctor",
      "Auto-satisfied when ECOG is entered on the patient record"),
    I("med_list", "Current medications & comorbidity list", "Clinical", 2, False, None, "patient"),
    I("labs", "Recent CBC, LFT, KFT (within 30 days)", "Labs", 4, False, None, "lab"),
    I("prior_tx", "Prior treatment / surgery / outside-hospital records", "Documents", 2, False, None, "patient",
      "Mark 'not applicable' if none"),
    I("caregiver", "Caregiver / contact details confirmed", "Logistics", 1, False, None, "front_desk"),
]

SITES = {
    "breast": {
        "label": "Breast",
        "items": [
            I("histology", "Core biopsy histopathology report", "Pathology", 10, True, None, "pathology"),
            I("receptors", "ER / PR / HER2 immunohistochemistry", "Pathology", 9, True, None, "pathology",
              "Needed before any systemic-vs-surgery-first decision"),
            I("breast_imaging", "Mammogram + breast/axillary ultrasound (or MRI)", "Imaging", 7, True, None, "radiology"),
            I("staging_scan", "Staging imaging (CT chest/abd or PET-CT; bone scan)", "Imaging", 6, False, 2, "radiology",
              "Usually indicated from stage II/node-positive upward"),
            I("echo", "Baseline echocardiogram / LVEF", "Cardiac", 3, False, 2, "cardiology"),
            I("family_hx", "Family history / genetic risk screen", "Clinical", 2, False, None, "patient"),
        ],
        "questions": [
            "Is receptor status (ER/PR/HER2) confirmed on core biopsy rather than only cytology?",
            "Is axillary nodal status established (imaging ± sampling)?",
            "Does the patient have a baseline cardiac assessment if anthracycline/HER2 therapy is likely?",
            "Is breast-conserving surgery feasible, or is neoadjuvant therapy the question?",
        ],
    },
    "oral": {
        "label": "Oral cavity / head & neck",
        "items": [
            I("histology", "Biopsy histopathology report", "Pathology", 10, True, None, "pathology"),
            I("primary_imaging", "CECT / MRI of primary site and neck", "Imaging", 8, True, None, "radiology"),
            I("chest_imaging", "Chest imaging (CT / X-ray) for metastasis screen", "Imaging", 5, False, 2, "radiology"),
            I("dental", "Dental evaluation / extraction plan if RT likely", "Dental", 4, False, None, "dental"),
            I("nutrition", "Nutrition & swallow assessment", "Supportive", 3, False, None, "dietitian"),
            I("tobacco_hx", "Tobacco / alcohol history & cessation counselling", "Clinical", 2, False, None, "patient"),
        ],
        "questions": [
            "Is the lesion resectable on imaging — depth of invasion / bone / nodal involvement?",
            "Is the airway secure, and is nutrition adequate (consider feeding access)?",
            "Is a dental clearance needed before radiotherapy?",
        ],
    },
    "cervix": {
        "label": "Cervix",
        "items": [
            I("histology", "Cervical biopsy histopathology report", "Pathology", 10, True, None, "pathology"),
            I("pelvic_exam", "Documented pelvic / EUA findings (FIGO clinical stage)", "Clinical", 6, True, None, "referring_doctor"),
            I("mri_pelvis", "MRI pelvis (local extent / parametrium)", "Imaging", 8, True, None, "radiology"),
            I("systemic_imaging", "CECT chest/abdomen or PET-CT (nodes / distant)", "Imaging", 6, False, 2, "radiology"),
            I("viral_screen", "HIV / HBV / HCV serology", "Labs", 3, False, None, "lab"),
            I("renal_check", "Renal function / hydronephrosis check", "Labs", 4, False, 2, "lab"),
        ],
        "questions": [
            "Is FIGO stage assigned with imaging-supported nodal assessment?",
            "Is there hydronephrosis or impaired renal function that changes the plan?",
            "Is the patient anaemic enough to need correction before chemoradiation?",
        ],
    },
    "lung": {
        "label": "Lung",
        "items": [
            I("histology", "Biopsy / cytology with histologic subtype", "Pathology", 10, True, None, "pathology"),
            I("ct_chest", "CECT chest + upper abdomen", "Imaging", 8, True, None, "radiology"),
            I("biomarkers", "Molecular / PD-L1 testing (EGFR, ALK, ROS1, PD-L1) if non-small-cell", "Pathology", 8, True, None, "pathology",
              "Turnaround is long — start early"),
            I("brain_imaging", "Brain MRI / CT", "Imaging", 5, False, 2, "radiology"),
            I("pft", "Pulmonary function tests", "Cardiopulmonary", 4, False, None, "pulmonology"),
            I("pet_ct", "PET-CT where it would change management", "Imaging", 3, False, 2, "radiology"),
        ],
        "questions": [
            "Is histologic subtype confirmed, and are driver mutations / PD-L1 tested or pending?",
            "Is the intent curative or palliative given stage and fitness?",
            "Is the patient fit for the planned modality (PFT, ECOG)?",
        ],
    },
    "colorectal": {
        "label": "Colorectal",
        "items": [
            I("histology", "Colonoscopy biopsy histopathology report", "Pathology", 10, True, None, "pathology"),
            I("ct_staging", "CECT chest/abdomen/pelvis", "Imaging", 8, True, None, "radiology"),
            I("cea", "Baseline CEA", "Labs", 4, False, None, "lab"),
            I("mmr", "MMR / MSI status", "Pathology", 4, False, None, "pathology"),
            I("rectal_mri", "MRI rectum (if rectal primary)", "Imaging", 7, False, 1, "radiology"),
            I("nutrition", "Nutrition assessment", "Supportive", 2, False, None, "dietitian"),
        ],
        "questions": [
            "Colon or rectum — and is MRI-based local staging available if rectal?",
            "Is there obstruction or bleeding needing urgent surgical review?",
            "Are MMR/MSI and baseline CEA available?",
        ],
    },
    "gastric": {
        "label": "Stomach / oesophagus",
        "items": [
            I("histology", "Endoscopic biopsy histopathology report", "Pathology", 10, True, None, "pathology"),
            I("ct_staging", "CECT chest/abdomen (± EUS / PET-CT)", "Imaging", 8, True, None, "radiology"),
            I("her2", "HER2 / MMR testing", "Pathology", 5, False, None, "pathology"),
            I("nutrition", "Nutrition assessment & feeding plan", "Supportive", 5, True, None, "dietitian"),
            I("cardiac_fit", "Cardiac / anaesthetic fitness", "Cardiac", 3, False, 1, "cardiology"),
            I("laparoscopy", "Staging laparoscopy decision (if resectable on CT)", "Procedure", 2, False, 2, "surgery"),
        ],
        "questions": [
            "Is the patient nutritionally fit for major surgery or chemotherapy?",
            "Is the disease resectable on imaging; is staging laparoscopy needed?",
            "Is there obstruction / bleeding needing urgent intervention?",
        ],
    },
    "prostate": {
        "label": "Prostate",
        "items": [
            I("histology", "Biopsy histopathology with Gleason / ISUP grade", "Pathology", 10, True, None, "pathology"),
            I("psa", "Baseline PSA", "Labs", 7, True, None, "lab"),
            I("mri_prostate", "Multiparametric MRI prostate", "Imaging", 6, False, None, "radiology"),
            I("bone_scan", "Bone scan / PSMA PET (intermediate-/high-risk)", "Imaging", 6, False, 2, "radiology"),
            I("testosterone", "Serum testosterone (if hormone therapy likely)", "Labs", 2, False, 3, "lab"),
            I("urinary_fn", "Urinary & sexual function baseline", "Clinical", 2, False, None, "referring_doctor"),
        ],
        "questions": [
            "What is the risk group (PSA, grade, clinical stage)?",
            "Is systemic staging indicated by risk group, and is it done?",
            "What is life expectancy / comorbidity context for active treatment vs surveillance?",
        ],
    },
    "ovary": {
        "label": "Ovary",
        "items": [
            I("histology", "Histopathology / cytology confirming primary", "Pathology", 10, True, None, "pathology"),
            I("ca125", "CA-125 (± CEA, CA19-9, AFP/hCG in young patients)", "Labs", 6, True, None, "lab"),
            I("ct_abd_pelvis", "CECT chest/abdomen/pelvis", "Imaging", 8, True, None, "radiology"),
            I("brca", "BRCA / HRD germline-somatic testing plan", "Genetics", 5, False, None, "pathology"),
            I("surgical_review", "Documented resectability / surgical opinion", "Procedure", 5, False, 2, "surgery"),
            I("albumin", "Nutrition / albumin status", "Supportive", 2, False, 3, "dietitian"),
        ],
        "questions": [
            "Is primary cytoreduction feasible, or is neoadjuvant chemotherapy the question?",
            "Is tissue diagnosis (not just cytology/markers) available?",
            "Has germline/somatic testing been planned?",
        ],
    },
}

OWNERS = {
    "referring_doctor": "Referring doctor",
    "patient": "Patient / family",
    "lab": "Laboratory",
    "radiology": "Radiology",
    "pathology": "Pathology",
    "dental": "Dental",
    "dietitian": "Dietitian",
    "cardiology": "Cardiology",
    "pulmonology": "Pulmonology",
    "surgery": "Surgery",
    "front_desk": "Front desk",
}

STAGE_LABELS = {None: "Unknown", 0: "0", 1: "I", 2: "II", 3: "III", 4: "IV"}


def site_items(site):
    s = SITES.get(site)
    return COMMON + (s["items"] if s else [])
