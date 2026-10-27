"""WhatsApp delivery.

If WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID are set, messages go out through the
WhatsApp Cloud API. Otherwise every message is logged as "ready to send" and staff
send it with one tap from the dashboard (wa.me click-to-chat link, text prefilled).
"""
import logging
import re
from urllib.parse import quote

import requests
from django.conf import settings

log = logging.getLogger(__name__)


def normalize(number):
    digits = re.sub(r"\D", "", number or "")
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) <= 7:  # local Gambian number, e.g. 3000000
        digits = settings.KUNDA["default_country_code"] + digits
    return digits


def link(number, text=""):
    n = normalize(number)
    base = f"https://wa.me/{n}" if n else "https://wa.me/"
    return f"{base}?text={quote(text)}" if text else base


def send(to, body, *, booking=None, kind="custom"):
    from .models import MessageLog

    entry = MessageLog(booking=booking, to=normalize(to), body=body, kind=kind)
    cfg = settings.KUNDA
    if cfg["whatsapp_token"] and cfg["whatsapp_phone_id"] and entry.to:
        url = f"https://graph.facebook.com/{cfg['whatsapp_api_version']}/{cfg['whatsapp_phone_id']}/messages"
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {cfg['whatsapp_token']}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": entry.to,
                    "type": "text",
                    "text": {"body": body, "preview_url": True},
                },
                timeout=10,
            )
            resp.raise_for_status()
            entry.status = "sent"
            entry.provider_id = (resp.json().get("messages") or [{}])[0].get("id", "")
        except Exception as exc:  # network / API errors are logged, never raised to the guest
            log.warning("WhatsApp send failed: %s", exc)
            entry.status = "failed"
            entry.error = str(exc)[:1000]
    else:
        entry.status = "manual"
    entry.save()
    return entry
