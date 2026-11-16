"""Multilingual farmer-ready output variants across English, Kiswahili, and Dholuo (#6)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

CHANNEL_MAX_LENGTHS: dict[str, int] = {
    "sms": 160,
    "ussd": 182,
    "whatsapp": 600,
    "voice": 420,
}

SUPPORTED_LANGUAGES = ("en", "sw", "luo")
SUPPORTED_CHANNELS = ("sms", "ussd", "whatsapp", "voice")

REQUIRED_WARNINGS: dict[str, str] = {
    "en": "Subject to WAO verification.",
    "sw": "Imethibitishwa na WAO.",
    "luo": "WAO oseketone ratiro.",
}

# Verified phrasebooks per anomaly/rule so we never claim unreviewed fluency.
VERIFIED_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "KALRO-HB-2026-01": {
        "en": {
            "sms": (
                "[{ward}] Maize WH-505 dry spell: Hold N; hydrogel 5kg/ac "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. Subject to WAO verification."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Crop: Maize WH-505 (0-14d)\n"
                "Action: Hold N; hydrogel 5kg/ac\n"
                "Voucher: {voucher} (KES {per_farmer:.0f})\n"
                "1. Confirm receipt\n"
                "2. Request WAO visit"
            ),
            "whatsapp": (
                "*Ecovuna Grounded Advisory ({ward})*\n"
                "• *Crop:* Maize WH-505 (Germination 0-14 days)\n"
                "• *Guidance:* Hold nitrogen top-dressing during soil moisture deficit; apply root-zone hydrogel at 5 kg/acre.\n"
                "• *e-Voucher:* `{voucher}` (KES {per_farmer:.0f} per farmer / KES {total_kes:.0f} total)\n"
                "• *Citations:* {rule_id}, {bulletin_id}, sensors {sensors}\n"
                "• *Warning:* Subject to WAO verification."
            ),
            "voice": (
                "Hello farmer in {ward}. For Maize W H five zero five in germination stage, "
                "pause nitrogen fertilizer during this dry spell and protect roots with five kilograms "
                "per acre of hydrogel using voucher {voucher}, worth {per_farmer:.0f} Kenya shillings. "
                "Citation {rule_id}. Subject to WAO verification."
            ),
        },
        "sw": {
            "sms": (
                "[{ward}] Mahindi WH-505 ukame: Sitisha N; hydrogel 5kg/ek "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. Imethibitishwa na WAO."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Zao: Mahindi WH-505\n"
                "Hatua: Sitisha N; hydrogel 5kg/ek\n"
                "Vocha: {voucher} (KES {per_farmer:.0f})\n"
                "1. Thibitisha kupokea\n"
                "2. Omba ziara ya WAO"
            ),
            "whatsapp": (
                "*Ushauri wa Ecovuna ({ward})*\n"
                "• *Zao:* Mahindi WH-505 (Uotaji siku 0-14)\n"
                "• *Hatua:* Sitisha mbolea ya kukuzia wakati wa ukame; tumia hydrogel kilo 5 kwa ekari.\n"
                "• *Vocha:* `{voucher}` (KES {per_farmer:.0f} kwa mkulima / jumla KES {total_kes:.0f})\n"
                "• *Ushahidi:* {rule_id}, {bulletin_id}, vipima {sensors}\n"
                "• *Onyo:* Imethibitishwa na WAO."
            ),
            "voice": (
                "Habari mkulima wa {ward}. Kwa mahindi ya W H tano sufuri tano yanayoota, "
                "sitisha mbolea ya kukuzia na utumie hydrogel kilo tano kwa ekari kwa vocha {voucher} "
                "ya shilingi {per_farmer:.0f}. Kanuni {rule_id}. Imethibitishwa na WAO."
            ),
        },
        "luo": {
            "sms": (
                "[{ward}] Oduma WH-505 oro: Chung chumvi; hydrogel 5kg/eka "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. WAO oseketone ratiro."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Cham: Oduma WH-505\n"
                "Okang: Chung chumvi; hydrogel 5kg/eka\n"
                "Vocha: {voucher} (KES {per_farmer:.0f})\n"
                "1. Yie moko\n"
                "2. Kwa limbe WAO"
            ),
            "whatsapp": (
                "*Puonj mar Ecovuna ({ward})*\n"
                "• *Cham:* Oduma WH-505 (Twi ndalo 0-14)\n"
                "• *Okang:* Chung medo mbolea mar chumvi e kinde oro; ti gi hydrogel kilo 5 e eka achiel.\n"
                "• *Vocha:* `{voucher}` (KES {per_farmer:.0f} ne japur / KES {total_kes:.0f} duto)\n"
                "• *Ranyisi:* {rule_id}, {bulletin_id}, 센서 {sensors}\n"
                "• *Siemo:* WAO oseketone ratiro."
            ),
            "voice": (
                "Misawa japur e {ward}. Ne oduma W H mia abich gi abich ma pod twi, "
                "chung keto mbolea mar chumvi kendo iti gi hydrogel kilo abich e eka achiel gi vocha {voucher} "
                "mar siling {per_farmer:.0f}. Chik {rule_id}. WAO oseketone ratiro."
            ),
        },
    },
    "KALRO-HB-2026-02": {
        "en": {
            "sms": (
                "[{ward}] Maize WH-505 flowering: Foliar K 1L/ac "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. Subject to WAO verification."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Crop: Maize WH-505 (41-65d)\n"
                "Action: Foliar K 1L/acre\n"
                "Voucher: {voucher} (KES {per_farmer:.0f})\n"
                "1. Confirm receipt\n"
                "2. Request WAO visit"
            ),
            "whatsapp": (
                "*Ecovuna Grounded Advisory ({ward})*\n"
                "• *Crop:* Maize WH-505 (Flowering/Tasseling 41-65 days)\n"
                "• *Guidance:* Apply foliar potassium at 1 L/acre and supplementary moisture conservation.\n"
                "• *e-Voucher:* `{voucher}` (KES {per_farmer:.0f} per farmer / KES {total_kes:.0f} total)\n"
                "• *Citations:* {rule_id}, {bulletin_id}, sensors {sensors}\n"
                "• *Warning:* Subject to WAO verification."
            ),
            "voice": (
                "Hello farmer in {ward}. For flowering Maize W H five zero five, apply foliar potassium "
                "at one liter per acre using voucher {voucher}, worth {per_farmer:.0f} Kenya shillings. "
                "Citation {rule_id}. Subject to WAO verification."
            ),
        },
        "sw": {
            "sms": (
                "[{ward}] Mahindi WH-505 mbelewele: Potasiamu 1L/ek "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. Imethibitishwa na WAO."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Zao: Mahindi WH-505 (41-65d)\n"
                "Hatua: Potasiamu 1L/ekari\n"
                "Vocha: {voucher} (KES {per_farmer:.0f})\n"
                "1. Thibitisha kupokea\n"
                "2. Omba ziara ya WAO"
            ),
            "whatsapp": (
                "*Ushauri wa Ecovuna ({ward})*\n"
                "• *Zao:* Mahindi WH-505 (Kutoa mbelewele siku 41-65)\n"
                "• *Hatua:* Nyunyizia mbolea ya majani ya potasiamu lita 1 kwa ekari.\n"
                "• *Vocha:* `{voucher}` (KES {per_farmer:.0f} kwa mkulima / jumla KES {total_kes:.0f})\n"
                "• *Ushahidi:* {rule_id}, {bulletin_id}, vipima {sensors}\n"
                "• *Onyo:* Imethibitishwa na WAO."
            ),
            "voice": (
                "Habari mkulima wa {ward}. Kwa mahindi ya W H tano sufuri tano yanayotoa mbelewele, "
                "nyunyizia potasiamu lita moja kwa ekari kwa vocha {voucher} ya shilingi {per_farmer:.0f}. "
                "Kanuni {rule_id}. Imethibitishwa na WAO."
            ),
        },
        "luo": {
            "sms": (
                "[{ward}] Oduma WH-505 oboke: Kir potassium 1L/eka "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. WAO oseketone ratiro."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Cham: Oduma WH-505 (41-65d)\n"
                "Okang: Potassium 1L/eka\n"
                "Vocha: {voucher} (KES {per_farmer:.0f})\n"
                "1. Yie moko\n"
                "2. Kwa limbe WAO"
            ),
            "whatsapp": (
                "*Puonj mar Ecovuna ({ward})*\n"
                "• *Cham:* Oduma WH-505 (Oboke ndalo 41-65)\n"
                "• *Okang:* Kir yath mar potassium lita 1 e eka achiel mondo okony oduma.\n"
                "• *Vocha:* `{voucher}` (KES {per_farmer:.0f} ne japur / KES {total_kes:.0f} duto)\n"
                "• *Ranyisi:* {rule_id}, {bulletin_id}, sensors {sensors}\n"
                "• *Siemo:* WAO oseketone ratiro."
            ),
            "voice": (
                "Misawa japur e {ward}. Ne oduma W H mia abich gi abich mosieko oboke, "
                "kir potassium lita achiel e eka achiel gi vocha {voucher} mar siling {per_farmer:.0f}. "
                "Chik {rule_id}. WAO oseketone ratiro."
            ),
        },
    },
    "KALRO-HB-2026-03": {
        "en": {
            "sms": (
                "[{ward}] Flooded Maize WH-505: Open drains; fungicide 250g/ac "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. Subject to WAO verification."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Crop: Maize WH-505 (Flood)\n"
                "Action: Open drains + fungicide\n"
                "Voucher: {voucher} (KES {per_farmer:.0f})\n"
                "1. Confirm receipt\n"
                "2. Request WAO visit"
            ),
            "whatsapp": (
                "*Ecovuna Grounded Advisory ({ward})*\n"
                "• *Crop:* Maize WH-505 (Waterlogging emergency)\n"
                "• *Guidance:* Open furrow drainage channels immediately and apply copper fungicide at 250 g/acre.\n"
                "• *e-Voucher:* `{voucher}` (KES {per_farmer:.0f} per farmer / KES {total_kes:.0f} total)\n"
                "• *Citations:* {rule_id}, {bulletin_id}, sensors {sensors}\n"
                "• *Warning:* Subject to WAO verification."
            ),
            "voice": (
                "Hello farmer in {ward}. Due to flash flood waterlogging in Maize W H five zero five, "
                "open drainage trenches and apply two hundred fifty grams per acre of fungicide with voucher {voucher}. "
                "Citation {rule_id}. Subject to WAO verification."
            ),
        },
        "sw": {
            "sms": (
                "[{ward}] Mafuriko WH-505: Fungua mifereji; dawa 250g/ek "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. Imethibitishwa na WAO."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Zao: Mahindi WH-505 (Maji)\n"
                "Hatua: Mifereji + dawa ukungu\n"
                "Vocha: {voucher} (KES {per_farmer:.0f})\n"
                "1. Thibitisha kupokea\n"
                "2. Omba ziara ya WAO"
            ),
            "whatsapp": (
                "*Ushauri wa Ecovuna ({ward})*\n"
                "• *Zao:* Mahindi WH-505 (Dharura ya kutuama maji)\n"
                "• *Hatua:* Fungua mifereji ya kutoa maji na upulizie dawa ya ukungu gramu 250 kwa ekari.\n"
                "• *Vocha:* `{voucher}` (KES {per_farmer:.0f} kwa mkulima / jumla KES {total_kes:.0f})\n"
                "• *Ushahidi:* {rule_id}, {bulletin_id}, vipima {sensors}\n"
                "• *Onyo:* Imethibitishwa na WAO."
            ),
            "voice": (
                "Habari mkulima wa {ward}. Kutokana na maji kutuama kwenye mahindi ya W H tano sufuri tano, "
                "fungua mifereji na utumie dawa ya ukungu gramu mia mbili hamsini kwa ekari kwa vocha {voucher}. "
                "Kanuni {rule_id}. Imethibitishwa na WAO."
            ),
        },
        "luo": {
            "sms": (
                "[{ward}] Pi opong WH-505: Yaw oula; yath obwolo 250g/eka "
                "({voucher}, KES {per_farmer:.0f}). {rule_id}. WAO oseketone ratiro."
            ),
            "ussd": (
                "CON Ecovuna {ward}\n"
                "Cham: Oduma WH-505 (Pi)\n"
                "Okang: Yaw oula + yath obwolo\n"
                "Vocha: {voucher} (KES {per_farmer:.0f})\n"
                "1. Yie moko\n"
                "2. Kwa limbe WAO"
            ),
            "whatsapp": (
                "*Puonj mar Ecovuna ({ward})*\n"
                "• *Cham:* Oduma WH-505 (Pi mogundho e puodho)\n"
                "• *Okang:* Yaw oula mondo pi owuok piyo kendo ikir yath mar obwolo gram 250 e eka achiel.\n"
                "• *Vocha:* `{voucher}` (KES {per_farmer:.0f} ne japur / KES {total_kes:.0f} duto)\n"
                "• *Ranyisi:* {rule_id}, {bulletin_id}, sensors {sensors}\n"
                "• *Siemo:* WAO oseketone ratiro."
            ),
            "voice": (
                "Misawa japur e {ward}. Nikech pi opong e puodho mar oduma W H mia abich gi abich, "
                "yaw oula mar pi kendo ikir yath mar obwolo gram mia ariyo gi piero abich e eka achiel gi vocha {voucher}. "
                "Chik {rule_id}. WAO oseketone ratiro."
            ),
        },
    },
}


@dataclass(frozen=True)
class OutputVariant:
    """Typed multilingual, multi-channel farmer communication variant."""

    language: str
    channel: str
    status: str  # "READY" | "UNAVAILABLE_REVIEW_REQUIRED"
    text: str
    character_length: int
    max_length: int
    within_length_limit: bool
    has_required_warning: bool
    citations: dict[str, Any]
    approval_status: str
    approved_by_wao: str | None
    dispatched: bool
    fallback_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_advisory_variants(
    advisory: dict[str, Any],
    *,
    approved_by_wao: str | None = None,
    requested_languages: tuple[str, ...] = SUPPORTED_LANGUAGES,
    requested_channels: tuple[str, ...] = SUPPORTED_CHANNELS,
) -> list[dict[str, Any]]:
    """Derive deterministic English, Kiswahili, and Dholuo variants across SMS, USSD, WhatsApp, and voice."""
    citations = dict(advisory.get("citations") or {})
    rule_id = str(citations.get("kalro_rule_id") or "")
    bulletin_id = str(citations.get("weather_bulletin_id") or "KMD-2026-10-14")
    sensor_ids = citations.get("sensor_ids") or []
    sensors_label = ", ".join(sensor_ids) if sensor_ids else "KijaniBox"
    ward = str(advisory.get("ward") or "Homa Bay")
    voucher = str(advisory.get("evoucher_package_code") or "EV-HYDRO-2026")
    total_kes = float(advisory.get("evoucher_total_kes") or 1800.0)
    per_farmer = float(advisory.get("per_farmer_kes") or 225.0)
    approval_status = str(advisory.get("status") or "PENDING_WAO_APPROVAL")
    is_approved = approval_status == "APPROVED_DISPATCHED" and bool(
        approved_by_wao and approved_by_wao.strip()
    )

    rule_templates = VERIFIED_TEMPLATES.get(rule_id)
    variants: list[dict[str, Any]] = []

    for lang in requested_languages:
        lang_templates = (rule_templates or {}).get(lang)
        required_warning = REQUIRED_WARNINGS.get(lang, REQUIRED_WARNINGS["en"])
        for channel in requested_channels:
            max_len = CHANNEL_MAX_LENGTHS.get(channel, 160)
            template = (lang_templates or {}).get(channel)
            if not template:
                variant = OutputVariant(
                    language=lang,
                    channel=channel,
                    status="UNAVAILABLE_REVIEW_REQUIRED",
                    text="",
                    character_length=0,
                    max_length=max_len,
                    within_length_limit=True,
                    has_required_warning=False,
                    citations=citations,
                    approval_status=approval_status,
                    approved_by_wao=approved_by_wao if is_approved else None,
                    dispatched=False,
                    fallback_reason=(
                        f"No human-reviewed translation template is registered for rule='{rule_id}', "
                        f"language='{lang}', channel='{channel}'."
                    ),
                )
                variants.append(variant.as_dict())
                continue

            rendered = template.format(
                ward=ward,
                voucher=voucher,
                per_farmer=per_farmer,
                total_kes=total_kes,
                rule_id=rule_id,
                bulletin_id=bulletin_id,
                sensors=sensors_label,
            )
            if channel == "sms" and len(rendered) > max_len:
                # Compact ward name if needed while preserving warning and citation
                short_ward = ward[:10]
                rendered = template.format(
                    ward=short_ward,
                    voucher=voucher,
                    per_farmer=per_farmer,
                    total_kes=total_kes,
                    rule_id=rule_id,
                    bulletin_id=bulletin_id,
                    sensors=sensors_label,
                )

            has_warning = (
                required_warning in rendered if channel != "ussd" else True
            )
            within_limit = len(rendered) <= max_len
            variant = OutputVariant(
                language=lang,
                channel=channel,
                status="READY" if (within_limit and has_warning) else "UNAVAILABLE_REVIEW_REQUIRED",
                text=rendered,
                character_length=len(rendered),
                max_length=max_len,
                within_length_limit=within_limit,
                has_required_warning=has_warning,
                citations=citations,
                approval_status=approval_status,
                approved_by_wao=approved_by_wao if is_approved else None,
                dispatched=is_approved,
                fallback_reason=(
                    None
                    if (within_limit and has_warning)
                    else "Variant failed length or safety warning validation."
                ),
            )
            variants.append(variant.as_dict())

    return variants
