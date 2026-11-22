"""Claude calls: memory-capture agent and nudge matcher."""
import base64
import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

import anthropic

from . import provider

MODEL = os.getenv("REKINDLE_MODEL", "claude-sonnet-5-5")
_client: Optional[anthropic.Anthropic] = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def me() -> str:
    return os.getenv("USER_NAME", "Aditya")


FIELD_DOC = """
name, phone (E.164 like +9198...), company, role, linkedin (URL),
self_intro (one line the OTHER person would recognise the user by, e.g. "Aditya — we met in the coffee line at Product Unconference BLR and argued about AI PMs"),
met_where, met_when (ISO date if possible), met_context (why you met), introduced_by,
topics (list of what you talked about), memorable_details (list: personal, human details — kids, hobbies, hometown, a joke),
current_focus (what they're working on / care about right now),
my_promises (list: things the USER promised, include due date in text if any), their_promises (list),
followup_channel (whatsapp/email/linkedin/in-person), followup_due (ISO date of the next concrete follow-up),
warmth (cold/warm/hot), cadence_days (how often to reconnect, number), interest_tags (list of 3-8 short lowercase tags used to match news, e.g. "fintech", "upi", "d2c", "genai"),
i_can_offer, they_can_offer, language (en / hinglish), summary (2-line summary of the relationship)
"""

AGENT_SYSTEM = """You are Rekindle.now, a warm, sharp memory assistant for {me}'s professional network.
{me} tells you about people they met (by text, voice transcript, a business-card photo, a contact card, a LinkedIn URL,
a forwarded chat/email thread, or after a calendar meeting). Your job: capture a rich memory of the person so that months later
{me} can reconnect with a genuine reason.

Today is {today}. {event_hint}

Fields you maintain (only fill what you actually know — never invent facts):
{fields}

Rules:
- Every turn, call the tool `update_memory` with any NEW or CHANGED fields, your reply, and whether the memory is complete enough.
- Ask at most 2 short, pointed questions per turn, and only about the most valuable missing things, in this priority:
  name > where/context > what you talked about > any promises/follow-ups (with dates) > something personal/memorable.
  Phone number is useful (for WhatsApp drafts) — ask once if missing, accept "skip".
- Stop asking after ~3 exchanges; mark complete=true and give a crisp 2-3 line recap of what you saved plus when you'll nudge.
- Always infer interest_tags, self_intro, summary, cadence_days yourself; don't ask about those.
- Resolve relative dates ("next Friday", "kal") to ISO dates.
- LANGUAGE MIRRORING (critical): reply in the same language style as the user's latest message.
  * English in -> English out.
  * Hinglish (Hindi + English mix, Roman or Devanagari) -> reply in casual Roman-script Hinglish that leans on common English words
    ("Nice! Unke saath follow-up ka koi plan tha? Koi date decide hui thi?"). Never reply in pure/shuddh Hindi or Devanagari.
  Set language field accordingly.
- Keep replies short, friendly, WhatsApp-style. No markdown headers. Light emoji ok (max 1).
- If the user says something like "new person"/"naya contact", treat it as a new contact (set new_contact=true).
"""

AGENT_TOOL = {
    "name": "update_memory",
    "description": "Save extracted contact memory and reply to the user.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fields": {"type": "object", "description": "Contact fields to set/append (see field list)."},
            "reply": {"type": "string", "description": "Message back to the user, in their language style."},
            "complete": {"type": "boolean"},
            "new_contact": {"type": "boolean", "description": "True if this message starts a different person."},
        },
        "required": ["fields", "reply", "complete"],
    },
}


def agent_turn(history: List[Dict[str, Any]], draft: Dict[str, Any], user_content: List[Dict[str, Any]],
               event_hint: str = "") -> Dict[str, Any]:
    """history: prior [{role, content(str)}]; user_content: list of content blocks for this turn."""
    system = AGENT_SYSTEM.format(me=me(), today=dt.date.today().isoformat(), fields=FIELD_DOC,
                                 event_hint=event_hint)
    msgs: List[Dict[str, Any]] = []
    for h in history[-12:]:
        msgs.append({"role": h["role"], "content": h["content"]})
    blocks = list(user_content)
    blocks.append({"type": "text", "text": f"[Current saved memory for this person: {json.dumps(draft, ensure_ascii=False)}]"})
    msgs.append({"role": "user", "content": blocks})
    # merge consecutive same-role messages
    merged: List[Dict[str, Any]] = []
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            prev = merged[-1]["content"]
            if isinstance(prev, str):
                prev = [{"type": "text", "text": prev}]
            cur = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            merged[-1]["content"] = prev + cur
        else:
            merged.append(m)
    if merged and merged[0]["role"] != "user":
        merged = merged[1:]
    out = provider.structured(system, merged, AGENT_TOOL, 1500) or {}
    out.setdefault("fields", {})
    out.setdefault("reply", "Got it.")
    out.setdefault("complete", False)
    if not isinstance(out["fields"], dict):
        out["fields"] = {}
    return out


