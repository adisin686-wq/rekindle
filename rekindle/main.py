"""Rekindle.now — a memory for your network. FastAPI server."""
import base64
import os
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

import httpx  # noqa: E402
from fastapi import BackgroundTasks, FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response  # noqa: E402

from . import db, llm, nudges  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
IMG = ROOT / "data" / "img"
app = FastAPI(title="Rekindle.now")
db.init()

TW_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TW_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TW_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
MY_WA = os.getenv("MY_WHATSAPP", "")  # e.g. +91XXXXXXXXXX
CURRENT_EVENT = os.getenv("CURRENT_EVENT", "Product Unconference 2026, Bangalore (Day 2 - build day)")


def base_url() -> str:
    f = ROOT / "data" / "base_url.txt"
    if os.getenv("PUBLIC_BASE_URL"):
        return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return f.read_text().strip().rstrip("/") if f.exists() else "http://localhost:8000"


# ---------------- WhatsApp send ----------------
_tls = threading.local()          # collects replies while handling an inbound webhook (sent back as TwiML)
OUTBOX: Dict[str, List[Any]] = {}  # proactive messages a trial sender can't push; delivered on your next message


def wa_send(to: str, body: str, media: Optional[List[str]] = None) -> None:
    num = to.replace("whatsapp:", "")
    db.log("wa:" + num, "out", body)
    coll = getattr(_tls, "collector", None)
    if coll is not None:
        coll.append((body, media))
        return
    if not (TW_SID and TW_TOKEN):
        print("[wa_send skipped: no Twilio creds]", body[:120])
        return
    data: Dict[str, Any] = {"From": TW_FROM, "To": "whatsapp:" + num, "Body": body[:1550]}
    if media:
        data["MediaUrl"] = media
    r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{TW_SID}/Messages.json",
                   data=data, auth=(TW_SID, TW_TOKEN), timeout=20)
    if r.status_code >= 300:
        print("Twilio push not allowed (trial sender) — queued for next reply:", r.text[:120])
        OUTBOX.setdefault(num, []).append((body, media))


def _twiml(msgs: List[Any]) -> str:
    from xml.sax.saxutils import escape
    out = ["<Response>"]
    for body, media in msgs:
        out.append("<Message><Body>" + escape(body[:1550]) + "</Body>" +
                   "".join(f"<Media>{escape(m)}</Media>" for m in (media or [])) + "</Message>")
    out.append("</Response>")
    return "".join(out)


# ---------------- speech-to-text for WhatsApp voice notes (local Whisper) ----------------
_whisper = None


def _load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    return _whisper


def transcribe(audio: bytes, suffix: str = ".ogg", mime: str = "audio/ogg") -> str:
    from . import provider
    if provider.name() == "gemini":
        try:
            return provider.transcribe_audio(base64.b64encode(audio).decode(), mime.split(";")[0])
        except Exception as e:
            print("gemini transcribe failed, falling back to whisper", e)
    p = ROOT / "data" / f"voice{suffix}"
    p.write_bytes(audio)
    segs, _ = _load_whisper().transcribe(str(p), task="transcribe", initial_prompt=
                                         "Hinglish conversation: maine usse Unconference mein mila, we talked about product.")
    return " ".join(s.text for s in segs).strip()


@app.on_event("startup")
def _warm():
    def w():
        try:
            _load_whisper()
            print("Whisper ready")
        except Exception as e:
            print("Whisper not available:", e)
    threading.Thread(target=w, daemon=True).start()


