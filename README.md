# Rekindle.now — a memory for your network

Built at Product Unconference 2026, Bangalore (build day).

Rekindle.now remembers who you met, where, what you talked about and what you promised. When something relevant happens (a news story, movement on a topic you discussed, a promise coming due, a relationship going quiet), it nudges you with a ready-to-send WhatsApp draft for each relevant person, plus an infographic.

## What's in it

- **Capture:** WhatsApp agent (text, voice notes, business-card photos, shared contacts, LinkedIn URLs, forwarded threads), a voice page for the iPhone Action Button, an Apple Watch Shortcut endpoint, calendar and event check-in prompts. Replies mirror your language: English in, English out; Hinglish in, easy Hinglish out.
- **Memory:** an LLM agent extracts 20+ fields per person into SQLite and asks 1–2 pointed follow-up questions.
- **Nudges:** one trigger → one personal draft per relevant contact, each with a PNG infographic and a `wa.me` link that opens the chat with the draft pre-filled.
- **Dashboard:** WhatsApp simulator, trigger buttons, nudge cards and memory cards.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in keys
./run.sh               # starts the app on :8000 and a Cloudflare quick tunnel
```

`run.sh` expects the `cloudflared` binary at `bin/cloudflared`. Use `./restart.sh` after editing `.env`; it restarts the app and keeps the tunnel URL.

- Dashboard: http://localhost:8000 (click "Load demo contacts" for fake demo data)
- Voice page: `<public-url>/voice`
- Twilio WhatsApp webhook: `<public-url>/whatsapp` (POST)

**LLM:** uses Claude when `ANTHROPIC_API_KEY` is set, otherwise Google Gemini's free tier via `GEMINI_API_KEY`.

**WhatsApp:** on a Twilio *trial* WhatsApp sender, outbound and reply messages require paid content templates. Inbound messages are processed and logged (visible in the dashboard's "Your WhatsApp" tab), but replies are not delivered until the sender is upgraded.

## WhatsApp commands

- `new`: start a new person
- `nudge`: scan news and due follow-ups, then `show` to receive nudges
- `trigger: <headline>`: fire a topic trigger

## Roadmap

Gmail newsletters as triggers, real calendar and location prompts, LinkedIn import, a native app with full-duplex Indic voice.
