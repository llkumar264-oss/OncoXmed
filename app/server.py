"""OncoReady API server (Flask + SQLite). Run:  python run.py"""
import csv
import io
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory

from . import db, engine, kb, ml, synth

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
app = Flask(__name__, static_folder=STATIC, static_url_path="")
STATUSES = ["awaiting_consult", "in_treatment", "closed"]


def actor():
    return request.headers.get("X-Actor", "clinician")[:40]


def err(msg, code=400):
    return jsonify(error=msg), code


def validate(d, partial=False):
    errs = []
    if not partial or "name" in d:
        if not (d.get("name") or "").strip():
            errs.append("name is required")
    if not partial or "site" in d:
        if d.get("site") not in kb.SITES:
            errs.append(f"site must be one of {list(kb.SITES)}")
    for f, lo, hi in [("age", 0, 120), ("stage", 0, 4), ("ecog", 0, 4), ("weight_loss_pct", 0, 80), ("hb", 2, 20), ("distance_km", 0, 3000)]:
        v = d.get(f)
        if v not in (None, ""):
            try:
                if not (lo <= float(v) <= hi):
                    errs.append(f"{f} must be between {lo} and {hi}")
            except (TypeError, ValueError):
                errs.append(f"{f} must be a number")
    for f in ("symptom_onset", "consult_date"):
        if d.get(f):
            try:
                engine.pdate(d[f])
            except ValueError:
                errs.append(f"{f} must be YYYY-MM-DD")
    bad = [s for s in d.get("symptoms") or [] if s not in kb.SYMPTOM_VOCAB]
    if bad:
        errs.append(f"unknown symptoms: {bad}")
    if d.get("status") and d["status"] not in STATUSES:
        errs.append(f"status must be one of {STATUSES}")
    return errs


def clean(d):
    out = dict(d)
    for f in ("age", "stage", "ecog"):
        if f in out:
            out[f] = None if out[f] in (None, "") else int(float(out[f]))
    for f in ("weight_loss_pct", "hb", "distance_km"):
        if f in out:
            out[f] = None if out[f] in (None, "") else float(out[f])
    for f in ("symptom_onset", "consult_date"):
        if f in out and not out[f]:
            out[f] = None
    return out


def evaluate(p, items, events, targets=None):
    return engine.evaluate(p, items, events, targets if targets is not None else db.get_targets())


def summary(p, ev):
    pr = ml.predict(p, ev)
    b = ev["journey"]["bottleneck"]
    return dict(id=p["id"], mrn=p["mrn"], name=p["name"], age=p["age"], sex=p["sex"], site=p["site"], stage=p["stage"], ecog=p["ecog"],
                status=p["status"], city=p["city"], consult_date=p["consult_date"], synthetic=p["synthetic"],
                tier=ev["priority"]["tier"], priority=ev["priority"]["score"], band=ev["readiness"]["band"], readiness=ev["readiness"]["score"],
                missing=len(ev["readiness"]["missing"]), missing_critical=len(ev["readiness"]["missing_critical"]), red_flags=len(ev["red_flags"]),
                worst=ev["journey"]["worst"], bottleneck=(f"{b['label']} ({b['days']}d)" if b else None), total_days=ev["journey"]["total_days"],
                hops=ev["journey"]["facility_hops"], risk=pr["probability"] if pr else None, risk_band=pr["band"] if pr else None,
                action=ev["recommendation"]["action"])


def all_eval():
    t = db.get_targets()
    out = []
    for p, items, events in db.load_all():
        out.append((p, items, events, engine.evaluate(p, items, events, t)))
    return out


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True, patients=db.count_patients(), model=ml.load() is not None)


@app.get("/api/meta")
def meta():
    return jsonify(
        sites={k: dict(label=v["label"]) for k, v in kb.SITES.items()},
        symptoms={k: dict(label=l, urgent=u) for k, (l, u) in kb.SYMPTOM_VOCAB.items()},
        events=[dict(key=k, label=l) for k, l in kb.JOURNEY_EVENTS],
        intervals={k: dict(label=v[0], default=v[3]) for k, v in kb.INTERVALS.items()},
        targets={**kb.DEFAULT_TARGETS, **db.get_targets()}, owners=kb.OWNERS, stages=[dict(v=k, label=l) for k, l in kb.STAGE_LABELS.items()],
        checklists={k: [dict(key=i["key"], label=i["label"], critical=i["critical"]) for i in kb.site_items(k)] for k in kb.SITES},
        today=str(date.today()), synthetic_count=_synthetic_count())


