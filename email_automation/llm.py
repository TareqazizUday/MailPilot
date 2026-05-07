from __future__ import annotations

import json
import os
from typing import Any


def _api_key(settings) -> str:
    k = getattr(settings, "LLM_API_KEY", None)
    if k is not None and hasattr(k, "get_secret_value"):
        s = (k.get_secret_value() or "").strip()
        if s:
            return s
    for name in ("OPENAI_API_KEY", "LLM_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""


def _model_name() -> str:
    return (os.environ.get("LLM_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"


def _extract_json(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    if not s:
        return {}
    # Try direct JSON first
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    # Try to find a JSON object within the text
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(s[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def decide_and_write_reply(
    *,
    settings,
    mail_from: str,
    mail_subject: str,
    mail_body: str,
    kb_context: str,
    service_keywords: list[str],
) -> dict[str, Any]:
    """
    Returns dict with keys:
      is_relevant: bool
      confidence: float (0..1)
      reply_subject: str
      reply_body: str
      reason: str (optional)
    """
    key = _api_key(settings)
    if not key:
        return {
            "is_relevant": False,
            "confidence": 0.0,
            "reply_subject": "",
            "reply_body": "",
            "reason": "missing_llm_key",
        }

    from openai import OpenAI

    client = OpenAI(api_key=key)
    model = _model_name()

    raw_kw = [str(k).strip() for k in (service_keywords or []) if str(k).strip()]
    raw_kw = [k for k in raw_kw if k.lower() not in ("*", "__all__")]
    kw = ", ".join(raw_kw[:40])
    kb_has = bool((kb_context or "").strip())
    prompt = (
        "You are MailPilot, an email assistant.\n"
        "Decide if this inbound email is service-related for this business (use SERVICE_KEYWORDS and the email text).\n"
        "If KB_CONTEXT is non-empty: ground the reply in KB_CONTEXT; do not invent facts beyond KB + the email.\n"
        "If KB_CONTEXT is empty: still decide relevance from the email + SERVICE_KEYWORDS; if relevant, write a "
        "concise professional reply using only what the email states plus polite generic wording. "
        "Do not invent prices, policies, or product details—offer to clarify or follow up if needed.\n"
        "If the email is spam, marketing blasts, automated job alerts, or clearly unrelated, return is_relevant=false.\n\n"
        "Return ONLY valid JSON with keys: is_relevant, confidence, reply_subject, reply_body, reason.\n"
        "confidence must be a number from 0 to 1.\n\n"
        f"SERVICE_KEYWORDS: {kw}\n"
        f"KB_CONTEXT_PRESENT: {str(kb_has).lower()}\n\n"
        f"EMAIL_FROM: {mail_from}\n"
        f"EMAIL_SUBJECT: {mail_subject}\n"
        f"EMAIL_BODY:\n{mail_body}\n\n"
        f"KB_CONTEXT:\n{kb_context}\n"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Return only JSON. No markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
    except Exception as e:
        return {
            "is_relevant": False,
            "confidence": 0.0,
            "reply_subject": "",
            "reply_body": "",
            "reason": f"llm_api_error:{e}",
        }

    text = ""
    try:
        text = resp.choices[0].message.content or ""
    except Exception:
        text = ""
    out = _extract_json(text)

    # Normalize
    is_rel = bool(out.get("is_relevant"))
    try:
        conf = float(out.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    conf = 0.0 if conf < 0 else 1.0 if conf > 1 else conf
    return {
        "is_relevant": is_rel,
        "confidence": conf,
        "reply_subject": str(out.get("reply_subject") or ""),
        "reply_body": str(out.get("reply_body") or ""),
        "reason": str(out.get("reason") or ""),
    }