# ---------------- core conversation ----------------
def handle_message(channel: str, blocks: List[Dict[str, Any]], text_for_log: str) -> str:
    s = db.get_session(channel)
    low = text_for_log.strip().lower()
    if low in {"new", "reset", "naya", "new contact"}:
        db.reset_session(channel)
        return "Fresh start ✨ Kiske baare mein batana hai? / Who did you meet?"
    db.log(channel, "in", text_for_log)
    hint = (f"{llm.me()} is currently at: {CURRENT_EVENT}. If they don't say where they met someone today, "
            f"assume it was here (and mention that in your recap so they can correct you).")
    out = llm.agent_turn(s["history"], s["draft"], blocks, event_hint=hint)
    if out.get("new_contact"):
        s["draft"], s["contact_id"] = {}, None
    fields = out.get("fields") or {}
    for k, v in fields.items():
        if isinstance(v, list):
            old = s["draft"].get(k) or []
            s["draft"][k] = old + [x for x in v if x not in old]
        elif v not in (None, ""):
            s["draft"][k] = v
    if s["draft"].get("name"):
        d = dict(s["draft"])
        d.setdefault("last_contact", d.get("met_when"))
        d.setdefault("source", channel.split(":")[0])
        s["contact_id"] = db.upsert_contact(d, s.get("contact_id"))
    reply = out.get("reply", "Saved!")
    s["history"] += [{"role": "user", "content": text_for_log or "(attachment)"},
                     {"role": "assistant", "content": reply}]
    if out.get("complete"):
        s["history"] = []  # keep draft/contact so late additions still attach; history reset keeps it snappy
    db.save_session(s)
    db.log(channel, "out", reply)
    return reply


async def _twilio_media(url: str) -> bytes:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as c:
        r = await c.get(url, auth=(TW_SID, TW_TOKEN))
        return r.content


def _process_wa(frm: str, body: str, media: List[Dict[str, Any]]) -> None:
    try:
        low = body.strip().lower()
        if low in {"show", "ok", "nudges"}:
            if not OUTBOX.get(frm.replace("whatsapp:", "")):
                wa_send(frm, "Nothing new yet — give it a few more seconds, then send *show* again.")
            return
        if low in {"nudge", "scan", "nudge me"}:
            threading.Thread(target=lambda: deliver_nudges(nudges.scan_news() + nudges.scan_due()), daemon=True).start()
            wa_send(frm, "🔎 Scanning today’s news and your open promises against your people… send *show* in ~20 seconds.")
            return
        if low.startswith("trigger:"):
            title = body.split(":", 1)[1].strip()
            threading.Thread(target=lambda: deliver_nudges(nudges.process_trigger(
                db.add_trigger("topic movement", title, source="manual"))), daemon=True).start()
            wa_send(frm, "⚡ Finding who in your network cares about this… send *show* in ~15 seconds.")
            return
        blocks: List[Dict[str, Any]] = []
        log_text = body
        for m in media:
            ct, data = m["type"], m["data"]
            if ct.startswith("image/"):
                blocks.append(llm.image_block(data, ct.split(";")[0]))
                blocks.append({"type": "text", "text": "(Photo — likely a business card, badge, LinkedIn profile or selfie. Extract what you can.)"})
                log_text = (log_text + " [photo]").strip()
            elif "vcard" in ct:
                vc = data.decode("utf-8", "ignore")
                blocks.append({"type": "text", "text": f"(Shared contact card)\n{vc}"})
                log_text = (log_text + " [contact card]").strip()
            elif ct.startswith("audio/"):
                try:
                    t = transcribe(data, mime=ct)
                except Exception as e:
                    print("transcribe failed", e)
                    wa_send(frm, "Voice note couldn't be transcribed here — please type it, or use the Rekindle.now voice button 🙏")
                    return
                blocks.append({"type": "text", "text": f"(Voice note transcript) {t}"})
                log_text = (log_text + f" 🎙️ {t}").strip()
        if body:
            blocks.insert(0, {"type": "text", "text": body})
        if not blocks:
            return
        reply = handle_message("wa:" + frm.replace("whatsapp:", ""), blocks, log_text)
        wa_send(frm, reply)
    except Exception:
        traceback.print_exc()
        wa_send(frm, "Oops, something broke on my side. Try again?")


