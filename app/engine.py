"""Rule-based decision-support engine: readiness, journey review, red flags,
priority triage, consultation brief and clinic planner. Pure functions, no I/O,
so everything is unit-testable and explainable."""
from datetime import date, datetime, timedelta

from . import kb

STAGE_PTS = {None: 8, 0: 0, 1: 5, 2: 8, 3: 12, 4: 14}
STATUS_ORDER = {"ok": 0, "watch": 1, "delayed": 2, "critical": 3}
STATUS_PTS = {"ok": 0, "watch": 5, "delayed": 12, "critical": 20, "unknown": 0}
ORDER = ["symptom_onset", "first_contact", "biopsy", "pathology_report", "oncology_consult", "treatment_start"]


def pdate(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _today(today):
    return pdate(today) or date.today()


# ------------------------------------------------------------------ readiness
def readiness(p, items, today=None):
    """items: {key: {status: received|pending|na, ...}}"""
    today = _today(today)
    rows, got, total = [], 0.0, 0.0
    cats = {}
    for it in kb.site_items(p.get("site")):
        stage = p.get("stage")
        if it["min_stage"] is not None and stage is not None and stage < it["min_stage"]:
            continue  # not indicated at this stage
        rec = items.get(it["key"], {})
        status = rec.get("status", "pending")
        auto = False
        if it["key"] == "ecog" and p.get("ecog") is not None:
            status, auto = "received", True
        row = dict(it, status=status, auto=auto, received_date=rec.get("received_date"), note=rec.get("note", ""),
                   owner_label=kb.OWNERS.get(it["owner"], it["owner"]))
        rows.append(row)
        if status == "na":
            continue
        total += it["weight"]
        c = cats.setdefault(it["category"], [0.0, 0.0])
        c[1] += it["weight"]
        if status == "received":
            got += it["weight"]
            c[0] += it["weight"]
    score = round(100 * got / total, 1) if total else 100.0
    missing = [r for r in rows if r["status"] == "pending"]
    crit = [r for r in missing if r["critical"]]
    if score >= 85 and not crit:
        band = "ready"
    elif score >= 60 and len(crit) <= 1:
        band = "nearly"
    else:
        band = "not_ready"
    return dict(score=score, band=band, items=rows, missing=missing, missing_critical=crit,
                by_category={k: round(100 * v[0] / v[1]) if v[1] else 100 for k, v in cats.items()})


# ------------------------------------------------------------------ red flags
def red_flags(p):
    flags = []
    for s in p.get("symptoms") or []:
        if s in kb.URGENT_SYMPTOMS:
            flags.append(dict(key=s, label=kb.SYMPTOM_VOCAB[s][0], kind="symptom"))
    if p.get("ecog") is not None and p["ecog"] >= 3:
        flags.append(dict(key="ecog", label=f"Poor performance status (ECOG {p['ecog']})", kind="clinical"))
    if (p.get("weight_loss_pct") or 0) >= 10:
        flags.append(dict(key="weight_loss", label=f"Weight loss {p['weight_loss_pct']:.0f}% of body weight", kind="clinical"))
    if p.get("hb") is not None and p["hb"] < 8:
        flags.append(dict(key="anaemia", label=f"Severe anaemia (Hb {p['hb']} g/dL)", kind="lab"))
    return flags


# ------------------------------------------------------------------ journey
def _status(days, target):
    r = days / target if target else 0
    if r <= 1:
        return "ok"
    if r <= 1.5:
        return "watch"
    if r <= 2:
        return "delayed"
    return "critical"


def journey(p, events, targets=None, today=None):
    today = _today(today)
    targets = {**kb.DEFAULT_TARGETS, **(targets or {})}
    dates = {"symptom_onset": pdate(p.get("symptom_onset"))}
    for e in sorted(events, key=lambda e: e["date"]):
        dates.setdefault(e["type"], pdate(e["date"]))
    projected = False
    if not dates.get("oncology_consult") and pdate(p.get("consult_date")):
        dates["oncology_consult"] = pdate(p["consult_date"])
        projected = True
    present_idx = [i for i, k in enumerate(ORDER) if dates.get(k)]
    out, safety = [], []
    for key, (label, a, b, _) in kb.INTERVALS.items():
        target = targets[key]
        d0, d1 = dates.get(a), dates.get(b)
        row = dict(key=key, label=label, target=target, days=None, state="unknown", status="unknown",
                   start=str(d0) if d0 else None, end=str(d1) if d1 else None, projected=False)
        if d0 and d1:
            days = (d1 - d0).days
            row.update(days=days, state="done")
            if b == "oncology_consult" and projected:
                row.update(state="scheduled", projected=True)
            if days < 0:
                row.update(status="unknown", state="inconsistent")
                safety.append(dict(severity="warn", text=f"Date inconsistency: {label} is negative ({days} d)"))
            else:
                row["status"] = _status(days, target)
        elif d0 and not d1:
            later = [i for i in present_idx if i > ORDER.index(b)]
            if later:
                row["state"] = "missing_date"
            else:
                days = (today - d0).days
                row.update(days=days, state="ongoing", status=_status(max(days, 0), target), end=None)
        out.append(row)
    known = [r for r in out if r["days"] is not None and r["status"] in STATUS_ORDER]
    bottleneck = None
    over = [(r["days"] - r["target"], r) for r in known if r["days"] > r["target"]]
    if over:
        bottleneck = max(over, key=lambda x: x[0])[1]
    worst = max((r["status"] for r in known), key=lambda s: STATUS_ORDER[s], default="unknown")
    hops = len({e.get("facility") for e in events if e.get("facility")})
    img = sum(1 for e in events if e["type"] == "imaging")
    if dates.get("treatment_start") and (not dates.get("pathology_report") or dates["treatment_start"] < dates["pathology_report"]):
        safety.append(dict(severity="high", text="Treatment started without / before a documented pathology report — verify tissue diagnosis"))
    if hops >= 3:
        safety.append(dict(severity="info", text=f"Care fragmented across {hops} facilities — records likely incomplete; request consolidation"))
    if img >= 3:
        safety.append(dict(severity="info", text=f"{img} imaging studies recorded — check for duplicate / repeat imaging"))
    start = dates.get("symptom_onset") or dates.get("first_contact")
    end = dates.get("treatment_start") or today
    total = (end - start).days if start else None
    return dict(intervals=out, bottleneck=bottleneck, worst=worst, facility_hops=hops, safety=safety,
                total_days=total, dates={k: str(v) for k, v in dates.items() if v}, treated=bool(dates.get("treatment_start")))


# ------------------------------------------------------------------ priority
def priority(p, red, jr, rd):
    reasons, pts = [], 0.0
    n = len(red)
    if n:
        v = min(n, 3) / 3 * 40
        pts += v
        reasons.append((round(v), f"{n} clinical red flag(s): " + "; ".join(r["label"] for r in red[:3])))
    v = STAGE_PTS.get(p.get("stage"), 8)
    pts += v
    reasons.append((v, f"Stage {kb.STAGE_LABELS.get(p.get('stage'))}" + (" (unstaged — uncertainty counted)" if p.get("stage") is None else "")))
    dv = STATUS_PTS.get(jr["worst"], 0)
    if dv:
        pts += dv
        b = jr["bottleneck"]
        reasons.append((dv, f"Journey delay: {b['label']} {b['days']} d vs {b['target']} d target" if b else "Journey running late"))
    ev = {None: 0, 0: 0, 1: 0, 2: 5, 3: 10, 4: 10}.get(p.get("ecog"), 0)
    if ev:
        pts += ev
        reasons.append((ev, f"ECOG {p['ecog']}"))
    if (p.get("age") or 0) >= 70:
        pts += 3
        reasons.append((3, "Age ≥ 70"))
    pts = min(100, round(pts))
    # Safety floor: a red flag must never leave a patient in the routine tier.
    if n >= 2 and pts < 55:
        reasons.append((55 - pts, "Two or more red flags: minimum priority P1"))
        pts = 55
    elif n == 1 and pts < 35:
        reasons.append((35 - pts, "Any red flag: minimum priority P2"))
        pts = 35
    if pts >= 55:
        tier, sla = "P1", "See within 48 h"
    elif pts >= 35:
        tier, sla = "P2", "See within 7 days"
    else:
        tier, sla = "P3", "See within 14 days"
    return dict(score=pts, tier=tier, sla=sla, reasons=[dict(points=a, text=b) for a, b in reasons])


def recommendation(tier, rd, red):
    crit = [r["label"] for r in rd["missing_critical"]]
    if tier == "P1":
        if rd["band"] == "ready":
            return dict(action="see_now", text="Book the earliest slot — records are complete.")
        return dict(action="parallel", text="See urgently; do NOT wait for tests — order missing items in parallel" + (f" ({', '.join(crit[:2])})." if crit else "."))
    if rd["band"] == "ready":
        return dict(action="book", text="Ready for consultation — book within SLA.")
    if rd["band"] == "nearly":
        return dict(action="book_conditional", text="Book, but chase the outstanding items before the visit" + (f": {', '.join(crit)}." if crit else "."))
    return dict(action="prepare", text="Hold the slot and complete critical work-up first" + (f": {', '.join(crit[:3])}." if crit else "."))


def evaluate(p, items, events, targets=None, today=None):
    rd = readiness(p, items, today)
    red = red_flags(p)
    jr = journey(p, events, targets, today)
    pr = priority(p, red, jr, rd)
    rec = recommendation(pr["tier"], rd, red)
    return dict(readiness=rd, red_flags=red, journey=jr, priority=pr, recommendation=rec)


# ------------------------------------------------------------------ brief
def one_liner(p):
    site = kb.SITES.get(p.get("site"), {}).get("label", p.get("site"))
    sx = {"F": "F", "M": "M"}.get(p.get("sex"), "")
    st = kb.STAGE_LABELS.get(p.get("stage"))
    ec = f"ECOG {p['ecog']}" if p.get("ecog") is not None else "ECOG not recorded"
    return f"{p.get('age', '?')}{sx} · Ca {site} · stage {st} · {ec}"


def brief(p, ev, today=None):
    rd, jr, pr = ev["readiness"], ev["journey"], ev["priority"]
    site = kb.SITES.get(p.get("site"), {})
    timeline = [dict(label=kb.EVENT_LABELS.get(k, k.replace("_", " ").title()), date=d)
                for k, d in sorted(jr["dates"].items(), key=lambda kv: kv[1])]
    timeline = [dict(label="Symptom onset" if t["label"].lower().startswith("symptom") else t["label"], date=t["date"]) for t in timeline]
    delays = [r for r in jr["intervals"] if r["status"] in ("watch", "delayed", "critical")]
    actions = {}
    for m in rd["missing"]:
        actions.setdefault(m["owner_label"], []).append(dict(item=m["label"], critical=m["critical"]))
    return dict(
        patient=dict(id=p["id"], name=p["name"], mrn=p.get("mrn"), summary=one_liner(p),
                     referring_doctor=p.get("referring_doctor"), city=p.get("city")),
        priority=pr, recommendation=ev["recommendation"],
        readiness=dict(score=rd["score"], band=rd["band"]),
        red_flags=[r["label"] for r in ev["red_flags"]],
        missing_critical=[m["label"] for m in rd["missing_critical"]],
        missing_other=[m["label"] for m in rd["missing"] if not m["critical"]],
        timeline=timeline, delays=delays, bottleneck=jr["bottleneck"], safety=jr["safety"],
        questions=site.get("questions", []), actions=actions,
        generated=str(_today(today)),
    )


def brief_text(b):
    L = [f"CONSULTATION BRIEF — {b['patient']['name']} ({b['patient']['mrn']})",
         b["patient"]["summary"],
         f"Priority {b['priority']['tier']} ({b['priority']['score']}/100) — {b['priority']['sla']}",
         f"Readiness {b['readiness']['score']}% [{b['readiness']['band'].replace('_', ' ')}] — {b['recommendation']['text']}", ""]
    if b["red_flags"]:
        L += ["RED FLAGS"] + [f" ! {x}" for x in b["red_flags"]] + [""]
    if b["missing_critical"]:
        L += ["MISSING — CRITICAL"] + [f" - {x}" for x in b["missing_critical"]] + [""]
    if b["missing_other"]:
        L += ["MISSING — OTHER"] + [f" - {x}" for x in b["missing_other"]] + [""]
    L += ["JOURNEY"] + [f" {t['date']}  {t['label']}" for t in b["timeline"]]
    for d in b["delays"]:
        L.append(f" ⚠ {d['label']}: {d['days']} d (target {d['target']} d) — {d['status']}")
    if b["safety"]:
        L += ["", "SAFETY NOTES"] + [f" - {s['text']}" for s in b["safety"]]
    L += ["", "INFORMATION THIS CONSULT NEEDS"] + [f" ? {q}" for q in b["questions"]]
    return "\n".join(L)


# ------------------------------------------------------------------ clinic planner
def _hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def plan_clinic(cands, start="09:00", end="13:00", doctors=1, new_min=30, complex_min=45):
    """cands: list of dict(id,name,site,tier,priority,band,missing(list of dict owner_label,label,critical),stage)."""
    t0, t1 = _mins(start), _mins(end)
    doctors = max(1, int(doctors))
    rank = lambda c: (-c["priority"], c["id"])
    urgent = sorted([c for c in cands if c["tier"] == "P1"], key=rank)
    ready = sorted([c for c in cands if c["tier"] != "P1" and c["band"] in ("ready", "nearly")], key=rank)
    notready = sorted([c for c in cands if c["tier"] != "P1" and c["band"] == "not_ready"], key=rank)
    queue = [(c, "parallel_workup" if c["band"] != "ready" else "ready") for c in urgent] + \
            [(c, "ready" if c["band"] == "ready" else "conditional") for c in ready] + \
            [(c, "conditional") for c in notready]
    cursors = [t0] * doctors
    sched, wait = [], []
    for c, tag in queue:
        dur = complex_min if (len(c["missing"]) >= 4 or ((c.get("stage") or 0) >= 3 and len(c["missing"]) >= 2)) else new_min
        d = min(range(doctors), key=lambda i: cursors[i])
        if cursors[d] + dur > t1:
            wait.append(dict(id=c["id"], name=c["name"], tier=c["tier"], band=c["band"], reason="No capacity left in this session"))
            continue
        sched.append(dict(doctor=d + 1, id=c["id"], name=c["name"], tier=c["tier"], band=c["band"], tag=tag,
                          start=_hm(cursors[d]), end=_hm(cursors[d] + dur), minutes=dur, priority=c["priority"],
                          n_missing=len(c["missing"])))
        cursors[d] += dur
    sched.sort(key=lambda s: (s["start"], s["doctor"]))
    booked_ids = {s["id"] for s in sched}
    tasks = {}
    for c in cands:
        if c["id"] not in booked_ids:
            continue
        for m in c["missing"]:
            tasks.setdefault(m["owner_label"], []).append(dict(patient_id=c["id"], patient=c["name"], item=m["label"], critical=m["critical"]))
    used = sum(s["minutes"] for s in sched)
    cap = (t1 - t0) * doctors
    return dict(schedule=sched, waitlist=wait, tasks=tasks,
                kpis=dict(booked=len(sched), waitlisted=len(wait), urgent_booked=sum(1 for s in sched if s["tier"] == "P1"),
                          conditional=sum(1 for s in sched if s["tag"] in ("conditional", "parallel_workup")),
                          utilisation=round(100 * used / cap) if cap else 0, task_count=sum(len(v) for v in tasks.values())))
