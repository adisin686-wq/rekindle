"""Trigger detection -> per-contact nudges (one trigger can create many drafts)."""
import datetime as dt
from typing import Any, Dict, List

import feedparser

from . import db, infographic, llm

RSS_FEEDS = {
    "Economic Times Tech": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",
    "Livemint Companies": "https://www.livemint.com/rss/companies",
    "Inc42": "https://inc42.com/feed/",
    "YourStory": "https://yourstory.com/feed",
    "Moneycontrol Business": "https://www.moneycontrol.com/rss/business.xml",
}


def fetch_news(limit_per_feed: int = 8) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for src, url in RSS_FEEDS.items():
        try:
            f = feedparser.parse(url)
            for e in f.entries[:limit_per_feed]:
                items.append({"title": e.get("title", ""), "body": (e.get("summary") or "")[:600],
                              "url": e.get("link", ""), "source": src})
        except Exception:
            continue
    return [i for i in items if i["title"]]


def process_trigger(trigger_id: int, only: List[Dict[str, Any]] = None) -> List[int]:
    trig = db.get_trigger(trigger_id)
    contacts = only if only is not None else db.list_contacts()
    if not trig or not contacts:
        return []
    out = []
    byid = {c["id"]: c for c in contacts}
    for n in llm.match_trigger(trig, contacts):
        c = byid.get(int(n.get("contact_id", -1)))
        if not c:
            continue
        nid = db.add_nudge(trigger_id, c["id"], n.get("reason", ""), n.get("draft", ""))
        try:
            img = infographic.render(nid, n.get("infographic") or {}, c, trig, llm.me())
            db.update_nudge(nid, image=img)
        except Exception as e:  # infographic is best-effort
            print("infographic failed", e)
        out.append(nid)
    return out


def scan_news() -> List[int]:
    contacts = db.list_contacts()
    items = fetch_news()
    if not items or not contacts:
        return []
    idx = llm.pick_relevant_headlines(items, contacts, k=2)
    nids: List[int] = []
    for i in idx:
        it = items[i]
        tid = db.add_trigger("news", it["title"], it["body"], it["url"], it["source"])
        nids += process_trigger(tid)
    return nids


def scan_due(days_ahead: int = 2) -> List[int]:
    """Actionables coming due + relationships going cold."""
    today = dt.date.today()
    nids: List[int] = []
    for c in db.list_contacts():
        due = c.get("followup_due")
        try:
            d = dt.date.fromisoformat(due[:10]) if due else None
        except Exception:
            d = None
        if d and d <= today + dt.timedelta(days=days_ahead):
            tid = db.add_trigger("follow-up due", f"Follow-up with {c['name']} due {d.isoformat()}",
                                 "Promises: " + "; ".join(c.get("my_promises") or []), source="Rekindle.now")
            nids += process_trigger(tid, only=[c])
            continue
        try:
            last = dt.date.fromisoformat((c.get("last_contact") or c.get("met_when") or "")[:10])
            cad = int(float(c.get("cadence_days") or 60))
            if (today - last).days >= cad:
                tid = db.add_trigger("going cold", f"{(today - last).days} days since you spoke to {c['name']}",
                                     c.get("summary") or "", source="Rekindle.now")
                nids += process_trigger(tid, only=[c])
        except Exception:
            pass
    return nids
