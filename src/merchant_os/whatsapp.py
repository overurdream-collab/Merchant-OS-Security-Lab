import os
import requests


class WhatsAppConfigError(RuntimeError):
    pass


def _config():
    return {
        "graph_version": os.getenv("META_GRAPH_VERSION", "v23.0"),
        "access_token": os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
        "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
    }


def whatsapp_config_status():
    cfg = _config()
    return {
        "configured": bool(
            cfg["access_token"] and cfg["phone_number_id"]
        ),
        "graph_version": cfg["graph_version"],
        "phone_number_id_present": bool(cfg["phone_number_id"]),
        "access_token_present": bool(cfg["access_token"]),
    }


def send_text(to, text):
    cfg = _config()

    if not cfg["access_token"] or not cfg["phone_number_id"]:
        raise WhatsAppConfigError(
            "WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required"
        )

    if not to:
        raise ValueError("WhatsApp recipient is required")

    if not text:
        raise ValueError("WhatsApp message text is required")

    url = (
        f"https://graph.facebook.com/"
        f"{cfg['graph_version']}/"
        f"{cfg['phone_number_id']}/messages"
    )

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {cfg['access_token']}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        },
        timeout=20,
    )

    if not response.ok:
        try:
            details = response.json()
        except ValueError:
            details = response.text[:500]

        raise RuntimeError(
            f"WhatsApp Cloud API returned HTTP {response.status_code}: {details}"
        )

    return response.json()
