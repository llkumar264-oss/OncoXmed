"""Synthetic cohort generator.

Real patient data cannot be downloaded in this environment, so this produces a
*synthetic* but structurally realistic referral cohort: late-presentation stage
mix, multi-facility journeys, rural distance effects, incomplete records and
heavy-tailed delays. Everything it creates is flagged synthetic=1.

Distributions are plausible assumptions, NOT measured epidemiology. Replace
with real data via the CSV import (see README) before drawing any conclusions.
"""
import json
import random
from datetime import date, timedelta

import numpy as np

from . import db, engine, kb

SITE_MIX = {"breast": .22, "oral": .18, "cervix": .12, "lung": .12, "colorectal": .11, "gastric": .09, "prostate": .08, "ovary": .08}
AGE = {"breast": (50, 11), "oral": (52, 12), "cervix": (50, 10), "lung": (60, 9), "colorectal": (56, 12), "gastric": (58, 11), "prostate": (68, 7), "ovary": (52, 11)}
MALE_P = {"breast": .02, "oral": .70, "cervix": 0, "lung": .75, "colorectal": .55, "gastric": .65, "prostate": 1, "ovary": 0}
STAGE_P = {"breast": [.10, .30, .38, .22], "oral": [.10, .18, .32, .40], "cervix": [.08, .30, .40, .22], "lung": [.04, .10, .30, .56],
           "colorectal": [.08, .22, .34, .36], "gastric": [.06, .14, .30, .50], "prostate": [.12, .28, .25, .35], "ovary": [.08, .10, .45, .37]}
SYMP = {"breast": ["lump", "fatigue"], "oral": ["non_healing_ulcer", "dysphagia", "weight_loss"], "cervix": ["abnormal_discharge", "abdominal_pain", "fatigue"],
        "lung": ["cough", "weight_loss", "fatigue"], "colorectal": ["change_bowel_habit", "weight_loss", "abdominal_pain"],
        "gastric": ["dysphagia", "abdominal_pain", "weight_loss"], "prostate": ["urinary_symptoms", "fatigue"], "ovary": ["abdominal_pain", "fatigue", "lump"]}
URGENT_BY_SITE = {"breast": ["severe_pain", "breathlessness"], "oral": ["bleeding", "airway_obstruction", "cannot_swallow"], "cervix": ["bleeding", "urinary_obstruction"],
                  "lung": ["haemoptysis", "breathlessness", "neuro_deficit"], "colorectal": ["bowel_obstruction", "bleeding"], "gastric": ["bleeding", "cannot_swallow", "jaundice"],
                  "prostate": ["cord_compression_signs", "urinary_obstruction"], "ovary": ["bowel_obstruction", "breathlessness"]}
FIRST_M = ["Ramesh", "Suresh", "Mahesh", "Dinesh", "Rajendra", "Mohan", "Anil", "Vijay", "Sanjay", "Kailash", "Gopal", "Bhanwar", "Hari", "Mukesh", "Arjun", "Imran", "Salim", "Harpreet"]
FIRST_F = ["Sunita", "Geeta", "Kamla", "Meena", "Radha", "Savitri", "Pooja", "Lakshmi", "Anita", "Shanti", "Rekha", "Sarita", "Fatima", "Kiran", "Nirmala", "Bimla", "Santosh", "Manju"]
LAST = ["Sharma", "Meena", "Choudhary", "Singh", "Rathore", "Gupta", "Joshi", "Bishnoi", "Khan", "Verma", "Yadav", "Jat", "Prajapat", "Kumawat", "Soni", "Bhati", "Mathur", "Saini"]
CITIES = ["Jaipur", "Jodhpur", "Bikaner", "Ajmer", "Kota", "Udaipur", "Alwar", "Sikar", "Barmer", "Nagaur", "Pali", "Jaisalmer"]
FACILITIES = ["District Hospital", "Private diagnostic centre", "Medical college OPD", "CHC / PHC", "Nursing home", "Regional cancer centre", "Private oncology clinic"]
DOCTORS = ["Dr. A. Rao", "Dr. S. Iyer", "Dr. P. Nair", "Dr. M. Kulkarni", "Dr. R. Banerjee", "Dr. F. Ahmed", "Dr. V. Chauhan", "Dr. N. Bhatt"]


def _d(x):
    return x.isoformat()


