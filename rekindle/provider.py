"""LLM provider switch: Claude when ANTHROPIC_API_KEY is set, else Google Gemini (free tier) via GEMINI_API_KEY."""
import json
import os
import re
from typing import Any, Dict, List

import httpx

GEMINI_MODELS = [m for m in [os.getenv("GEMINI_MODEL"), "gemini-flash-lite-latest", "gemini-3.1-flash-lite"] if m]
_good_model: List[str] = []


def name() -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return "none"


def _gemini_parts(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}]
    parts = []
    for b in content:
        if b.get("type") == "text":
            parts.append({"text": b["text"]})
        elif b.get("type") == "image":
            s = b["source"]
            parts.append({"inline_data": {"mime_type": s["media_type"], "data": s["data"]}})
        elif b.get("type") == "audio":
            parts.append({"inline_data": {"mime_type": b["mime"], "data": b["data"]}})
    return parts


def _gemini(system: str, messages: List[Dict[str, Any]], json_mode: bool, max_tokens: int) -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": _gemini_parts(m["content"])}
                for m in messages]
    body: Dict[str, Any] = {"contents": contents,
                            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.6}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = ""
    import time
    models = GEMINI_MODELS * 2  # two passes: fall over to the next model on overload, then retry
    for i, model in enumerate(models):
        try:
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                           headers={"X-goog-api-key": key}, json=body, timeout=30)
        except httpx.TimeoutException:
            last = f"{model}: timeout"
            continue
        if r.status_code == 200:
            j = r.json()
            try:
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
            except Exception:
                return ""
        last = f"{model}: {r.status_code} {r.text[:200]}"
        if r.status_code in (429, 500, 503) and i >= len(GEMINI_MODELS) - 1:
            time.sleep(1.5)
    raise RuntimeError("Gemini call failed: " + last)


def _parse_json(txt: str) -> Dict[str, Any]:
    txt = txt.strip()
    txt = re.sub(r"^```(json)?|```$", "", txt).strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else {}


def structured(system: str, messages: List[Dict[str, Any]], tool: Dict[str, Any], max_tokens: int = 2000) -> Dict[str, Any]:
    """Returns the tool input dict (Claude forced tool call, or Gemini JSON mode)."""
    if name() == "claude":
        from .llm import client, MODEL
        resp = client().messages.create(model=MODEL, max_tokens=max_tokens, system=system, messages=messages,
                                        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]})
        for b in resp.content:
            if b.type == "tool_use":
                return dict(b.input)
        return {}
    sys2 = (system + "\n\nOUTPUT FORMAT: respond ONLY with a JSON object (no prose) matching this JSON schema "
            f"(this is the `{tool['name']}` call): " + json.dumps(tool["input_schema"]))
    return _parse_json(_gemini(sys2, messages, True, max_tokens))


def text(prompt: str, max_tokens: int = 300) -> str:
    if name() == "claude":
        from .llm import client, MODEL
        resp = client().messages.create(model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in resp.content if b.type == "text")
    return _gemini("", [{"role": "user", "content": prompt}], False, max_tokens)


def transcribe_audio(b64: str, mime: str) -> str:
    """Gemini can transcribe Hinglish voice notes directly."""
    return _gemini("Transcribe this voice note verbatim. It may mix Hindi and English; write Hindi words in Roman script "
                   "(Hinglish), English words in English. Output only the transcript.",
                   [{"role": "user", "content": [{"type": "audio", "mime": mime, "data": b64}]}], False, 800).strip()
