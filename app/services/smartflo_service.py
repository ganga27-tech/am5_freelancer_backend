import re
import logging
from typing import Dict, Any, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SmartfloService:
    """
    Tata Tele Business Services Smartflo Click-to-Call Service.
    API documentation: https://api-smartflo.tatateleservices.com/v1/click_to_call
    """

    @staticmethod
    def normalize_phone_number(raw_phone: str) -> str:
        """
        Normalize phone numbers for Smartflo.
        Accepts 10-digit mobile numbers or numbers starting with 91 / +91 / 0.
        Returns a clean 10-digit or valid standard number without symbols.
        """
        if not raw_phone:
            raise ValueError("Phone number is required")

        # Strip whitespace and symbols
        digits = re.sub(r"\D", "", raw_phone)

        # If 12 digits starting with 91, strip 91 or keep standard
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]

        # Validate 10-digit mobile number or standard extension
        if len(digits) < 4 or len(digits) > 13:
            raise ValueError(f"Invalid phone number format: {raw_phone}")

        return digits

    @classmethod
    async def initiate_click_to_call(
        cls,
        agent_number: Optional[str] = None,
        destination_number: str = "",
        caller_id: Optional[str] = None,
        call_timeout: Optional[int] = None,
        custom_identifier: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Initiates an asynchronous Click-to-Call request via Tata Smartflo API.
        
        Parameters:
            - agent_number: Agent ID ('050xxx'), Extension ('060xxx'), DID or registered mobile number.
            - destination_number: Target customer / vendor phone number.
            - caller_id: Assigned Smartflo Pilot Number / DID.
            - call_timeout: Maximum call duration in seconds.
            - custom_identifier: Key-value metadata for webhook correlation (<= 512 chars).
            
        Returns:
            Tuple[bool, str, Optional[str]]: (success, message, ref_id)
        """
        # Resolve agent number
        eff_agent = agent_number or settings.SMARTFLO_DEFAULT_AGENT_NUMBER or "918065605779"
        eff_agent_clean = re.sub(r"\D", "", str(eff_agent))

        if not destination_number:
            return False, "Destination phone number is required", None

        try:
            norm_dest = cls.normalize_phone_number(destination_number)
        except ValueError as e:
            return False, str(e), None

        eff_caller_id = caller_id or settings.SMARTFLO_CALLER_ID or "918065605783"
        eff_caller_id_clean = re.sub(r"\D", "", str(eff_caller_id))

        eff_timeout = call_timeout or settings.SMARTFLO_CALL_TIMEOUT or 300

        payload: Dict[str, Any] = {
            "agent_number": eff_agent_clean,
            "destination_number": norm_dest,
            "caller_id": eff_caller_id_clean,
            "async": 1,
            "call_timeout": eff_timeout,
        }

        if custom_identifier:
            payload["custom_identifier"] = custom_identifier

        headers = {
            "Authorization": f"Bearer {settings.SMARTFLO_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        api_url = settings.SMARTFLO_API_URL or "https://api-smartflo.tatateleservices.com/v1/click_to_call"

        logger.info(
            f"Initiating Tata Smartflo C2C: agent={eff_agent_clean} -> dest={norm_dest}, caller_id={eff_caller_id_clean}"
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    api_url,
                    json=payload,
                    headers=headers,
                )

            logger.info(f"Smartflo response status: {response.status_code}, body: {response.text}")

            try:
                resp_json = response.json()
            except Exception:
                resp_json = {}

            if response.status_code == 200:
                is_success = resp_json.get("success", True)
                message = resp_json.get("message", "Call originated successfully.")
                ref_id = resp_json.get("ref_id")
                return is_success, message, ref_id
            else:
                err_msg = resp_json.get("message") or resp_json.get("error") or response.text or f"Smartflo returned HTTP {response.status_code}"
                logger.warning(f"Smartflo call failed with HTTP {response.status_code}: {err_msg}")
                return False, f"Smartflo: {err_msg}", None

        except httpx.TimeoutException:
            logger.error("Timeout connecting to Tata Smartflo Click-to-Call API")
            return False, "Smartflo service timed out. Please try again.", None
        except httpx.RequestError as exc:
            logger.error(f"Network error connecting to Smartflo: {str(exc)}")
            return False, f"Unable to reach Smartflo network: {str(exc)}", None
        except Exception as exc:
            logger.error(f"Unexpected error during Smartflo call: {str(exc)}", exc_info=True)
            return False, f"Error initiating call: {str(exc)}", None


smartflo_service = SmartfloService()
