"""SQLite memory store for Rekindle.now."""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rekindle.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# JSON-list fields on a contact
LIST_FIELDS = ["topics", "memorable_details", "my_promises", "their_promises", "interest_tags"]

CONTACT_FIELDS = [
    "name", "phone", "company", "role", "linkedin", "self_intro",
    "met_where", "met_when", "met_context", "introduced_by",
    "topics", "memorable_details", "current_focus",
    "my_promises", "their_promises", "followup_channel", "followup_due",
    "warmth", "last_contact", "cadence_days", "interest_tags",
    "i_can_offer", "they_can_offer", "language", "source", "summary",
]


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    c = conn()
    cols = ", ".join(f"{f} TEXT" for f in CONTACT_FIELDS)
    c.executescript(f"""
    CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols},
        created_at REAL, updated_at REAL);
    CREATE TABLE IF NOT EXISTS sessions (channel TEXT PRIMARY KEY, draft TEXT, history TEXT,
        contact_id INTEGER, updated_at REAL);
    CREATE TABLE IF NOT EXISTS triggers (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT,
        title TEXT, body TEXT, url TEXT, source TEXT, created_at REAL);
    CREATE TABLE IF NOT EXISTS nudges (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger_id INTEGER,
        contact_id INTEGER, reason TEXT, draft TEXT, image TEXT, status TEXT, created_at REAL);
    CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT,
        direction TEXT, body TEXT, created_at REAL);
    """)
    c.commit()


def _row_to_contact(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    for f in LIST_FIELDS:
        try:
            d[f] = json.loads(d[f]) if d.get(f) else []
        except Exception:
            d[f] = [d[f]] if d.get(f) else []
    return d


def list_contacts() -> List[Dict[str, Any]]:
    return [_row_to_contact(r) for r in conn().execute("SELECT * FROM contacts ORDER BY updated_at DESC")]


def get_contact(cid: int) -> Optional[Dict[str, Any]]:
    r = conn().execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return _row_to_contact(r) if r else None


def find_contact_by_name(name: str) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    r = conn().execute("SELECT * FROM contacts WHERE lower(name)=lower(?)", (name.strip(),)).fetchone()
    return _row_to_contact(r) if r else None


def _clean(data: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in data.items():
        if k not in CONTACT_FIELDS or v is None:
            continue
        out[k] = json.dumps(v) if k in LIST_FIELDS else str(v)
    return out


def upsert_contact(data: Dict[str, Any], cid: Optional[int] = None) -> int:
    c = conn()
    now = time.time()
    if cid is None:
        existing = find_contact_by_name(data.get("name", ""))
        cid = existing["id"] if existing else None
    if cid is not None:
        cur = get_contact(cid) or {}
        merged = {}
        for k, v in data.items():
            if k in LIST_FIELDS and isinstance(v, list):
                old = cur.get(k) or []
                merged[k] = old + [x for x in v if x not in old]
            elif v not in (None, ""):
                merged[k] = v
        vals = _clean(merged)
        if vals:
            sets = ", ".join(f"{k}=?" for k in vals)
            c.execute(f"UPDATE contacts SET {sets}, updated_at=? WHERE id=?", (*vals.values(), now, cid))
    else:
        vals = _clean(data)
        keys = ", ".join(list(vals) + ["created_at", "updated_at"])
        qs = ", ".join("?" * (len(vals) + 2))
        cur_ = c.execute(f"INSERT INTO contacts ({keys}) VALUES ({qs})", (*vals.values(), now, now))
        cid = cur_.lastrowid
    c.commit()
    return cid


def delete_all() -> None:
    c = conn()
    for t in ["contacts", "sessions", "triggers", "nudges", "log"]:
        c.execute(f"DELETE FROM {t}")
    c.commit()


# --- conversation sessions (one per channel, e.g. "wa:+91..." or "voice" or "sim") ---
def get_session(channel: str) -> Dict[str, Any]:
    r = conn().execute("SELECT * FROM sessions WHERE channel=?", (channel,)).fetchone()
    if not r:
        return {"channel": channel, "draft": {}, "history": [], "contact_id": None}
    return {"channel": channel, "draft": json.loads(r["draft"] or "{}"),
            "history": json.loads(r["history"] or "[]"), "contact_id": r["contact_id"]}


def save_session(s: Dict[str, Any]) -> None:
    c = conn()
    c.execute("REPLACE INTO sessions (channel, draft, history, contact_id, updated_at) VALUES (?,?,?,?,?)",
              (s["channel"], json.dumps(s["draft"]), json.dumps(s["history"][-20:]), s.get("contact_id"), time.time()))
    c.commit()


def reset_session(channel: str) -> None:
    c = conn()
    c.execute("DELETE FROM sessions WHERE channel=?", (channel,))
    c.commit()


# --- triggers & nudges ---
def add_trigger(kind: str, title: str, body: str = "", url: str = "", source: str = "") -> int:
    c = conn()
    cur = c.execute("INSERT INTO triggers (kind,title,body,url,source,created_at) VALUES (?,?,?,?,?,?)",
                    (kind, title, body, url, source, time.time()))
    c.commit()
    return cur.lastrowid


def get_trigger(tid: int) -> Optional[Dict[str, Any]]:
    r = conn().execute("SELECT * FROM triggers WHERE id=?", (tid,)).fetchone()
    return dict(r) if r else None


def add_nudge(trigger_id: int, contact_id: int, reason: str, draft: str, image: str = "") -> int:
    c = conn()
    cur = c.execute("INSERT INTO nudges (trigger_id,contact_id,reason,draft,image,status,created_at) VALUES (?,?,?,?,?,?,?)",
                    (trigger_id, contact_id, reason, draft, image, "new", time.time()))
    c.commit()
    return cur.lastrowid


def update_nudge(nid: int, **kw: Any) -> None:
    c = conn()
    sets = ", ".join(f"{k}=?" for k in kw)
    c.execute(f"UPDATE nudges SET {sets} WHERE id=?", (*kw.values(), nid))
    c.commit()


def get_nudge(nid: int) -> Optional[Dict[str, Any]]:
    r = conn().execute("SELECT * FROM nudges WHERE id=?", (nid,)).fetchone()
    return dict(r) if r else None


def list_nudges() -> List[Dict[str, Any]]:
    rows = conn().execute("""SELECT n.*, c.name AS contact_name, t.title AS trigger_title, t.kind AS trigger_kind
        FROM nudges n LEFT JOIN contacts c ON c.id=n.contact_id LEFT JOIN triggers t ON t.id=n.trigger_id
        ORDER BY n.id DESC LIMIT 50""")
    return [dict(r) for r in rows]


def log(channel: str, direction: str, body: str) -> None:
    c = conn()
    c.execute("INSERT INTO log (channel,direction,body,created_at) VALUES (?,?,?,?)", (channel, direction, body, time.time()))
    c.commit()


def get_log(channel: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = conn().execute("SELECT * FROM log WHERE channel=? ORDER BY id DESC LIMIT ?", (channel, limit))
    return list(reversed([dict(r) for r in rows]))