@app.post("/whatsapp")
async def whatsapp(request: Request, bg: BackgroundTasks):
    form = await request.form()
    frm = str(form.get("From", ""))
    body = str(form.get("Body", "") or "")
    media = []
    for i in range(int(form.get("NumMedia", 0) or 0)):
        url, ct = str(form.get(f"MediaUrl{i}")), str(form.get(f"MediaContentType{i}"))
        media.append({"type": ct, "data": await _twilio_media(url)})

    def run() -> List[Any]:
        _tls.collector = []
        try:
            num = frm.replace("whatsapp:", "")
            queued = OUTBOX.pop(num, [])      # deliver pending nudges / calendar pings first
            if queued and body.strip().lower() in {"show", "ok", "nudges"}:
                return queued
            _process_wa(frm, body, media)
            return queued + _tls.collector
        finally:
            _tls.collector = None

    from starlette.concurrency import run_in_threadpool
    import time as _t
    t0 = _t.time()
    msgs = await run_in_threadpool(run)
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + _twiml(msgs)
    print(f"[whatsapp] {frm} {body[:40]!r} -> {len(msgs)} msgs in {_t.time()-t0:.1f}s", flush=True)
    return Response(xml.encode("utf-8"), media_type="text/xml")


# ---------------- nudges ----------------
def wa_link(phone: Optional[str], text: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"https://wa.me/{digits}?text={quote(text)}" if digits else f"https://wa.me/?text={quote(text)}"


def deliver_nudges(ids: List[int]) -> None:
    for nid in ids:
        n = db.get_nudge(nid)
        c = db.get_contact(n["contact_id"]) if n else None
        if not n or not c:
            continue
        trig = db.get_trigger(n["trigger_id"]) or {}
        page = f"{base_url()}/n/{nid}"
        body = (f"🔔 *Rekindle with {c['name']}*" + (f" ({c.get('company')})" if c.get("company") else "") +
                f"\n_Why now:_ {n['reason']}\n_Trigger:_ {trig.get('title', '')}\n\n"
                f"*Draft:*\n{n['draft']}\n\n👉 Open their chat with this draft: {page}")
        media = [f"{base_url()}/img/{n['image']}"] if n.get("image") else None
        if MY_WA:
            wa_send(MY_WA, body, media)
        db.update_nudge(nid, status="delivered")


@app.get("/n/{nid}", response_class=HTMLResponse)
def nudge_page(nid: int):
    return (STATIC / "nudge.html").read_text()


@app.get("/go/{nid}")
def go(nid: int):
    """Redirect straight into WhatsApp with the draft."""
    n = db.get_nudge(nid)
    c = db.get_contact(n["contact_id"]) if n else None
    if not n or not c:
        return PlainTextResponse("not found", 404)
    db.update_nudge(nid, status="opened")
    return Response(status_code=302, headers={"Location": wa_link(c.get("phone"), n["draft"])})


@app.get("/img/{name}")
def img(name: str):
    p = (IMG / Path(name).name)
    return FileResponse(p) if p.exists() else PlainTextResponse("nf", 404)


# ---------------- JSON API (dashboard, simulator, voice page, watch shortcut) ----------------
@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC / "index.html").read_text()


@app.get("/voice", response_class=HTMLResponse)
def voice():
    return (STATIC / "voice.html").read_text()


@app.get("/api/contacts")
def api_contacts():
    return db.list_contacts()


@app.get("/api/nudges")
def api_nudges():
    out = []
    for n in db.list_nudges():
        c = db.get_contact(n["contact_id"]) or {}
        n["wa_link"] = wa_link(c.get("phone"), n["draft"] or "")
        n["img_url"] = f"/img/{n['image']}" if n.get("image") else ""
        out.append(n)
    return out


@app.get("/api/nudge/{nid}")
def api_nudge(nid: int):
    n = db.get_nudge(nid)
    if not n:
        return JSONResponse({"error": "nf"}, 404)
    c = db.get_contact(n["contact_id"]) or {}
    t = db.get_trigger(n["trigger_id"]) or {}
    return {**n, "contact": c, "trigger": t, "phone_digits": "".join(ch for ch in (c.get("phone") or "") if ch.isdigit()),
            "img_url": f"/img/{n['image']}" if n.get("image") else ""}


@app.post("/api/nudge/{nid}/status")
async def api_nudge_status(nid: int, request: Request):
    j = await request.json()
    db.update_nudge(nid, status=j.get("status", "opened"))
    return {"ok": True}


@app.get("/api/log")
def api_log(channel: str = "sim"):
    return db.get_log(channel)


