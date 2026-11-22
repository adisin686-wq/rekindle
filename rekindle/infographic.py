"""Render a shareable PNG card for a nudge."""
import textwrap
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "data" / "img"
OUT.mkdir(parents=True, exist_ok=True)


def _font(size: int, bold: bool = False):
    cands = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
             "/System/Library/Fonts/Helvetica.ttc"]
    for p in cands:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render(nid: int, info: Dict[str, Any], contact: Dict[str, Any], trigger: Dict[str, Any], me: str) -> str:
    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), (14, 23, 38))
    d = ImageDraw.Draw(img)
    # accent band
    d.rectangle([0, 0, W, 14], fill=(255, 122, 69))
    d.text((70, 60), "REKINDLE.NOW  ·  " + (trigger.get("kind") or "update").upper(), font=_font(30, True), fill=(255, 122, 69))
    y = 130
    head = info.get("headline") or trigger.get("title", "")
    for line in textwrap.wrap(head, 22)[:3]:
        d.text((70, y), line, font=_font(76, True), fill=(255, 255, 255))
        y += 92
    y += 30
    stat = info.get("stat_or_fact") or ""
    if stat:
        d.rounded_rectangle([70, y, W - 70, y + 170], radius=28, fill=(30, 45, 70))
        yy = y + 32
        for line in textwrap.wrap(stat, 38)[:2]:
            d.text((105, yy), line, font=_font(44, True), fill=(120, 220, 190))
            yy += 56
        y += 210
    why = info.get("why_it_matters") or ""
    d.text((70, y), f"Why it matters for {contact.get('name', '').split(' ')[0]}", font=_font(32, True), fill=(160, 175, 200))
    y += 50
    for line in textwrap.wrap(why, 44)[:3]:
        d.text((70, y), line, font=_font(40), fill=(230, 236, 245))
        y += 54
    # footer: who + where we met
    d.line([70, H - 190, W - 70, H - 190], fill=(50, 65, 90), width=2)
    d.text((70, H - 160), f"From {me}", font=_font(36, True), fill=(255, 255, 255))
    met = " · ".join(x for x in [contact.get("met_where"), contact.get("met_when")] if x)
    if met:
        d.text((70, H - 110), f"We met: {met}"[:60], font=_font(30), fill=(160, 175, 200))
    path = OUT / f"nudge_{nid}.png"
    img.save(path)
    return path.name