def _synthetic_count():
    with db.connect() as c:
        return c.execute("SELECT COUNT(*) FROM patients WHERE synthetic=1").fetchone()[0]


# ------------------------------------------------------------------ patients
@app.get("/api/patients")
def list_patients():
    q = (request.args.get("q") or "").lower()
    rows = []
    for p, items, events, ev in all_eval():
        s = summary(p, ev)
        if q and q not in f"{p['name']} {p['mrn']} {p['city']} {p['site']}".lower():
            continue
        if request.args.get("site") and p["site"] != request.args["site"]:
            continue
        if request.args.get("tier") and s["tier"] != request.args["tier"]:
            continue
        if request.args.get("band") and s["band"] != request.args["band"]:
            continue
        if request.args.get("status") and p["status"] != request.args["status"]:
            continue
        s["rail"] = dict(dates=ev["journey"]["dates"], intervals=[dict(key=r["key"], status=r["status"], state=r["state"]) for r in ev["journey"]["intervals"]])
        rows.append(s)
    key = request.args.get("sort", "priority")
    rev = request.args.get("dir", "desc") == "desc"
    rows.sort(key=lambda r: (r.get(key) is None, r.get(key) if r.get(key) is not None else 0), reverse=rev)
    if rev:  # keep None last even when reversed
        rows.sort(key=lambda r: r.get(key) is None)
    total = len(rows)
    limit = min(int(request.args.get("limit", 100)), 500)
    off = int(request.args.get("offset", 0))
    return jsonify(total=total, rows=rows[off:off + limit])


@app.get("/api/patients/<int:pid>")
def get_patient(pid):
    r = db.load_one(pid)
    if not r:
        return err("not found", 404)
    p, items, events = r
    ev = evaluate(p, items, events)
    return jsonify(patient=p, events=events, evaluation=ev, risk=ml.predict(p, ev), brief=engine.brief(p, ev),
                   audit=db.audit(30, pid))


@app.post("/api/patients")
def create_patient():
    d = request.get_json(force=True, silent=True) or {}
    e = validate(d)
    if e:
        return err("; ".join(e))
    d = clean(d)
    d.setdefault("status", "awaiting_consult")
    d["synthetic"] = 0
    d["symptoms"] = d.get("symptoms") or []
    try:
        pid = db.save_patient(d)
    except Exception as ex:  # unique MRN etc.
        return err(str(ex))
    db.log(actor(), "create_patient", pid, d["name"])
    return jsonify(id=pid), 201


@app.put("/api/patients/<int:pid>")
def update_patient(pid):
    if not db.load_one(pid):
        return err("not found", 404)
    d = request.get_json(force=True, silent=True) or {}
    e = validate(d, partial=True)
    if e:
        return err("; ".join(e))
    d = clean(d)
    d.pop("synthetic", None)
    db.save_patient(d, pid)
    db.log(actor(), "update_patient", pid, ",".join(d))
    return jsonify(ok=True)


@app.delete("/api/patients/<int:pid>")
def del_patient(pid):
    db.delete_patient(pid)
    db.log(actor(), "delete_patient", pid)
    return jsonify(ok=True)


@app.post("/api/patients/<int:pid>/items")
def set_item(pid):
    d = request.get_json(force=True, silent=True) or {}
    r = db.load_one(pid)
    if not r:
        return err("not found", 404)
    keys = {i["key"] for i in kb.site_items(r[0]["site"])}
    if d.get("key") not in keys:
        return err("unknown checklist item")
    if d.get("status") not in ("received", "pending", "na"):
        return err("status must be received|pending|na")
    rd = d.get("received_date") or (str(date.today()) if d["status"] == "received" else None)
    db.set_item(pid, d["key"], d["status"], rd, d.get("note", ""))
    db.log(actor(), "item_" + d["status"], pid, d["key"])
    p, items, events = db.load_one(pid)
    ev = evaluate(p, items, events)
    return jsonify(evaluation=ev, risk=ml.predict(p, ev), brief=engine.brief(p, ev))