@app.post("/api/chat")
async def api_chat(request: Request):
    j = await request.json()
    channel = j.get("channel", "sim")
    text = (j.get("text") or "").strip()
    blocks: List[Dict[str, Any]] = []
    log_text = text
    if text:
        blocks.append({"type": "text", "text": text})
    if j.get("image"):  # data URL
        head, b64 = j["image"].split(",", 1)
        mt = head.split(";")[0].split(":")[1]
        blocks.append(llm.image_block(base64.b64decode(b64), mt))
        blocks.append({"type": "text", "text": "(Photo — likely a business card, badge or LinkedIn profile. Extract what you can.)"})
        log_text += " [photo]"
    if j.get("vcard"):
        blocks.append({"type": "text", "text": f"(Shared contact card)\n{j['vcard']}"})
        log_text += " [contact card]"
    if not blocks:
        return {"reply": ""}
    return {"reply": handle_message(channel, blocks, log_text.strip())}


@app.post("/api/watch", response_class=PlainTextResponse)
async def api_watch(request: Request):
    """For Apple Watch / Siri Shortcut: body is JSON {text} or raw text; returns plain text to speak."""
    raw = (await request.body()).decode("utf-8", "ignore")
    try:
        import json
        text = json.loads(raw).get("text", raw)
    except Exception:
        text = raw
    return handle_message("watch", [{"type": "text", "text": text}], text)


@app.post("/api/trigger")
async def api_trigger(request: Request):
    j = await request.json()
    tid = db.add_trigger(j.get("kind", "topic movement"), j["title"], j.get("body", ""), j.get("url", ""), j.get("source", "manual"))
    ids = nudges.process_trigger(tid)
    deliver_nudges(ids)
    return {"trigger_id": tid, "nudges": ids}


@app.post("/api/scan/news")
def api_scan_news():
    ids = nudges.scan_news()
    deliver_nudges(ids)
    return {"nudges": ids}


@app.post("/api/scan/due")
def api_scan_due():
    ids = nudges.scan_due()
    deliver_nudges(ids)
    return {"nudges": ids}


@app.get("/api/news")
def api_news():
    return nudges.fetch_news(5)


@app.post("/api/calendar-ping")
async def api_calendar_ping(request: Request):
    """Simulates: calendar meeting just ended -> Rekindle.now pings you on WhatsApp for context."""
    j = await request.json()
    person, meeting = j.get("person", "someone"), j.get("meeting", "your meeting")
    msg = (f"📅 Your meeting *{meeting}* with *{person}* just ended. How did it go? "
           f"Anything you promised, or a follow-up date? (Voice note bhi chalega 🎙️)")
    ch = "wa:" + MY_WA if MY_WA else "sim"
    s = db.get_session(ch)
    s["draft"], s["contact_id"] = {"name": person, "met_context": meeting}, None
    s["history"] = [{"role": "user", "content": f"(Calendar: I just had '{meeting}' with {person}.)"},
                    {"role": "assistant", "content": msg}]
    db.save_session(s)
    if MY_WA:
        wa_send(MY_WA, msg)
    else:
        db.log("sim", "out", msg)
    return {"sent": msg}


@app.post("/api/event-checkin")
async def api_event_checkin(request: Request):
    j = await request.json()
    ev = j.get("event", CURRENT_EVENT)
    msg = (f"📍 Looks like you're at *{ev}*. Met anyone worth remembering? "
           f"Send me a name, a card photo, a contact, or just a voice note.")
    if MY_WA:
        wa_send(MY_WA, msg)
    else:
        db.log("sim", "out", msg)
    return {"sent": msg}


@app.post("/api/seed")
def api_seed():
    from .seed import seed
    seed()
    return {"ok": True}


@app.post("/api/reset-session")
async def api_reset_session(request: Request):
    j = await request.json()
    db.reset_session(j.get("channel", "sim"))
    return {"ok": True}


@app.get("/api/config")
def api_config():
    return {"twilio": bool(TW_SID and TW_TOKEN), "my_wa": bool(MY_WA), "my_wa_num": MY_WA, "base_url": base_url(),
            "event": CURRENT_EVENT, "me": llm.me(), "anthropic": __import__("rekindle.provider", fromlist=["x"]).name() != "none",
            "llm": __import__("rekindle.provider", fromlist=["x"]).name()}
