"""SQLite persistence layer (stdlib only)."""
import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("ONCOREADY_DB", os.path.join(os.path.dirname(__file__), "..", "data", "oncoready.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mrn TEXT UNIQUE, name TEXT NOT NULL, age INTEGER, sex TEXT,
  site TEXT NOT NULL, stage INTEGER, ecog INTEGER, weight_loss_pct REAL, hb REAL,
  symptoms TEXT DEFAULT '[]', symptom_onset TEXT, consult_date TEXT, referring_doctor TEXT, city TEXT,
  distance_km REAL, comorbidities TEXT DEFAULT '', status TEXT DEFAULT 'awaiting_consult',
  synthetic INTEGER DEFAULT 0, notes TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS items(
  patient_id INTEGER, key TEXT, status TEXT, received_date TEXT, note TEXT DEFAULT '',
  PRIMARY KEY(patient_id,key), FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, type TEXT, date TEXT, facility TEXT, detail TEXT DEFAULT '',
  FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, patient_id INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_events_p ON events(patient_id);
CREATE INDEX IF NOT EXISTS ix_status ON patients(status);
"""

PATIENT_FIELDS = ["mrn", "name", "age", "sex", "site", "stage", "ecog", "weight_loss_pct", "hb", "symptoms",
                  "symptom_onset", "consult_date", "referring_doctor", "city", "distance_km", "comorbidities",
                  "status", "synthetic", "notes"]


def connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with connect() as c:
        c.executescript(SCHEMA)


def _p(row):
    d = dict(row)
    d["symptoms"] = json.loads(d.get("symptoms") or "[]")
    return d


def now():
    return datetime.now().isoformat(timespec="seconds")


def count_patients():
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM patients").fetchone()[0]


def load_all():
    """Return list of (patient, items, events) for everyone — single pass."""
    with connect() as c:
        pts = [_p(r) for r in c.execute("SELECT * FROM patients ORDER BY id")]
        items, events = {}, {}
        for r in c.execute("SELECT * FROM items"):
            items.setdefault(r["patient_id"], {})[r["key"]] = dict(status=r["status"], received_date=r["received_date"], note=r["note"])
        for r in c.execute("SELECT * FROM events ORDER BY date"):
            events.setdefault(r["patient_id"], []).append(dict(r))
    return [(p, items.get(p["id"], {}), events.get(p["id"], [])) for p in pts]


def load_one(pid):
    with connect() as c:
        r = c.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        if not r:
            return None
        p = _p(r)
        items = {i["key"]: dict(status=i["status"], received_date=i["received_date"], note=i["note"])
                 for i in c.execute("SELECT * FROM items WHERE patient_id=?", (pid,))}
        events = [dict(e) for e in c.execute("SELECT * FROM events WHERE patient_id=? ORDER BY date", (pid,))]
    return p, items, events


def save_patient(data, pid=None):
    row = {k: data.get(k) for k in PATIENT_FIELDS if k in data}
    if "symptoms" in row:
        row["symptoms"] = json.dumps(row["symptoms"] or [])
    with connect() as c:
        if pid is None:
            row.setdefault("created_at", now())
            row["created_at"] = row.get("created_at") or now()
            if not row.get("mrn"):
                n = c.execute("SELECT COALESCE(MAX(id),0)+1 FROM patients").fetchone()[0]
                row["mrn"] = f"ONC-{n:05d}"
            cols = ",".join(row)
            cur = c.execute(f"INSERT INTO patients({cols}) VALUES({','.join('?' * len(row))})", list(row.values()))
            return cur.lastrowid
        sets = ",".join(f"{k}=?" for k in row)
        c.execute(f"UPDATE patients SET {sets} WHERE id=?", [*row.values(), pid])
        return pid


def delete_patient(pid):
    with connect() as c:
        c.execute("DELETE FROM patients WHERE id=?", (pid,))


def set_item(pid, key, status, received_date=None, note=""):
    with connect() as c:
        c.execute("INSERT INTO items(patient_id,key,status,received_date,note) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(patient_id,key) DO UPDATE SET status=excluded.status, received_date=excluded.received_date, note=excluded.note",
                  (pid, key, status, received_date, note))


def add_event(pid, type_, date_, facility="", detail=""):
    with connect() as c:
        return c.execute("INSERT INTO events(patient_id,type,date,facility,detail) VALUES(?,?,?,?,?)",
                         (pid, type_, date_, facility, detail)).lastrowid


def delete_event(eid):
    with connect() as c:
        c.execute("DELETE FROM events WHERE id=?", (eid,))


def log(actor, action, pid=None, detail=""):
    with connect() as c:
        c.execute("INSERT INTO audit(ts,actor,action,patient_id,detail) VALUES(?,?,?,?,?)", (now(), actor, action, pid, detail))


def audit(limit=200, pid=None):
    with connect() as c:
        if pid:
            rows = c.execute("SELECT * FROM audit WHERE patient_id=? ORDER BY id DESC LIMIT ?", (pid, limit))
        else:
            rows = c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


def get_settings():
    with connect() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}


def set_setting(k, v):
    with connect() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v)))


def get_targets():
    s = get_settings().get("targets")
    return json.loads(s) if s else {}


def wipe():
    with connect() as c:
        c.executescript("DELETE FROM items; DELETE FROM events; DELETE FROM patients; DELETE FROM audit;")