@app.post("/api/patients/<int:pid>/events")
def add_event(pid):
    d = request.get_json(force=True, silent=True) or {}
    if not db.load_one(pid):
        return err("not found", 404)
    if d.get("type") not in kb.EVENT_LABELS:
        return err("unknown event type")
    try:
        engine.pdate(d.get("date"))
        if not d.get("date"):
            raise ValueError
    except ValueError:
        return err("date must be YYYY-MM-DD")
    eid = db.add_event(pid, d["type"], d["date"], d.get("facility", ""), d.get("detail", ""))
    if d["type"] == "treatment_start":
        db.save_patient(dict(status="in_treatment"), pid)
    db.log(actor(), "add_event", pid, f"{d['type']} {d['date']}")
    return jsonify(id=eid), 201


@app.delete("/api/events/<int:eid>")
def del_event(eid):
    db.delete_event(eid)
    db.log(actor(), "delete_event", None, str(eid))
    return jsonify(ok=True)


# ------------------------------------------------------------------ brief
@app.get("/api/patients/<int:pid>/brief.txt")
def brief_txt(pid):
    r = db.load_one(pid)
    if not r:
        return err("not found", 404)
    p, items, events = r
    b = engine.brief(p, evaluate(p, items, events))
    db.log(actor(), "export_brief_txt", pid)
    return Response(engine.brief_text(b), mimetype="text/plain")


BRIEF_HTML = """<!doctype html><meta charset=utf-8><title>Consultation brief — {{b.patient.name}}</title>
<style>
body{font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif;max-width:820px;margin:24px auto;padding:0 20px;color:#14213d}
h1{font-size:20px;margin:0}h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#52606d;border-bottom:1px solid #d9e2ec;padding-bottom:4px;margin:20px 0 8px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-weight:600;font-size:12px}
.P1{background:#fde2e2;color:#9b1c1c}.P2{background:#fff0d6;color:#8a5300}.P3{background:#e1f2e8;color:#14633a}
.flag{color:#9b1c1c}li{margin:2px 0}table{border-collapse:collapse;width:100%}td,th{padding:4px 8px;border-bottom:1px solid #eef2f6;text-align:left;font-size:13px}
.muted{color:#52606d}.bar{height:8px;background:#e4ebf2;border-radius:4px;overflow:hidden;width:220px;display:inline-block;vertical-align:middle}.bar i{display:block;height:100%;background:#0f766e}
.crit{font-weight:600}.foot{margin-top:28px;font-size:11px;color:#7b8794;border-top:1px solid #d9e2ec;padding-top:8px}
@media print{body{margin:0}button{display:none}}
</style>
<div class=top><div><h1>Consultation readiness brief</h1><div><b>{{b.patient.name}}</b> · {{b.patient.mrn}}</div>
<div class=muted>{{b.patient.summary}}{% if b.patient.referring_doctor %} · Referred by {{b.patient.referring_doctor}}{% endif %}</div></div>
<div style="text-align:right"><span class="pill {{b.priority.tier}}">{{b.priority.tier}} · {{b.priority.score}}/100</span><div class=muted>{{b.priority.sla}}</div><button onclick="print()">Print</button></div></div>
<h2>Recommendation</h2><p><b>{{b.recommendation.text}}</b></p>
<p>Record readiness {{b.readiness.score}}% <span class=bar><i style="width:{{b.readiness.score}}%"></i></span> <span class=muted>({{b.readiness.band.replace('_',' ')}})</span></p>
{% if b.red_flags %}<h2>Red flags</h2><ul>{% for r in b.red_flags %}<li class=flag>⚠ {{r}}</li>{% endfor %}</ul>{% endif %}
<h2>Why this priority</h2><ul>{% for r in b.priority.reasons %}<li>+{{r.points}} — {{r.text}}</li>{% endfor %}</ul>
{% if b.missing_critical or b.missing_other %}<h2>Outstanding work-up</h2><ul>{% for m in b.missing_critical %}<li class=crit>{{m}} <span class=flag>(critical)</span></li>{% endfor %}{% for m in b.missing_other %}<li>{{m}}</li>{% endfor %}</ul>{% endif %}
<h2>Patient journey</h2><table>{% for t in b.timeline %}<tr><td style="width:110px">{{t.date}}</td><td>{{t.label}}</td></tr>{% endfor %}</table>
{% for d in b.delays %}<p class=flag>⚠ {{d.label}}: {{d.days}} days (target {{d.target}}) — {{d.status}}</p>{% endfor %}
{% for s in b.safety %}<p class=muted>• {{s.text}}</p>{% endfor %}
<h2>Information this consultation needs</h2><ul>{% for q in b.questions %}<li>{{q}}</li>{% endfor %}</ul>
{% if b.actions %}<h2>Pre-visit actions by owner</h2><table>{% for owner, its in b.actions.items() %}<tr><th style="width:150px">{{owner}}</th><td>{% for i in its %}{{i.item}}{% if i.critical %} <b class=flag>*</b>{% endif %}{% if not loop.last %}; {% endif %}{% endfor %}</td></tr>{% endfor %}</table>{% endif %}
<div class=foot>Generated {{b.generated}} by OncoReady decision support. Rule-based summary of recorded data — not a diagnosis or treatment recommendation; clinician judgement prevails.</div>"""


