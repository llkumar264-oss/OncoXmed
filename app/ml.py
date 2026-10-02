"""Treatment-delay risk model.

Target: diagnosis→treatment start > 30 days (configurable). Features are limited
to what is knowable at consultation time. We train an interpretable logistic
regression (served, with per-patient driver explanations) and compare it with a
gradient-boosting model + simple rule baselines.

HONEST CAVEAT: with the bundled synthetic cohort the metrics only prove the
pipeline works. The delays in that data come from the generator's own assumptions,
so scores are not evidence of clinical validity. Retrain on real data
(scripts/train_model.py --csv ...) and validate prospectively before use.
"""
import json
import os

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

from . import db, engine, kb

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ONCOREADY_MODEL_DIR", os.path.join(HERE, "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
MODEL_PATH = os.path.join(DATA_DIR, "model.joblib")
METRICS_PATH = os.path.join(DATA_DIR, "model_metrics.json")
SITES = list(kb.SITES)
BASE = ["age", "stage", "stage_unknown", "ecog", "n_red_flags", "symptom_to_contact", "contact_to_biopsy",
        "biopsy_to_report", "report_to_consult", "facility_hops", "readiness", "distance_km"]
FEATS = BASE + [f"site_{s}" for s in SITES]
NICE = {"age": "Age", "stage": "Stage", "stage_unknown": "Stage unknown", "ecog": "ECOG", "n_red_flags": "Red-flag count",
        "symptom_to_contact": "Symptom→contact delay", "contact_to_biopsy": "Contact→biopsy delay", "biopsy_to_report": "Biopsy→report delay",
        "report_to_consult": "Report→consult wait", "facility_hops": "Facilities visited", "readiness": "Record readiness",
        "distance_km": "Distance from centre", **{f"site_{s}": f"Site: {kb.SITES[s]['label']}" for s in SITES}}
LABEL_DAYS = 30


def featurize(p, ev, medians=None):
    iv = {r["key"]: r["days"] for r in ev["journey"]["intervals"]}
    med = medians or {}
    g = lambda k: (iv.get(k) if iv.get(k) is not None else med.get(k, 10))
    row = dict(age=p.get("age") or 55, stage=p.get("stage") or 0, stage_unknown=int(p.get("stage") is None),
               ecog=p.get("ecog") if p.get("ecog") is not None else 1, n_red_flags=len(ev["red_flags"]),
               symptom_to_contact=g("symptom_to_contact"), contact_to_biopsy=g("contact_to_biopsy"),
               biopsy_to_report=g("biopsy_to_report"), report_to_consult=g("report_to_consult"),
               facility_hops=ev["journey"]["facility_hops"] or 1, readiness=ev["readiness"]["score"],
               distance_km=p.get("distance_km") or 40)
    for s in SITES:
        row[f"site_{s}"] = int(p.get("site") == s)
    return [float(row[f]) for f in FEATS]


def build_frame(today=None):
    targets = db.get_targets()
    X, y, ids, allrows = [], [], [], []
    for p, items, events in db.load_all():
        ev = engine.evaluate(p, items, events, targets, today)
        x = featurize(p, ev)
        iv = {r["key"]: r for r in ev["journey"]["intervals"]}
        r2t = iv["report_to_treatment"]
        if r2t["state"] == "done" and r2t["days"] is not None and r2t["days"] >= 0:
            X.append(x)
            y.append(int(r2t["days"] > LABEL_DAYS))
            ids.append(p["id"])
    return np.array(X), np.array(y), ids


