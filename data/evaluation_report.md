# OncoReady evaluation report

Cohort: **1500 synthetic patients** (seed 11); 374 awaiting consult, 1126 treated.

> All figures come from synthetic data whose generator embeds the same assumptions the rules and model learn. They verify that the software behaves as specified; they are **not** evidence of clinical effectiveness.

## 1. Triage safety invariants

| Check | Result |
|---|---|
| Patients with ≥1 red flag | 729 |
| …of those placed in routine tier P3 | **0** (must be 0) |
| Patients with ≥2 red flags | 158 |
| …of those placed in P1 | **158/158** (must be all) |

| Tier | Awaiting patients |
|---|---|
| P1 | 56 |
| P2 | 162 |
| P3 | 156 |

## 2. Does record readiness track delay? (treated patients)

| Readiness band | n | Median diagnosis→treatment (d) | Over 30 d |
|---|---|---|---|
| ready | 495 | 19 | 15% |
| nearly | 409 | 24 | 28% |
| not ready | 222 | 32 | 55% |

## 3. Delay-risk model (held-out test set)

Target: diagnosis→treatment > 30 days; prevalence 28%; n=1126 (282 test).

| Model | AUC | Accuracy | Precision | Recall | Brier |
|---|---|---|---|---|---|
| Logistic regression (served) | 0.859 | 0.823 | 0.7 | 0.628 | 0.129 |
| Gradient boosting | 0.865 | 0.844 | 0.75 | 0.654 | 0.122 |
| Rule: consult wait over target | – | 0.734 | 0.523 | 0.436 | – |
| Always 'on time' | 0.5 | 0.723 | – | 0 | – |

5-fold CV AUC (logistic): 0.869 ± 0.03; (GBM): 0.854 ± 0.041

Calibration (logistic): 0.0-0.2: predicted 7%, observed 7% (n=151); 0.2-0.4: predicted 30%, observed 24% (n=49); 0.4-0.6: predicted 51%, observed 64% (n=31); 0.6-0.8: predicted 70%, observed 60% (n=25); 0.8-1.0: predicted 92%, observed 81% (n=26)

## 4. Clinic planner vs unprioritised booking

300 simulated sessions, 60 waiting patients each, 2 doctors × 4 h.

| Metric | Unprioritised | OncoReady |
|---|---|---|
| Share of waiting P1 (urgent) patients seen | 27% | 96% |
| Non-urgent, not-ready patients occupying slots | 37% | 0% |

## 5. Known limitations

- Rules, checklists and default time targets are authored defaults, not validated institutional protocols; the treating team must review and edit them (Settings).
- No real patient data was available in this environment (public data hosts, including Kaggle, were unreachable), so the cohort is synthetic.
- The model uses only consultation-time features, but its labels here come from the generator; retrain on real data and validate prospectively before any use.
- Priority is a transparent additive score with safety floors; it supports, never replaces, clinician triage.