@app.get("/patients/<int:pid>/brief")
def brief_html(pid):
    r = db.load_one(pid)
    if not r:
        return "Not found", 404
    p, items, events = r
    b = engine.brief(p, evaluate(p, items, events))
    db.log(actor(), "view_brief", pid)
    return render_template_string(BRIEF_HTML, b=b)


# ------------------------------------------------------------------ dashboard & analytics
def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


@app.get("/api/dashboard")
def dashboard():
    rows = all_eval()
    targets = {**kb.DEFAULT_TARGETS, **db.get_targets()}
    awaiting = [(p, i, e, ev) for p, i, e, ev in rows if p["status"] == "awaiting_consult"]
    tiers = Counter(ev["priority"]["tier"] for *_, ev in awaiting)
    bands = Counter(ev["readiness"]["band"] for *_, ev in awaiting)
    iv = defaultdict(list)
    for p, i, e, ev in rows:
        for r in ev["journey"]["intervals"]:
            if r["state"] == "done" and r["days"] is not None and r["days"] >= 0:
                iv[r["key"]].append(r["days"])
    interval_stats = []
    for k, (label, *_r) in kb.INTERVALS.items():
        v = iv[k]
        interval_stats.append(dict(key=k, label=label, target=targets[k], n=len(v), median=statistics.median(v) if v else None, p90=_pct(v, .9),
                                   breach_pct=round(100 * sum(1 for x in v if x > targets[k]) / len(v)) if v else None))
    bott = Counter(ev["journey"]["bottleneck"]["label"] for *_, ev in rows if ev["journey"]["bottleneck"])
    missing = Counter()
    for p, i, e, ev in awaiting:
        for m in ev["readiness"]["missing"]:
            missing[m["label"]] += 1
    # monthly trend (treatment start month)
    by_m = defaultdict(list)
    for p, i, e, ev in rows:
        r = next(x for x in ev["journey"]["intervals"] if x["key"] == "report_to_treatment")
        if r["state"] == "done" and r["days"] is not None and r["days"] >= 0:
            by_m[r["end"][:7]].append(r["days"])
    trend = [dict(month=m, median=statistics.median(v), within=round(100 * sum(1 for x in v if x <= targets["report_to_treatment"]) / len(v)), n=len(v))
             for m, v in sorted(by_m.items())][-8:]
    urgent = sorted([summary(p, ev) for p, i, e, ev in awaiting if ev["priority"]["tier"] == "P1"], key=lambda r: -r["priority"])[:8]
    upcoming = sorted([summary(p, ev) for p, i, e, ev in awaiting if p["consult_date"]], key=lambda r: r["consult_date"])[:8]
    done = [ev for p, i, e, ev in rows if ev["journey"]["treated"]]
    return jsonify(
        totals=dict(patients=len(rows), awaiting=len(awaiting), in_treatment=len(done), unscheduled=sum(1 for p, *_ in awaiting if not p["consult_date"]),
                    red_flag_patients=sum(1 for *_, ev in awaiting if ev["red_flags"]),
                    avg_readiness=round(statistics.mean(ev["readiness"]["score"] for *_, ev in awaiting), 1) if awaiting else None,
                    within_target_pct=round(100 * sum(1 for x in by_m.values() for d in x if d <= targets["report_to_treatment"]) / max(1, sum(len(x) for x in by_m.values())))),
        tiers=dict(tiers), bands=dict(bands), intervals=interval_stats, bottlenecks=bott.most_common(), missing=missing.most_common(8),
        trend=trend, urgent=urgent, upcoming=upcoming, model=ml.metrics() and dict(auc=ml.metrics()["logistic_regression"]["auc"], trained_on=ml.metrics()["trained_on"]))


