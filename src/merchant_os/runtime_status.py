from __future__ import annotations

import os

from .whatsapp import whatsapp_config_status


def runtime_status() -> dict:
    wa = whatsapp_config_status()
    return {
        "service": "merchant-os",
        "environment": os.getenv("MERCHANT_OS_ENV", "development"),
        "whatsapp": wa,
        "webhook": {
            "verify_token_configured": bool(os.getenv("WHATSAPP_VERIFY_TOKEN")),
            "app_secret_configured": bool(os.getenv("META_APP_SECRET")),
        },
        "database": {
            "path": os.getenv("MERCHANT_OS_DB", "data/merchant_os.db"),
        },
    }