def train(today=None, seed=7):
    X, y, ids = build_frame(today)
    data_kind = "synthetic" if all(p["synthetic"] for p, _, _ in db.load_all()) else "mixed/real"
    if len(y) < 60 or y.min() == y.max():
        raise ValueError("Need ≥60 treated patients with both delayed and non-delayed outcomes to train.")
    medians = {k: float(np.median(X[:, FEATS.index(k)])) for k in ["symptom_to_contact", "contact_to_biopsy", "biopsy_to_report", "report_to_consult"]}
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=seed)
    sc = StandardScaler().fit(Xtr)
    lr = LogisticRegression(C=0.5, max_iter=2000)
    gb = GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.06, subsample=0.8, random_state=seed)
    cv = StratifiedKFold(5, shuffle=True, random_state=seed)
    cv_lr = cross_val_score(lr, sc.transform(Xtr), ytr, cv=cv, scoring="roc_auc")
    cv_gb = cross_val_score(gb, Xtr, ytr, cv=cv, scoring="roc_auc")
    lr.fit(sc.transform(Xtr), ytr)
    gb.fit(Xtr, ytr)
    p_lr = lr.predict_proba(sc.transform(Xte))[:, 1]
    p_gb = gb.predict_proba(Xte)[:, 1]
    base_rule = (Xte[:, FEATS.index("report_to_consult")] > kb.DEFAULT_TARGETS["report_to_consult"]).astype(int)

    def block(prob, thr=0.5):
        pred = (prob >= thr).astype(int)
        return dict(auc=round(float(roc_auc_score(yte, prob)), 3), accuracy=round(float(accuracy_score(yte, pred)), 3),
                    precision=round(float(precision_score(yte, pred, zero_division=0)), 3),
                    recall=round(float(recall_score(yte, pred, zero_division=0)), 3), brier=round(float(brier_score_loss(yte, prob)), 3))
    bins = np.linspace(0, 1, 6)
    calib = []
    for a, b in zip(bins[:-1], bins[1:]):
        m = (p_lr >= a) & (p_lr < b + (1e-9 if b == 1 else 0))
        if m.sum():
            calib.append(dict(bin=f"{a:.1f}-{b:.1f}", n=int(m.sum()), predicted=round(float(p_lr[m].mean()), 3), observed=round(float(yte[m].mean()), 3)))
    coefs = sorted(((NICE[f], round(float(c), 3)) for f, c in zip(FEATS, lr.coef_[0])), key=lambda t: -abs(t[1]))
    metrics = dict(
        n_total=int(len(y)), n_train=int(len(ytr)), n_test=int(len(yte)), prevalence=round(float(y.mean()), 3), label=f"diagnosis→treatment > {LABEL_DAYS} days",
        logistic_regression=block(p_lr), gradient_boosting=block(p_gb), cv_auc_logistic=[round(float(cv_lr.mean()), 3), round(float(cv_lr.std()), 3)],
        cv_auc_gbm=[round(float(cv_gb.mean()), 3), round(float(cv_gb.std()), 3)],
        baseline_rule_wait_over_target=dict(accuracy=round(float(accuracy_score(yte, base_rule)), 3), precision=round(float(precision_score(yte, base_rule, zero_division=0)), 3),
                                            recall=round(float(recall_score(yte, base_rule, zero_division=0)), 3)),
        majority_class_accuracy=round(float(max(yte.mean(), 1 - yte.mean())), 3), calibration=calib, top_coefficients=coefs[:10],
        trained_on=data_kind,
        caveat="Metrics on the bundled synthetic cohort validate the pipeline only; they are not clinical evidence.")
    # final fit on all data for serving
    sc2 = StandardScaler().fit(X)
    lr2 = LogisticRegression(C=0.5, max_iter=2000).fit(sc2.transform(X), y)
    joblib.dump(dict(scaler=sc2, model=lr2, medians=medians, feats=FEATS), MODEL_PATH)
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)
    return metrics


_cache = {}


def load():
    if "m" not in _cache and os.path.exists(MODEL_PATH):
        _cache["m"] = joblib.load(MODEL_PATH)
    return _cache.get("m")


def reset_cache():
    _cache.clear()


def metrics():
    if os.path.exists(METRICS_PATH):
        with open(METRICS_PATH) as f:
            return json.load(f)
    return None


def predict(p, ev):
    m = load()
    if not m:
        return None
    x = np.array([featurize(p, ev, m["medians"])])
    z = m["scaler"].transform(x)[0]
    prob = float(m["model"].predict_proba([z])[0, 1])
    contrib = sorted(((NICE[f], float(c * v)) for f, c, v in zip(FEATS, m["model"].coef_[0], z)), key=lambda t: -abs(t[1]))
    drivers = [dict(factor=n, effect="raises risk" if c > 0 else "lowers risk", weight=round(abs(c), 2)) for n, c in contrib[:4] if abs(c) > 0.05]
    band = "high" if prob >= 0.5 else "moderate" if prob >= 0.25 else "low"
    return dict(probability=round(prob, 3), band=band, drivers=drivers, label=f"P(diagnosis→treatment > {LABEL_DAYS} d)")
