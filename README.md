# OncoReady — Consultation Readiness & Patient Journey Review

**Track:** Cancer Care (NCG) · **Solution type:** Clinician-focused · **Use case:** Consultation Readiness & Patient Journey Review · **Entry path:** A (patient already has a doctor)

OncoReady helps an oncology clinic answer, before the first consultation, three questions for every referred patient:

1. **Is the record ready?** Site-specific work-up checklist (breast, oral/head & neck, cervix, lung, colorectal, stomach/oesophagus, prostate, ovary) with weighted scoring, critical items, and an owner for every missing item.
2. **Where did the journey stall?** Symptom → first contact → biopsy → diagnosis → consult → treatment, measured against editable time targets, with bottleneck detection and safety checks (treatment before pathology, fragmented care, repeat imaging, inconsistent dates).
3. **Who should be seen first, and what must happen before they arrive?** Transparent priority tiers (P1 48 h / P2 7 d / P3 14 d) with safety floors for red flags, a one-page consultation brief, and a clinic planner that builds the session and the prep-task list.

## Run it

```bash
pip install -r requirements.txt
python run.py            # http://127.0.0.1:8000
```
First launch creates the SQLite database, generates a **synthetic** demo cohort (700 patients) and trains the risk model (~3 s). Works fully offline.
Production: `docker build -t oncoready . && docker run -p 8000:8000 oncoready`.

Tests: `python -m unittest discover -s tests -v` (36 tests) · Evaluation report: `python scripts/evaluate.py` → `data/evaluation_report.md`

## What is in the app

| Screen | What it does |
|---|---|
| Today | Urgent queue, next booked consults, where journeys stall, most-missing items, diagnosis→treatment trend |
| Referral registry | Search/filter/sort, readiness bar, journey mini-rail, delay risk, next step; add, edit, import CSV, export CSV |
| Patient workspace | Full journey rail, step-by-step delay table, live checklist (Received / Pending / Not needed), red flags, "why this priority", delay-risk drivers, consult questions, activity |
| Consultation brief | Printable one-page HTML, copyable text, FHIR R4-shaped Bundle |
| Clinic planner | Date, doctors, slot lengths → schedule (urgent → ready → conditional), waiting list, prep tasks grouped by owner, one-click confirm bookings |
| Journey analytics | By-site readiness and delay, distance and facility-hop effects |
| Delay-risk model | Held-out metrics, calibration, coefficients, retrain button |
| Audit log / Settings | Every change and export logged; editable time targets; data import/regenerate/reset |

## Data — please read

Public datasets (Kaggle and similar) **could not be downloaded**: the environment this was built in blocks those hosts. So the bundled cohort is **synthetic** (`app/synth.py`): plausible late-presentation stage mix, multi-facility journeys, rural distance effects, incomplete records, heavy-tailed delays. Every synthetic record is flagged (MRN `SYN-…`) and the UI says so. Distributions are assumptions, not measured epidemiology.

To use real data: **Settings & data → Import patients from CSV** (template provided; dates become journey events), then `python scripts/train_model.py` or the Retrain button.

## Clinical content needs sign-off

Checklists, weights, critical flags, red-flag symptoms, priority points and the default time targets (14/14/7/7/30 days) are **authored defaults** in `app/kb.py`. They are not a validated protocol. The treating team must review them against institutional / NCG guidance before real use. Targets are editable in Settings; checklists in `kb.py`.

## Model

Logistic regression (served, with per-patient driver explanations) vs gradient boosting; target = diagnosis→treatment > 30 days; only consultation-time features. On the synthetic cohort: AUC ≈ 0.82–0.86, beating the "consult wait over target" rule and the always-on-time baseline. **These numbers only prove the pipeline works** — labels come from the generator. Retrain and validate prospectively on real data.

## Design notes

- Rule-based and explainable by construction; every priority has an itemised reason list. No generative text in clinical outputs.
- Safety floors: any red flag ⇒ at least P2; two or more ⇒ P1 (asserted in tests and in the evaluation report).
- "Not ready" never blocks an urgent patient: P1 + missing tests ⇒ "see now, test in parallel".
- Stdlib SQLite, Flask, no external front-end dependencies.

## Not included (be aware)

No authentication/roles (audit uses an `X-Actor` header), no EHR/ABDM integration, no PHI encryption at rest, FHIR export not validated against national profiles. Add these before handling real patient data.