@app.get("/api/analytics")
def analytics():
    rows = all_eval()
    targets = {**kb.DEFAULT_TARGETS, **db.get_targets()}
    by_site = defaultdict(lambda: dict(n=0, ready=0, rs=[], r2t=[], red=0))
    dist_bins = defaultdict(list)
    hops = defaultdict(list)
    for p, i, e, ev in rows:
        s = by_site[p["site"]]
        s["n"] += 1
        s["rs"].append(ev["readiness"]["score"])
        s["ready"] += ev["readiness"]["band"] == "ready"
        s["red"] += bool(ev["red_flags"])
        r = next(x for x in ev["journey"]["intervals"] if x["key"] == "report_to_treatment")
        if r["state"] == "done" and r["days"] is not None and r["days"] >= 0:
            s["r2t"].append(r["days"])
            d = p.get("distance_km") or 0
            dist_bins["<25 km" if d < 25 else "25–75 km" if d < 75 else "75–150 km" if d < 150 else ">150 km"].append(r["days"])
            hops[str(ev["journey"]["facility_hops"])].append(r["days"])
    site_rows = [dict(site=k, label=kb.SITES[k]["label"], n=v["n"], readiness=round(statistics.mean(v["rs"]), 1), ready_pct=round(100 * v["ready"] / v["n"]),
                      median_dx_to_tx=statistics.median(v["r2t"]) if v["r2t"] else None, over_target_pct=round(100 * sum(1 for x in v["r2t"] if x > targets["report_to_treatment"]) / len(v["r2t"])) if v["r2t"] else None,
                      red_flag_pct=round(100 * v["red"] / v["n"])) for k, v in by_site.items()]
    order = ["<25 km", "25–75 km", "75–150 km", ">150 km"]
    dist = [dict(bin=b, median=statistics.median(dist_bins[b]), n=len(dist_bins[b])) for b in order if dist_bins[b]]
    hp = [dict(hops=k, median=statistics.median(v), n=len(v)) for k, v in sorted(hops.items())]
    return jsonify(sites=sorted(site_rows, key=lambda r: -r["n"]), distance=dist, hops=hp, model=ml.metrics())


# ------------------------------------------------------------------ planner
@app.post("/api/planner")
def planner():
    d = request.get_json(force=True, silent=True) or {}
    cands = []
    for p, i, e, ev in all_eval():
        if p["status"] != "awaiting_consult":
            continue
        if d.get("only_date") and p["consult_date"] not in (d["only_date"], None):
            continue  # keep patients booked for this day or still unscheduled
        if d.get("site") and p["site"] != d["site"]:
            continue
        cands.append(dict(id=p["id"], name=p["name"], site=p["site"], stage=p["stage"], tier=ev["priority"]["tier"], priority=ev["priority"]["score"],
                          band=ev["readiness"]["band"], missing=[dict(owner_label=m["owner_label"], label=m["label"], critical=m["critical"]) for m in ev["readiness"]["missing"]]))
    try:
        plan = engine.plan_clinic(cands, d.get("start", "09:00"), d.get("end", "13:00"), int(d.get("doctors", 1)), int(d.get("new_min", 30)), int(d.get("complex_min", 45)))
    except (ValueError, TypeError):
        return err("invalid time or numeric parameter")
    plan["candidates"] = len(cands)
    return jsonify(plan)


