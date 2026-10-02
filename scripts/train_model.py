"""Retrain the delay-risk model, optionally after importing real data.

    python scripts/train_model.py                    # retrain on whatever is in the DB
    python scripts/train_model.py --csv my_data.csv  # import rows first (see /api/import/template.csv)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db, ml  # noqa: E402
from app.server import create_app  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--csv")
a = ap.parse_args()
app = create_app(seed_if_empty=False)
if a.csv:
    r = app.test_client().post("/api/import", data=open(a.csv, encoding="utf-8-sig").read(), content_type="text/csv").json
    print("import:", {k: r[k] for k in ("imported", "rejected")}, r.get("errors", [])[:5])
print("patients in DB:", db.count_patients())
m = ml.train()
print(json.dumps({k: m[k] for k in ("n_total", "prevalence", "logistic_regression", "gradient_boosting", "trained_on")}, indent=2))
