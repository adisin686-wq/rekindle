"""Fake demo contacts (no real people)."""
import datetime as dt

from . import db


def _d(days_ago: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()


def _f(days_ahead: int) -> str:
    return (dt.date.today() + dt.timedelta(days=days_ahead)).isoformat()


CONTACTS = [
    dict(name="Priya Raman", company="PaySetu (fintech)", role="Head of Product",
         self_intro="Aditya — we met at the SaaSBoomi Chennai coffee break and geeked out on UPI credit lines",
         met_where="SaaSBoomi Annual, Chennai", met_when=_d(92), met_context="Panel Q&A on embedded finance",
         topics=["UPI credit lines", "underwriting thin-file users", "RBI regulation"],
         memorable_details=["Runs half-marathons", "Daughter just started school"],
         current_focus="Launching credit on UPI for small merchants",
         my_promises=["Share my PRD template for credit onboarding"], their_promises=["Intro to their risk lead"],
         followup_channel="whatsapp", cadence_days="60", warmth="warm",
         interest_tags=["fintech", "upi", "rbi", "credit", "lending"], i_can_offer="PRD templates, PM hiring network",
         they_can_offer="Fintech regulatory insight", language="en",
         summary="Fintech product leader; promised her my credit-onboarding PRD template, never sent."),
    dict(name="Rohit Malhotra", company="Kirana Konnect", role="Founder",
         self_intro="Aditya — hum Delhi wale D2C meetup pe mile the, quick commerce pe lambi baat hui thi",
         met_where="D2C Founders Meetup, Gurugram", met_when=_d(45), met_context="Introduced by Neha at the meetup",
         introduced_by="Neha Kapoor", topics=["quick commerce margins", "dark stores", "kirana digitisation"],
         memorable_details=["Huge Delhi Capitals fan", "Moved back from Dubai"],
         current_focus="Raising seed round", my_promises=["Connect him with 2 angel investors"],
         followup_channel="whatsapp", followup_due=_f(1), cadence_days="30", warmth="hot",
         interest_tags=["quick commerce", "d2c", "retail", "kirana", "funding"], language="hinglish",
         summary="Founder raising seed for kirana tech; I promised 2 angel intros by tomorrow."),
    dict(name="Ananya Iyer", company="Lumen AI", role="ML Lead",
         self_intro="Aditya — we sat together at the Product Unconference Bangalore workshop on AI agents",
         met_where="Product Unconference 2026, Bangalore", met_when=_d(1), met_context="Day 1 breakout on AI agents for PMs",
         topics=["AI agents", "evals for LLM products", "voice AI in Indian languages"],
         memorable_details=["Learning Carnatic violin"], current_focus="Hindi/Hinglish voice agent for banks",
         their_promises=["Send their eval checklist"], followup_channel="linkedin", cadence_days="21", warmth="warm",
         interest_tags=["genai", "llm", "ai agents", "voice ai", "indic languages"], language="en",
         summary="ML lead building Indic voice agents; she owes me an eval checklist."),
    dict(name="Vikram Sethi", company="GreenGrid Energy", role="VP Strategy",
         self_intro="Aditya — we met on the Bangalore–Delhi flight and talked EV charging the whole way",
         met_where="Indigo flight BLR→DEL", met_when=_d(130), met_context="Seat neighbours",
         topics=["EV charging networks", "rooftop solar subsidies"], memorable_details=["Has two golden retrievers"],
         current_focus="Expanding EV charging in tier-2 cities", followup_channel="whatsapp", cadence_days="90", warmth="cold",
         interest_tags=["ev", "climate", "solar", "energy", "infrastructure"], language="en",
         summary="Energy strategy exec; great flight conversation, never followed up."),
    dict(name="Sneha Kulkarni", company="Shiksha Labs", role="Co-founder & CPO",
         self_intro="Aditya — we met at the Pune ProductCon and you told me about teaching coding to kids in Marathi",
         met_where="ProductCon Pune", met_when=_d(70), met_context="Hallway chat after her talk",
         topics=["vernacular edtech", "retention in K-12 apps", "NEP 2020"], memorable_details=["Ex-teacher", "Loves trekking in Sahyadris"],
         current_focus="Expanding to Hindi belt", followup_channel="email", cadence_days="60", warmth="warm",
         interest_tags=["edtech", "education", "vernacular", "k12", "nep"], language="en",
         summary="Edtech CPO; bonded over vernacular learning; wanted to compare retention playbooks."),
]


def seed() -> None:
    db.init()
    db.delete_all()
    for c in CONTACTS:
        c = dict(c)
        c.setdefault("last_contact", c["met_when"])
        c["source"] = "seed"
        db.upsert_contact(c)


if __name__ == "__main__":
    seed()
    print("seeded", len(CONTACTS))
