"""USSD and SMS inbox endpoints for low-bandwidth farmer channels."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Form
from fastapi.responses import PlainTextResponse

from ..contracts import PhoneInboxResponse, PhoneMessage
from ..db import connect, insert_json

router = APIRouter(tags=["telco"])


def _latest_advisory(ward: str) -> dict[str, object] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM staged_advisories WHERE ward = ? ORDER BY rowid DESC LIMIT 1",
            (ward,),
        ).fetchone()
    return dict(row) if row else None


def _record_ussd_event(phone_number: str, text: str, response_text: str) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO mcp_audit_log VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                f"USSD-{uuid.uuid4().hex[:10].upper()}",
                "telco",
                "ussd_callback",
                "receive",
                json.dumps({"phone_number": phone_number, "text": text}),
                json.dumps({"response": response_text}),
            ),
        )


@router.post("/api/v1/ussd/callback")
async def ussd_callback(
    session_id: str = Form(..., alias="sessionId"),
    service_code: str = Form(..., alias="serviceCode"),
    phone_number: str = Form(..., alias="phoneNumber"),
    text: str = Form(..., alias="text"),
) -> PlainTextResponse:
    """Handle Africa's Talking style USSD callbacks for farmers without smartphones."""
    _ = (session_id, service_code)
    with connect() as db:
        farmer = db.execute(
            "SELECT farmer_id, full_name, ward FROM farmers WHERE phone_number = ?",
            (phone_number,),
        ).fetchone()
    ward = str(farmer["ward"]) if farmer else "Rachuonyo North"

    if text == "":
        response_text = (
            "CON Ecovuna Homa Bay:\n"
            "1. Read today's advisory\n"
            "2. Confirm action taken\n"
            "3. Claim input e-voucher"
        )
    elif text == "1":
        advisory = _latest_advisory(ward)
        if advisory:
            response_text = f"END {advisory['draft_sms_english']}"
        else:
            response_text = "END No advisory has been staged for your ward yet."
    elif text == "2":
        response_text = "END Thank you. Your confirmation is logged for the ward officer."
    elif text == "3":
        advisory = _latest_advisory(ward)
        if advisory:
            response_text = (
                f"END E-Voucher {advisory['evoucher_package_code']} active. "
                f"Show this code at your verified agro-dealer."
            )
        else:
            response_text = "END No active e-voucher for your ward yet."
    else:
        response_text = "END Invalid selection."

    _record_ussd_event(phone_number, text, response_text)
    return PlainTextResponse(content=response_text)


@router.get("/api/v1/telco/phone-inbox", response_model=PhoneInboxResponse)
def get_phone_inbox(phone: str) -> PhoneInboxResponse:
    """Return delivered messages for a farmer phone number."""
    with connect() as db:
        rows = db.execute(
            "SELECT sender, timestamp, text_sw, text_en, text_luo, citation "
            "FROM phone_messages WHERE phone_number = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT 10",
            (phone,),
        ).fetchall()
    return PhoneInboxResponse(
        messages=[PhoneMessage.model_validate(dict(row)) for row in rows]
    )


def queue_inbox_message(
    phone_number: str,
    sender: str,
    text_sw: str,
    text_en: str,
    text_luo: str,
    citation: str,
) -> None:
    """Persist a delivered SMS so the phone inbox can read it back."""
    with connect() as db:
        insert_json(
            db,
            "phone_messages",
            {
                "phone_number": phone_number,
                "sender": sender,
                "timestamp": datetime.now(UTC).isoformat(),
                "text_sw": text_sw,
                "text_en": text_en,
                "text_luo": text_luo,
                "citation": citation,
            },
        )
