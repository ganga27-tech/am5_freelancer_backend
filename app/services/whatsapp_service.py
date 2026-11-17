"""Send WhatsApp messages through the campaign API."""
import logging
import re
from typing import Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_whatsapp(phone: str, message: str, campaign_name: str) -> Tuple[bool, str]:
    """Send one WhatsApp message. Returns (success, error text). Never raises."""
    if not settings.WHATSAPP_API_TOKEN or not settings.WHATSAPP_API_SECRET:
        logger.warning("WHATSAPP_API_TOKEN / WHATSAPP_API_SECRET not set. Skipping WhatsApp message.")
        return False, "WhatsApp is not configured"

    digits = re.sub(r"\D", "", phone or "")[-10:]
    if len(digits) != 10:
        return False, "Invalid phone number"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
        "X-API-Secret": settings.WHATSAPP_API_SECRET,
    }
    payload = {
        "campaign_type": "WAV",
        "campaign_name": campaign_name,
        "phone_numbers": [digits],
        "message": message,
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(settings.WHATSAPP_API_URL, json=payload, headers=headers, timeout=15.0)
        if response.status_code in (200, 201) and response.json().get("success") is True:
            return True, ""
        logger.error("WhatsApp send failed (%s): %s", response.status_code, response.text[:300])
        return False, response.text
    except Exception as e:
        logger.error("WhatsApp send error: %s", e)
        return False, str(e)