@app.post("/api/planner/commit")
def planner_commit():
    d = request.get_json(force=True, silent=True) or {}
    when = d.get("date")
    try:
        engine.pdate(when)
    except ValueError:
        return err("date must be YYYY-MM-DD")
    ids = [int(x) for x in d.get("patient_ids", [])]
    for pid in ids:
        db.save_patient(dict(consult_date=when), pid)
    db.log(actor(), "plan_commit", None, f"{len(ids)} patients → {when}")
    return jsonify(ok=True, updated=len(ids))


# ------------------------------------------------------------------ settings / model
@app.get("/api/settings")
def get_settings():
    return jsonify(targets={**kb.DEFAULT_TARGETS, **db.get_targets()}, defaults=kb.DEFAULT_TARGETS)


@app.put("/api/settings/targets")
def put_targets():
    d = request.get_json(force=True, silent=True) or {}
    t = {}
    for k, v in d.items():
        if k in kb.DEFAULT_TARGETS:
            try:
                v = int(v)
            except (TypeError, ValueError):
                return err(f"{k} must be an integer")
            if not 1 <= v <= 365:
                return err(f"{k} must be 1–365 days")
            t[k] = v
    db.set_setting("targets", {**db.get_targets(), **t})
    db.log(actor(), "update_targets", None, json.dumps(t))
    return jsonify(ok=True, targets={**kb.DEFAULT_TARGETS, **db.get_targets()})


@app.get("/api/model")
def model_info():
    return jsonify(metrics=ml.metrics(), features=ml.NICE, label_days=ml.LABEL_DAYS)


@app.post("/api/model/train")
def model_train():
    try:
        m = ml.train()
    except ValueError as ex:
        return err(str(ex))
    ml.reset_cache()
    db.log(actor(), "train_model", None, f"AUC={m['logistic_regression']['auc']}")
    return jsonify(metrics=m)


# ------------------------------------------------------------------ import / export
IMPORT_COLS = ["name", "age", "sex", "site", "stage", "ecog", "weight_loss_pct", "hb", "symptoms", "symptom_onset", "referring_doctor", "city", "distance_km",
               "status", "first_contact_date", "biopsy_date", "pathology_report_date", "oncology_consult_date", "treatment_start_date", "facility"]
DATE_EVENTS = {"first_contact_date": "first_contact", "biopsy_date": "biopsy", "pathology_report_date": "pathology_report",
               "oncology_consult_date": "oncology_consult", "treatment_start_date": "treatment_start"}


