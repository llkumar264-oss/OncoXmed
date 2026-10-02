"""Generate data/evaluation_report.md on a fresh synthetic cohort (separate temp DB).

    python scripts/evaluate.py [--n 1500] [--seed 11]
"""
import argparse
import os
import random
import statistics
import sys
import tempfile
from collections import Counter, defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=1500)
ap.add_argument("--seed", type=int, default=11)
a = ap.parse_args()
_t = tempfile.mkdtemp()
os.environ["ONCOREADY_DB"] = os.path.join(_t, "eval.db")
os.environ["ONCOREADY_MODEL_DIR"] = _t  # never overwrite the app's own model
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db, engine, kb, ml, synth  # noqa: E402

db.init()
synth.generate(a.n, seed=a.seed)
rows = [(p, i, e, engine.evaluate(p, i, e, {})) for p, i, e in db.load_all()]
aw = [r for r in rows if r[0]["status"] == "awaiting_consult"]
tr = [r for r in rows if r[3]["journey"]["treated"]]
L = []
w = L.append

w(f"# OncoReady evaluation report\n\nCohort: **{a.n} synthetic patients** (seed {a.seed}); {len(aw)} awaiting consult, {len(tr)} treated.\n")
w("> All figures come from synthetic data whose generator embeds the same assumptions the rules and model learn. They verify that the software behaves as specified; they are **not** evidence of clinical effectiveness.\n")

# 1. safety invariants -------------------------------------------------------
w("## 1. Triage safety invariants\n")
flagged = [r for r in rows if r[3]["red_flags"]]
p3_flagged = [r for r in flagged if r[3]["priority"]["tier"] == "P3"]
multi = [r for r in rows if len(r[3]["red_flags"]) >= 2]
p1_multi = [r for r in multi if r[3]["priority"]["tier"] == "P1"]
w(f"| Check | Result |\n|---|---|\n| Patients with ≥1 red flag | {len(flagged)} |\n| …of those placed in routine tier P3 | **{len(p3_flagged)}** (must be 0) |\n"
  f"| Patients with ≥2 red flags | {len(multi)} |\n| …of those placed in P1 | **{len(p1_multi)}/{len(multi)}** (must be all) |\n")
assert not p3_flagged and len(p1_multi) == len(multi)
w("| Tier | Awaiting patients |\n|---|---|\n" + "\n".join(f"| {t} | {n} |" for t, n in sorted(Counter(r[3]['priority']['tier'] for r in aw).items())) + "\n")

# 2. readiness vs outcome ------------------------------------------------------
w("## 2. Does record readiness track delay? (treated patients)\n")
by = defaultdict(list)
for p, i, e, ev in tr:
    d = next(x for x in ev["journey"]["intervals"] if x["key"] == "report_to_treatment")["days"]
    if d is not None and d >= 0:
        by[ev["readiness"]["band"]].append(d)
w("| Readiness band | n | Median diagnosis→treatment (d) | Over 30 d |\n|---|---|---|---|")
for b in ("ready", "nearly", "not_ready"):
    v = by[b]
    if v:
        w(f"| {b.replace('_', ' ')} | {len(v)} | {statistics.median(v):.0f} | {100 * sum(x > 30 for x in v) / len(v):.0f}% |")
w("")

# 3. model ----------------------------------------------------------------------
m = ml.train()
w("## 3. Delay-risk model (held-out test set)\n")
w(f"Target: {m['label']}; prevalence {m['prevalence']:.0%}; n={m['n_total']} ({m['n_test']} test).\n")
w("| Model | AUC | Accuracy | Precision | Recall | Brier |\n|---|---|---|---|---|---|")
for k, n in (("logistic_regression", "Logistic regression (served)"), ("gradient_boosting", "Gradient boosting")):
    x = m[k]
    w(f"| {n} | {x['auc']} | {x['accuracy']} | {x['precision']} | {x['recall']} | {x['brier']} |")
x = m["baseline_rule_wait_over_target"]
w(f"| Rule: consult wait over target | – | {x['accuracy']} | {x['precision']} | {x['recall']} | – |")
w(f"| Always 'on time' | 0.5 | {m['majority_class_accuracy']} | – | 0 | – |\n")
w(f"5-fold CV AUC (logistic): {m['cv_auc_logistic'][0]} ± {m['cv_auc_logistic'][1]}; (GBM): {m['cv_auc_gbm'][0]} ± {m['cv_auc_gbm'][1]}\n")
w("Calibration (logistic): " + "; ".join(f"{c['bin']}: predicted {c['predicted']:.0%}, observed {c['observed']:.0%} (n={c['n']})" for c in m["calibration"]) + "\n")

# 4. planner simulation ----------------------------------------------------------
w("## 4. Clinic planner vs unprioritised booking\n")
rng = random.Random(1)
pool = []
for p, i, e, ev in aw:
    pool.append(dict(id=p["id"], name=p["name"], site=p["site"], stage=p["stage"], tier=ev["priority"]["tier"], priority=ev["priority"]["score"], band=ev["readiness"]["band"],
                     missing=[dict(owner_label=m_["owner_label"], label=m_["label"], critical=m_["critical"]) for m_ in ev["readiness"]["missing"]]))
cap = 16
res = dict(naive_p1=[], plan_p1=[], naive_notready=[], plan_notready_unflagged=[])
for _ in range(300):
    sample = rng.sample(pool, min(len(pool), 60))
    naive = sample[:cap]
    plan = engine.plan_clinic(sample, "09:00", "13:00", 2)
    ids = {s["id"] for s in plan["schedule"]}
    planned = [c for c in sample if c["id"] in ids]
    res["naive_p1"].append(sum(c["tier"] == "P1" for c in naive) / max(1, sum(c["tier"] == "P1" for c in sample)))
    res["plan_p1"].append(sum(c["tier"] == "P1" for c in planned) / max(1, sum(c["tier"] == "P1" for c in sample)))
    res["naive_notready"].append(sum(c["band"] == "not_ready" and c["tier"] != "P1" for c in naive) / max(1, len(naive)))
    res["plan_notready_unflagged"].append(sum(c["band"] == "not_ready" and c["tier"] != "P1" for c in planned) / max(1, len(planned)))
mean = lambda k: 100 * statistics.mean(res[k])
w(f"300 simulated sessions, 60 waiting patients each, 2 doctors × 4 h.\n\n| Metric | Unprioritised | OncoReady |\n|---|---|---|\n"
  f"| Share of waiting P1 (urgent) patients seen | {mean('naive_p1'):.0f}% | {mean('plan_p1'):.0f}% |\n"
  f"| Non-urgent, not-ready patients occupying slots | {mean('naive_notready'):.0f}% | {mean('plan_notready_unflagged'):.0f}% |\n")
w("## 5. Known limitations\n")
w("- Rules, checklists and default time targets are authored defaults, not validated institutional protocols; the treating team must review and edit them (Settings).\n"
  "- No real patient data was available in this environment (public data hosts, including Kaggle, were unreachable), so the cohort is synthetic.\n"
  "- The model uses only consultation-time features, but its labels here come from the generator; retrain on real data and validate prospectively before any use.\n"
  "- Priority is a transparent additive score with safety floors; it supports, never replaces, clinician triage.\n")
out = os.path.join(os.path.dirname(__file__), "..", "data", "evaluation_report.md")
open(out, "w").write("\n".join(L))
print("\n".join(L))