def generate(n=700, seed=42, today=None, pipeline_frac=0.25):
    rng = np.random.default_rng(seed)
    py = random.Random(seed)
    today = engine.pdate(today) or date.today()
    sites, probs = list(SITE_MIX), list(SITE_MIX.values())
    probs = np.array(probs) / sum(probs)
    conn = db.connect()
    cur = conn.cursor()
    for i in range(n):
        site = str(rng.choice(sites, p=probs))
        awaiting = rng.random() < pipeline_frac
        male = rng.random() < MALE_P[site]
        age = int(np.clip(rng.normal(*AGE[site]), 22, 89))
        stage = int(rng.choice([1, 2, 3, 4], p=STAGE_P[site]))
        stage_known = not (awaiting and rng.random() < 0.15)
        ecog = int(np.clip(round(rng.normal(0.4 + 0.33 * stage, 0.8)), 0, 4))
        wl = float(np.clip(rng.gamma(2, 1.2 + 0.9 * stage + (2 if site in ("gastric", "lung") else 0)), 0, 25))
        hb = float(np.clip(rng.normal(12.3 - 0.45 * stage, 1.5), 5.5, 16))
        pool = SYMP[site]
        symptoms = list(rng.choice(pool, size=int(rng.integers(1, len(pool) + 1)), replace=False))
        if rng.random() < 0.04 + 0.045 * stage:
            symptoms.append(str(rng.choice(URGENT_BY_SITE[site])))
        dist = float(np.clip(rng.lognormal(np.log(45), 0.9), 3, 600))
        hops = int(np.clip(1 + rng.poisson(0.9 + (0.4 if dist > 100 else 0)), 1, 4))
        facs = py.sample(FACILITIES, hops)
        # --- journey durations (days) -------------------------------------
        rural = 1 if dist > 80 else 0
        s2c = max(1, int(rng.lognormal(np.log(10 + 5 * rural), 0.8)))
        c2b = max(1, int(rng.lognormal(np.log(7 + 2 * hops), 0.6)))
        b2r = max(1, int(rng.lognormal(np.log(4.5), 0.45)))
        r2c = max(0, int(rng.lognormal(np.log(3 + 1.0 * hops), 0.6)))
        # --- completeness of records --------------------------------------
        comp = float(rng.beta(3.3, 2.2) if awaiting else rng.beta(6, 1.7))
        comp = float(np.clip(comp - 0.05 * (hops - 1), 0.1, 1))
        p = dict(stage=stage if stage_known else None, site=site, ecog=ecog if (stage_known or rng.random() < .6) else None)
        items = {}
        for it in kb.site_items(site):
            if it["min_stage"] is not None and p["stage"] is not None and p["stage"] < it["min_stage"]:
                continue
            pr = comp + (0.08 if it["critical"] else 0) - 0.03 * it["weight"] / 10
            if it["key"] == "prior_tx":
                items[it["key"]] = ("na", None) if rng.random() < 0.5 else (("received" if rng.random() < pr else "pending"), None)
            else:
                items[it["key"]] = ("received" if rng.random() < min(pr, .985) else "pending", None)
        p_tmp = dict(p)
        rd = engine.readiness(p_tmp, {k: dict(status=v[0]) for k, v in items.items()}, today)
        missing_frac = 1 - rd["score"] / 100
        # --- timeline -----------------------------------------------------
        if awaiting:
            report = today - timedelta(days=int(rng.integers(1, 40)))
            consult = (today + timedelta(days=int(rng.integers(1, 10)))) if rng.random() < .72 else None
            tx = None
            status = "awaiting_consult"
        else:
            c2t = max(1, int(rng.lognormal(np.log(10) + 1.1 * missing_frac + 0.0035 * dist + 0.12 * (hops - 1) + (0.10 if stage == 4 else 0), 0.40)))
            tx = today - timedelta(days=int(rng.integers(3, 160)))
            consult = tx - timedelta(days=c2t)
            report = consult - timedelta(days=r2c)
            status = "in_treatment"
        biopsy = report - timedelta(days=b2r)
        contact = biopsy - timedelta(days=c2b)
        onset = contact - timedelta(days=s2c)
        sex = "M" if male else "F"
        name = f"{py.choice(FIRST_M if male else FIRST_F)} {py.choice(LAST)}"
        cur.execute("INSERT INTO patients(mrn,name,age,sex,site,stage,ecog,weight_loss_pct,hb,symptoms,symptom_onset,consult_date,referring_doctor,city,distance_km,comorbidities,status,synthetic,notes,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (f"SYN-{i + 1:04d}", name, age, sex, site, p["stage"], p["ecog"], round(wl, 1), round(hb, 1), json.dumps(symptoms),
                     _d(onset), _d(consult) if (awaiting and consult) else None, py.choice(DOCTORS), py.choice(CITIES), round(dist),
                     py.choice(["", "Hypertension", "Type 2 diabetes", "COPD", "Hypertension; diabetes", "Hypothyroidism", ""]),
                     status, "Synthetic record — not a real patient", _d(today)))
        pid = cur.lastrowid
        ev = [(pid, "first_contact", _d(contact), facs[0], ""), (pid, "biopsy", _d(biopsy), facs[min(1, hops - 1)], ""),
              (pid, "pathology_report", _d(report), facs[min(1, hops - 1)], "")]
        for k in range(int(rng.integers(1, 3 + (hops > 2)))):
            ev.append((pid, "imaging", _d(contact + timedelta(days=int(rng.integers(0, max(1, c2b))))), facs[k % hops], ""))
        if not awaiting:
            ev.append((pid, "oncology_consult", _d(consult), facs[-1], ""))
            ev.append((pid, "treatment_start", _d(tx), facs[-1], ""))
        cur.executemany("INSERT INTO events(patient_id,type,date,facility,detail) VALUES(?,?,?,?,?)", ev)
        cur.executemany("INSERT INTO items(patient_id,key,status,received_date,note) VALUES(?,?,?,?,'')",
                        [(pid, k, v[0], _d(report + timedelta(days=int(rng.integers(-5, 6)))) if v[0] == "received" else None) for k, v in items.items()])
    cur.execute("INSERT INTO audit(ts,actor,action,patient_id,detail) VALUES(?,?,?,?,?)", (db.now(), "system", "seed", None, f"Generated {n} synthetic patients (seed={seed})"))
    conn.commit()
    conn.close()
    return n