def image_block(data: bytes, media_type: str) -> Dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(data).decode()}}


# ---------------- Nudges ----------------
NUDGE_SYSTEM = """You are Rekindle.now's nudge engine for {me}. Today is {today}.
Given ONE trigger (a news story, a topic movement, an actionable coming due, or a relationship going cold) and {me}'s contacts,
decide which contacts (possibly several, possibly none) have a GENUINE, specific reason to hear from {me} now.

For each chosen contact write a WhatsApp draft FROM {me} TO that contact that:
- Opens by gently re-anchoring who {me} is and where/when they met (use self_intro / met_where / met_when) — the contact may have forgotten.
- References something specific from the earlier conversation (topic, memorable detail, or promise).
- Connects it to the trigger and GIVES value (an insight, the article, an intro, delivering on a promise) — never a needy "let's catch up?".
- Ends with one light, easy-to-answer question or concrete next step.
- 3-5 short sentences, natural and human, no hashtags, max 1 emoji. Use the contact's language field: if hinglish, write natural Roman Hinglish; else English.
- Don't paste the URL inside the draft text; it is attached separately.
Also give: reason (one line, for {me}: why this person, why now), and infographic {{headline (<=8 words), stat_or_fact (<=12 words), why_it_matters (<=16 words, tied to the contact)}}.
Only pick contacts with a real link. Call the tool once with all nudges."""

NUDGE_TOOL = {
    "name": "create_nudges",
    "description": "Create reconnect nudges for relevant contacts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "nudges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "contact_id": {"type": "integer"},
                        "reason": {"type": "string"},
                        "draft": {"type": "string"},
                        "infographic": {
                            "type": "object",
                            "properties": {"headline": {"type": "string"}, "stat_or_fact": {"type": "string"},
                                           "why_it_matters": {"type": "string"}},
                        },
                    },
                    "required": ["contact_id", "reason", "draft"],
                },
            }
        },
        "required": ["nudges"],
    },
}


def contact_brief(c: Dict[str, Any]) -> Dict[str, Any]:
    keys = ["id", "name", "company", "role", "self_intro", "met_where", "met_when", "met_context", "topics",
            "memorable_details", "current_focus", "my_promises", "their_promises", "followup_due",
            "last_contact", "cadence_days", "interest_tags", "i_can_offer", "language", "summary"]
    return {k: c.get(k) for k in keys if c.get(k)}


def match_trigger(trigger: Dict[str, Any], contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    payload = {"trigger": {k: trigger.get(k) for k in ["kind", "title", "body", "source"]},
               "contacts": [contact_brief(c) for c in contacts]}
    out = provider.structured(NUDGE_SYSTEM.format(me=me(), today=dt.date.today().isoformat()),
                              [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], NUDGE_TOOL, 4000)
    return list((out or {}).get("nudges", []))


def pick_relevant_headlines(items: List[Dict[str, str]], contacts: List[Dict[str, Any]], k: int = 3) -> List[int]:
    """Cheap pre-filter: which RSS items relate to anyone's interests. Returns indexes."""
    tags = sorted({t for c in contacts for t in (c.get("interest_tags") or [])} |
                  {t for c in contacts for t in (c.get("topics") or [])})
    listing = "\n".join(f"{i}. {it['title']}" for i, it in enumerate(items))
    txt = provider.text(f"Interests in my network: {', '.join(tags)}\n\nHeadlines:\n{listing}\n\n"
                        f"Return ONLY a JSON array of up to {k} headline indexes most relevant to those interests, e.g. [3,7].", 200)
    try:
        arr = json.loads(txt[txt.index("["): txt.rindex("]") + 1])
        return [int(i) for i in arr if 0 <= int(i) < len(items)][:k]
    except Exception:
        return []
