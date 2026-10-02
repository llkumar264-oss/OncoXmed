"""Run:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_tmp = tempfile.mkdtemp()
os.environ["ONCOREADY_DB"] = os.path.join(_tmp, "test.db")
os.environ["ONCOREADY_MODEL_DIR"] = _tmp

from app import db, engine, kb, ml, synth  # noqa: E402
from app.server import app as flask_app  # noqa: E402

TODAY = "2026-10-01"


def pt(**kw):
    base = dict(id=1, name="T", site="breast", stage=2, ecog=1, symptoms=[], symptom_onset="2026-08-01", age=55, sex="F", weight_loss_pct=0, hb=12)
    base.update(kw)
    return base


def ev(t, d, fac="A"):
    return dict(type=t, date=d, facility=fac)


class Readiness(unittest.TestCase):
    def test_empty_record_not_ready(self):
        r = engine.readiness(pt(), {}, TODAY)
        self.assertEqual(r["band"], "not_ready")
        self.assertGreaterEqual(len(r["missing_critical"]), 3)

    def test_all_received_is_ready(self):
        items = {i["key"]: dict(status="received") for i in kb.site_items("breast")}
        r = engine.readiness(pt(), items, TODAY)
        self.assertEqual((r["score"], r["band"]), (100.0, "ready"))

    def test_critical_missing_blocks_ready_even_with_high_score(self):
        items = {i["key"]: dict(status="received") for i in kb.site_items("breast")}
        items["breast_imaging"] = dict(status="pending")
        r = engine.readiness(pt(), items, TODAY)
        self.assertGreaterEqual(r["score"], 85)  # high score, yet one critical item is missing
        self.assertNotEqual(r["band"], "ready")
        self.assertEqual([m["key"] for m in r["missing_critical"]], ["breast_imaging"])

    def test_stage_gated_items_excluded_for_early_stage(self):
        keys = {i["key"] for i in engine.readiness(pt(stage=1), {}, TODAY)["items"]}
        self.assertNotIn("staging_scan", keys)
        keys2 = {i["key"] for i in engine.readiness(pt(stage=3), {}, TODAY)["items"]}
        self.assertIn("staging_scan", keys2)
        keys3 = {i["key"] for i in engine.readiness(pt(stage=None), {}, TODAY)["items"]}
        self.assertIn("staging_scan", keys3)  # unstaged => work-up still required

    def test_not_applicable_excluded_from_denominator(self):
        items = {i["key"]: dict(status="received") for i in kb.site_items("breast")}
        items["family_hx"] = dict(status="na")
        self.assertEqual(engine.readiness(pt(), items, TODAY)["score"], 100.0)

    def test_ecog_auto_satisfied(self):
        r = engine.readiness(pt(ecog=2), {}, TODAY)
        self.assertEqual(next(i for i in r["items"] if i["key"] == "ecog")["status"], "received")
        r = engine.readiness(pt(ecog=None), {}, TODAY)
        self.assertEqual(next(i for i in r["items"] if i["key"] == "ecog")["status"], "pending")


class RedFlagsAndPriority(unittest.TestCase):
    def test_flags(self):
        f = engine.red_flags(pt(ecog=3, weight_loss_pct=12, hb=7.2, symptoms=["bleeding", "lump"]))
        self.assertEqual({x["key"] for x in f}, {"bleeding", "ecog", "weight_loss", "anaemia"})

    def test_no_flags_for_benign_presentation(self):
        self.assertEqual(engine.red_flags(pt(symptoms=["lump", "fatigue"])), [])

    def _prio(self, p, items=None, events=None):
        ev_ = engine.evaluate(p, items or {}, events or [], None, TODAY)
        return ev_["priority"]

    def test_single_red_flag_never_routine(self):
        self.assertIn(self._prio(pt(stage=None, ecog=None, symptoms=["haemoptysis"], site="lung"))["tier"], ("P1", "P2"))

    def test_two_red_flags_force_p1(self):
        self.assertEqual(self._prio(pt(stage=1, symptoms=["bleeding", "airway_obstruction"], site="oral"))["tier"], "P1")

    def test_benign_early_stage_routine(self):
        self.assertEqual(self._prio(pt(stage=1, ecog=0))["tier"], "P3")

    def test_delay_raises_priority(self):
        ev_late = [ev("first_contact", "2026-08-05"), ev("biopsy", "2026-08-10"), ev("pathology_report", "2026-08-15")]
        a = self._prio(pt(stage=2), events=ev_late)  # diagnosed 47 days ago, still no consult
        b = self._prio(pt(stage=2, symptom_onset="2026-09-10"), events=[ev("first_contact", "2026-09-20"), ev("biopsy", "2026-09-22"), ev("pathology_report", "2026-09-28")])
        self.assertGreater(a["score"], b["score"])


class Journey(unittest.TestCase):
    def test_intervals_and_status(self):
        j = engine.journey(pt(symptom_onset="2026-07-01"), [ev("first_contact", "2026-07-11"), ev("biopsy", "2026-07-31"), ev("pathology_report", "2026-08-03")], None, TODAY)
        iv = {r["key"]: r for r in j["intervals"]}
        self.assertEqual(iv["symptom_to_contact"]["days"], 10)
        self.assertEqual(iv["symptom_to_contact"]["status"], "ok")
        self.assertEqual(iv["contact_to_biopsy"]["days"], 20)
        self.assertEqual(iv["contact_to_biopsy"]["status"], "watch")  # 20/14 = 1.43
        self.assertEqual(iv["biopsy_to_report"]["status"], "ok")
        # diagnosed 3 Aug, no consult yet: 59 d waiting vs 7 d target is the biggest overshoot
        self.assertEqual((j["bottleneck"]["key"], j["bottleneck"]["state"]), ("report_to_consult", "ongoing"))

    def test_status_thresholds(self):
        self.assertEqual([engine._status(d, 10) for d in (10, 15, 20, 21)], ["ok", "watch", "delayed", "critical"])

    def test_ongoing_interval_counts_to_today(self):
        j = engine.journey(pt(), [ev("first_contact", "2026-08-10"), ev("biopsy", "2026-08-12"), ev("pathology_report", "2026-09-21")], None, TODAY)
        r = next(x for x in j["intervals"] if x["key"] == "report_to_treatment")
        self.assertEqual((r["state"], r["days"]), ("ongoing", 10))

    def test_custom_targets_change_status(self):
        evs = [ev("first_contact", "2026-08-10"), ev("biopsy", "2026-08-12"), ev("pathology_report", "2026-08-14"), ev("treatment_start", "2026-09-10")]
        a = engine.journey(pt(), evs, {"report_to_treatment": 30}, TODAY)
        b = engine.journey(pt(), evs, {"report_to_treatment": 10}, TODAY)
        sa = next(x for x in a["intervals"] if x["key"] == "report_to_treatment")["status"]
        sb = next(x for x in b["intervals"] if x["key"] == "report_to_treatment")["status"]
        self.assertEqual((sa, sb), ("ok", "critical"))

    def test_treatment_before_pathology_is_safety_flag(self):
        j = engine.journey(pt(), [ev("first_contact", "2026-08-10"), ev("treatment_start", "2026-08-20")], None, TODAY)
        self.assertTrue(any(s["severity"] == "high" for s in j["safety"]))

    def test_negative_interval_flagged_not_scored(self):
        j = engine.journey(pt(symptom_onset="2026-09-01"), [ev("first_contact", "2026-08-20")], None, TODAY)
        r = j["intervals"][0]
        self.assertEqual((r["state"], r["status"]), ("inconsistent", "unknown"))

    def test_fragmentation_and_repeat_imaging(self):
        evs = [ev("first_contact", "2026-08-10", "A"), ev("imaging", "2026-08-11", "B"), ev("imaging", "2026-08-12", "C"), ev("imaging", "2026-08-13", "C")]
        j = engine.journey(pt(), evs, None, TODAY)
        self.assertEqual(j["facility_hops"], 3)
        self.assertEqual(len(j["safety"]), 2)

    def test_missing_middle_date_not_treated_as_ongoing(self):
        j = engine.journey(pt(), [ev("first_contact", "2026-08-10"), ev("pathology_report", "2026-09-01")], None, TODAY)
        self.assertEqual(next(x for x in j["intervals"] if x["key"] == "contact_to_biopsy")["state"], "missing_date")


class Planner(unittest.TestCase):
    def cand(self, i, tier, prio, band="ready", missing=0, stage=2):
        return dict(id=i, name=f"P{i}", site="breast", stage=stage, tier=tier, priority=prio, band=band,
                    missing=[dict(owner_label="Laboratory", label=f"x{k}", critical=False) for k in range(missing)])

    def test_urgent_first_then_ready_then_notready(self):
        c = [self.cand(1, "P3", 20, "ready"), self.cand(2, "P2", 50, "not_ready", 4), self.cand(3, "P1", 70, "not_ready", 2), self.cand(4, "P2", 45, "nearly", 1)]
        out = engine.plan_clinic(c, "09:00", "13:00", 1)
        self.assertEqual([s["id"] for s in out["schedule"]], [3, 4, 1, 2])
        self.assertEqual(out["schedule"][0]["tag"], "parallel_workup")

    def test_capacity_respected_and_waitlist(self):
        c = [self.cand(i, "P3", 10 + i) for i in range(10)]
        out = engine.plan_clinic(c, "09:00", "11:00", 1, new_min=30)
        self.assertEqual(len(out["schedule"]), 4)
        self.assertEqual(len(out["waitlist"]), 6)
        self.assertLessEqual(max(s["end"] for s in out["schedule"]), "11:00")

    def test_no_overlap_per_doctor(self):
        c = [self.cand(i, "P2", 40 - i, missing=i % 5) for i in range(16)]
        out = engine.plan_clinic(c, "09:00", "13:00", 2)
        for d in (1, 2):
            rows = sorted([s for s in out["schedule"] if s["doctor"] == d], key=lambda s: s["start"])
            for a, b in zip(rows, rows[1:]):
                self.assertLessEqual(a["end"], b["start"])

    def test_tasks_only_for_booked(self):
        c = [self.cand(1, "P1", 80, "not_ready", 3), self.cand(2, "P3", 10, "not_ready", 5)]
        out = engine.plan_clinic(c, "09:00", "09:30", 1)
        self.assertEqual(out["kpis"]["booked"], 1)
        self.assertEqual(out["kpis"]["task_count"], 3)


class Brief(unittest.TestCase):
    def test_brief_contents(self):
        p = pt(symptoms=["bleeding"], site="cervix")
        e = engine.evaluate(p, {}, [ev("first_contact", "2026-08-10"), ev("biopsy", "2026-08-12")], None, TODAY)
        b = engine.brief(p, e, TODAY)
        self.assertTrue(b["missing_critical"])
        self.assertIn("Active / significant bleeding", b["red_flags"])
        self.assertTrue(b["questions"])
        txt = engine.brief_text(b)
        self.assertIn("RED FLAGS", txt)
        self.assertIn("INFORMATION THIS CONSULT NEEDS", txt)


class KnowledgeBase(unittest.TestCase):
    def test_every_site_has_critical_histology_and_questions(self):
        for k, s in kb.SITES.items():
            keys = {i["key"]: i for i in s["items"]}
            self.assertTrue(keys["histology"]["critical"], k)
            self.assertTrue(s["questions"], k)
            self.assertEqual(len(keys), len(s["items"]), f"duplicate keys in {k}")
            for i in s["items"] + kb.COMMON:
                self.assertIn(i["owner"], kb.OWNERS)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init()
        db.wipe()
        synth.generate(260, seed=3)
        ml.train()
        ml.reset_cache()
        cls.c = flask_app.test_client()

    def test_registry_and_filters(self):
        r = self.c.get("/api/patients?limit=500").json
        self.assertGreaterEqual(r["total"], 260)  # other tests may add patients
        r = self.c.get("/api/patients?tier=P1&status=awaiting_consult").json
        self.assertTrue(all(x["tier"] == "P1" for x in r["rows"]))
        r = self.c.get("/api/patients?site=lung&limit=500").json
        self.assertTrue(r["rows"] and all(x["site"] == "lung" for x in r["rows"]))

    def test_create_validate_and_checklist_roundtrip(self):
        bad = self.c.post("/api/patients", json=dict(name="", site="x"))
        self.assertEqual(bad.status_code, 400)
        r = self.c.post("/api/patients", json=dict(name="Api Test", age=60, sex="F", site="breast", stage=2, ecog=1, symptoms=["lump"]))
        self.assertEqual(r.status_code, 201)
        pid = r.json["id"]
        before = self.c.get(f"/api/patients/{pid}").json["evaluation"]["readiness"]["score"]
        after = self.c.post(f"/api/patients/{pid}/items", json=dict(key="histology", status="received")).json["evaluation"]["readiness"]["score"]
        self.assertGreater(after, before)
        self.assertEqual(self.c.post(f"/api/patients/{pid}/items", json=dict(key="nonsense", status="received")).status_code, 400)
        self.assertEqual(self.c.post(f"/api/patients/{pid}/events", json=dict(type="biopsy", date="not-a-date")).status_code, 400)
        self.assertEqual(self.c.post(f"/api/patients/{pid}/events", json=dict(type="treatment_start", date="2026-09-20")).status_code, 201)
        self.assertEqual(self.c.get(f"/api/patients/{pid}").json["patient"]["status"], "in_treatment")
        self.assertEqual(self.c.delete(f"/api/patients/{pid}").status_code, 200)
        self.assertEqual(self.c.get(f"/api/patients/{pid}").status_code, 404)

    def test_import_accepts_good_rejects_bad(self):
        csv_text = ("name,age,sex,site,stage,ecog,symptoms,symptom_onset,first_contact_date,biopsy_date,pathology_report_date\n"
                    "Good Row,50,F,cervix,2,1,bleeding;lump,2026-08-01,2026-08-05,2026-08-10,2026-08-15\n"
                    "Bad Row,abc,F,nowhere,,,,,,,\n")
        r = self.c.post("/api/import", data=csv_text, content_type="text/csv").json
        self.assertEqual((r["imported"], r["rejected"]), (1, 1))

    def test_targets_validation_and_effect(self):
        self.assertEqual(self.c.put("/api/settings/targets", json=dict(report_to_treatment=0)).status_code, 400)
        self.assertEqual(self.c.put("/api/settings/targets", json=dict(report_to_treatment=45)).status_code, 200)
        self.assertEqual(self.c.get("/api/meta").json["targets"]["report_to_treatment"], 45)
        self.c.put("/api/settings/targets", json=dict(report_to_treatment=30))

    def test_planner_and_commit(self):
        r = self.c.post("/api/planner", json=dict(doctors=2, start="09:00", end="12:00")).json
        self.assertGreater(r["kpis"]["booked"], 0)
        ids = [s["id"] for s in r["schedule"]][:2]
        self.assertEqual(self.c.post("/api/planner/commit", json=dict(date="2026-10-05", patient_ids=ids)).json["updated"], 2)
        self.assertEqual(self.c.get(f"/api/patients/{ids[0]}").json["patient"]["consult_date"], "2026-10-05")
        self.assertEqual(self.c.post("/api/planner", json=dict(start="bad")).status_code, 400)

    def test_exports_and_brief_pages(self):
        pid = self.c.get("/api/patients?limit=1").json["rows"][0]["id"]
        self.assertIn("mrn", self.c.get("/api/export/patients.csv").data.decode().splitlines()[0])
        self.assertEqual(self.c.get(f"/api/patients/{pid}/fhir.json").json["resourceType"], "Bundle")
        self.assertIn("Consultation readiness brief", self.c.get(f"/patients/{pid}/brief").data.decode())
        self.assertIn("CONSULTATION BRIEF", self.c.get(f"/api/patients/{pid}/brief.txt").data.decode())

    def test_html_brief_escapes_names(self):
        pid = self.c.post("/api/patients", json=dict(name="<script>alert(1)</script>", site="lung", symptoms=[])).json["id"]
        html = self.c.get(f"/patients/{pid}/brief").data.decode()
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_audit_trail_records_changes(self):
        pid = self.c.post("/api/patients", json=dict(name="Audit Probe", site="oral", symptoms=[])).json["id"]
        self.c.post("/api/planner/commit", json=dict(date="2026-10-06", patient_ids=[pid]))
        acts = {a["action"] for a in self.c.get("/api/audit?limit=100").json["rows"]}
        self.assertTrue({"create_patient", "plan_commit"} <= acts)

    def test_dashboard_and_analytics_shapes(self):
        d = self.c.get("/api/dashboard").json
        self.assertEqual(set(d["tiers"]) <= {"P1", "P2", "P3"}, True)
        self.assertEqual(len(d["intervals"]), 5)
        self.assertTrue(self.c.get("/api/analytics").json["sites"])


class Model(unittest.TestCase):
    def test_model_beats_chance_and_outputs_valid_probability(self):
        db.init()
        if db.count_patients() < 200:
            synth.generate(400, seed=5)
        m = ml.train()
        ml.reset_cache()
        self.assertGreater(m["logistic_regression"]["auc"], 0.65)
        r = db.load_all()[0]
        out = ml.predict(r[0], engine.evaluate(*r, None, TODAY))
        self.assertTrue(0 <= out["probability"] <= 1)
        self.assertIn(out["band"], ("low", "moderate", "high"))


if __name__ == "__main__":
    unittest.main()