@app.get("/api/import/template.csv")
def import_template():
    ex = ["Sunita Sharma", 52, "F", "breast", 2, 1, 4, 11.8, "lump;fatigue", "2026-08-01", "Dr. A. Rao", "Jaipur", 35, "awaiting_consult",
          "2026-08-10", "2026-08-20", "2026-08-27", "", "", "District Hospital"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(IMPORT_COLS)
    w.writerow(ex)
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=oncoready_import_template.csv"})


@app.post("/api/import")
def import_csv():
    raw = request.get_data(as_text=True) if request.mimetype in ("text/csv", "text/plain") else None
    if raw is None and request.files.get("file"):
        raw = request.files["file"].read().decode("utf-8-sig")
    if not raw:
        return err("send CSV as the request body or a 'file' field")
    reader = csv.DictReader(io.StringIO(raw))
    ok, errors = 0, []
    for n, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        d = {k: row.get(k) or None for k in ["name", "age", "sex", "site", "stage", "ecog", "weight_loss_pct", "hb", "symptom_onset", "referring_doctor", "city", "distance_km"]}
        d["symptoms"] = [s.strip() for s in (row.get("symptoms") or "").split(";") if s.strip()]
        d["status"] = row.get("status") or ("in_treatment" if row.get("treatment_start_date") else "awaiting_consult")
        e = validate(d)
        if e:
            errors.append(dict(row=n, error="; ".join(e)))
            continue
        for f in DATE_EVENTS:
            if row.get(f):
                try:
                    engine.pdate(row[f])
                except ValueError:
                    e.append(f"{f} must be YYYY-MM-DD")
        if e:
            errors.append(dict(row=n, error="; ".join(e)))
            continue
        d = clean(d)
        d["synthetic"] = 0
        pid = db.save_patient(d)
        for f, t in DATE_EVENTS.items():
            if row.get(f):
                db.add_event(pid, t, row[f], row.get("facility", ""))
        ok += 1
    db.log(actor(), "import_csv", None, f"{ok} imported, {len(errors)} rejected")
    return jsonify(imported=ok, rejected=len(errors), errors=errors[:50])


@app.get("/api/export/patients.csv")
def export_csv():
    buf = io.StringIO()
    cols = ["mrn", "name", "age", "sex", "site", "stage", "ecog", "status", "priority_tier", "priority_score", "readiness_pct", "missing_critical", "red_flags",
            "worst_delay", "delay_risk", "consult_date"]
    w = csv.writer(buf)
    w.writerow(cols)
    for p, i, e, ev in all_eval():
        s = summary(p, ev)
        w.writerow([p["mrn"], p["name"], p["age"], p["sex"], p["site"], p["stage"], p["ecog"], p["status"], s["tier"], s["priority"], s["readiness"],
                    s["missing_critical"], s["red_flags"], s["worst"], s["risk"], p["consult_date"] or ""])
    db.log(actor(), "export_csv")
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=oncoready_registry.csv"})


@app.get("/api/patients/<int:pid>/fhir.json")
def fhir(pid):
    r = db.load_one(pid)
    if not r:
        return err("not found", 404)
    p, items, events = r
    ev = evaluate(p, items, events)
    label = kb.SITES[p["site"]]["label"]
    entries = [
        dict(resource=dict(resourceType="Patient", id=f"p{pid}", identifier=[dict(system="urn:oncoready:mrn", value=p["mrn"])], name=[dict(text=p["name"])],
                           gender={"M": "male", "F": "female"}.get(p["sex"], "unknown"))),
        dict(resource=dict(resourceType="Condition", id=f"c{pid}", subject=dict(reference=f"Patient/p{pid}"),
                           code=dict(text=f"Malignant neoplasm — {label}"), stage=[dict(summary=dict(text=f"Stage {kb.STAGE_LABELS.get(p['stage'])}"))],
                           onsetDateTime=p["symptom_onset"])),
    ]
    if p["ecog"] is not None:
        entries.append(dict(resource=dict(resourceType="Observation", status="final", code=dict(coding=[dict(system="http://loinc.org", code="89247-1", display="ECOG Performance Status score")]),
                                          subject=dict(reference=f"Patient/p{pid}"), valueInteger=p["ecog"])))
    for m in ev["readiness"]["missing"]:
        entries.append(dict(resource=dict(resourceType="ServiceRequest", status="active", intent="plan", priority="urgent" if m["critical"] else "routine",
                                          code=dict(text=m["label"]), subject=dict(reference=f"Patient/p{pid}"))))
    db.log(actor(), "export_fhir", pid)
    return jsonify(dict(resourceType="Bundle", type="collection", entry=entries, meta=dict(tag=[dict(display="FHIR R4-shaped export; not validated against national profiles")])))


# ------------------------------------------------------------------ admin
@app.get("/api/audit")
def audit():
    return jsonify(rows=db.audit(int(request.args.get("limit", 200))))


@app.post("/api/seed")
def seed():
    d = request.get_json(force=True, silent=True) or {}
    n = max(50, min(int(d.get("n", 700)), 3000))
    synth.generate(n, seed=int(d.get("seed", 42)))
    ml.train()
    ml.reset_cache()
    db.log(actor(), "seed", None, f"{n} synthetic")
    return jsonify(ok=True, patients=db.count_patients())


@app.post("/api/reset")
def reset():
    db.wipe()
    db.log(actor(), "reset")
    return jsonify(ok=True)


def create_app(seed_if_empty=True):
    db.init()
    if seed_if_empty and db.count_patients() == 0:
        synth.generate(700)
        ml.train()
    ml.reset_cache()
    return app
