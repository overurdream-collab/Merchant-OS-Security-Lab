import hmac
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone

from .intake import intake_message
from .router import route_message
from .agents import run_agent
from .whatsapp import send_text, WhatsAppConfigError
from . import database as database_module
from .database import ensure_schema, ensure_intelligence_schema
from .catalog import ensure_catalog_schema
from .orders import ensure_order_schema
from .merchants import ensure_merchant_schema
from .outreach import ensure_outreach_schema
from .operations import ensure_operations_schema
from .runtime_status import runtime_status


DB_PATH = os.getenv("MERCHANT_OS_DB", "data/merchant_os.db")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
APP_SECRET = os.getenv("META_APP_SECRET", "")
HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_db():
    database_module.DB_PATH = DB_PATH
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    with database_module.get_connection() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                received_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_messages (
                message_id TEXT PRIMARY KEY,
                received_at TEXT NOT NULL,
                wa_id TEXT,
                sender_name TEXT,
                message_type TEXT,
                message_text TEXT,
                raw_payload TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_statuses (
                status_key TEXT PRIMARY KEY,
                received_at TEXT NOT NULL,
                message_id TEXT,
                status TEXT,
                recipient_id TEXT,
                raw_payload TEXT NOT NULL
            )
            """
        )

        db.commit()

    ensure_schema()
    ensure_catalog_schema()
    ensure_order_schema()
    ensure_merchant_schema()
    ensure_outreach_schema()
    ensure_operations_schema()
    ensure_intelligence_schema()



def already_seen(event_id):
    with database_module.get_connection() as db:
        result = db.execute(
            "SELECT 1 FROM webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()

    return result is not None


def record_event(event_id, payload):
    with database_module.get_connection() as db:
        db.execute(
            """
            INSERT OR IGNORE INTO webhook_events
            (event_id, received_at, payload)
            VALUES (?, ?, ?)
            """,
            (
                event_id,
                utc_now(),
                json.dumps(payload, ensure_ascii=False),
            ),
        )


def extract_events(payload):
    events = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}

            for message in value.get("messages", []) or []:
                text = ""

                if message.get("type") == "text":
                    text = (
                        (message.get("text") or {}).get("body")
                        or ""
                    )

                events.append(
                    (
                        "message",
                        message,
                        text,
                        value,
                    )
                )

            for status in value.get("statuses", []) or []:
                events.append(
                    (
                        "status",
                        status,
                        "",
                        value,
                    )
                )

    return events


def process_payload(payload):
    ensure_db()

    processed = []

    for kind, obj, text, value in extract_events(payload):

        if kind == "message":

            message_id = obj.get("id")

            if not message_id:
                message_id = hashlib.sha256(
                    json.dumps(
                        obj,
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()

            event_id = "message:" + message_id

            if already_seen(event_id):
                processed.append(
                    {
                        "type": kind,
                        "id": message_id,
                        "duplicate": True,
                    }
                )
                continue

            record_event(event_id, payload)

            contacts = value.get("contacts") or [{}]
            contact = contacts[0]

            profile = contact.get("profile") or {}

            wa_id = (
                contact.get("wa_id")
                or obj.get("from")
            )

            with database_module.get_connection() as db:
                db.execute(
                    """
                    INSERT OR IGNORE INTO customer_messages
                    (
                        message_id,
                        received_at,
                        wa_id,
                        sender_name,
                        message_type,
                        message_text,
                        raw_payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        utc_now(),
                        wa_id,
                        profile.get("name"),
                        obj.get("type"),
                        text,
                        json.dumps(
                            {
                                "message": obj,
                                "value": value,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )

            intake = intake_message(
                message_id=message_id,
                wa_id=wa_id,
                sender_name=profile.get("name"),
                message_type=obj.get("type"),
                text=text,
                raw_payload={"message": obj, "value": value},
            )
            routing = route_message(text)
            agent_result = run_agent(text, routing)

            outbound = None
            if wa_id and agent_result.get("text"):
                try:
                    outbound = send_text(wa_id, agent_result["text"])
                except WhatsAppConfigError:
                    outbound = None
                except Exception as exc:
                    print("WhatsApp outbound error:", repr(exc))
                    outbound = None

            processed.append(
                {
                    "type": "message",
                    "id": message_id,
                    "duplicate": False,
                    "wa_id": wa_id,
                    "text": text,
                    "customer_id": intake["customer"]["id"],
                    "conversation_id": intake["conversation"]["id"],
                    "intent": routing["intent"],
                    "agent": routing["agent"],
                    "reply": agent_result.get("text"),
                    "outbound_sent": outbound is not None,
                }
            )

        else:

            message_id = obj.get("id") or ""

            status_key = (
                f"{message_id}:"
                f"{obj.get('status')}:"
                f"{obj.get('timestamp')}:"
                f"{obj.get('recipient_id')}"
            )

            event_id = "status:" + status_key

            if already_seen(event_id):
                processed.append(
                    {
                        "type": kind,
                        "id": message_id,
                        "status": obj.get("status"),
                        "duplicate": True,
                    }
                )
                continue

            record_event(event_id, payload)

            with database_module.get_connection() as db:
                db.execute(
                    """
                    INSERT OR IGNORE INTO whatsapp_statuses
                    (
                        status_key,
                        received_at,
                        message_id,
                        status,
                        recipient_id,
                        raw_payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        status_key,
                        utc_now(),
                        message_id,
                        obj.get("status"),
                        obj.get("recipient_id"),
                        json.dumps(
                            obj,
                            ensure_ascii=False,
                        ),
                    ),
                )

            processed.append(
                {
                    "type": "status",
                    "id": message_id,
                    "status": obj.get("status"),
                    "duplicate": False,
                }
            )

    return processed


def valid_signature(raw, header):
    if not APP_SECRET:
        return True

    if not header or not header.startswith("sha256="):
        return False

    supplied = header.split("=", 1)[1]

    expected = hmac.new(
        APP_SECRET.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        supplied,
        expected,
    )


class Handler(BaseHTTPRequestHandler):

    server_version = "MerchantOSWebhook/1.3"

    def send_json(self, code, body):

        raw = json.dumps(
            body,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(code)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(raw)),
        )

        self.end_headers()

        self.wfile.write(raw)

    def send_html(self, code, html):

        raw = html.encode("utf-8")

        self.send_response(code)

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(raw)),
        )

        self.end_headers()

        self.wfile.write(raw)

    def do_GET(self):

        parsed = urlparse(self.path)

        # -------------------------------------------------
        # Health Check
        # -------------------------------------------------

        if parsed.path == "/health":

            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "merchant-os-whatsapp-webhook",
                    "time": utc_now(),
                    **runtime_status(),
                },
            )

            return

        # -------------------------------------------------
        # Privacy Policy
        # -------------------------------------------------

        if parsed.path == "/privacy":

            html = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Merchant OS Privacy Policy</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>

<body>

<h1>Merchant OS Privacy Policy</h1>

<p>
Merchant OS is a business automation platform designed to help merchants
manage products, customer communications, orders and sales channels.
</p>

<h2>Information We Process</h2>

<p>
Depending on the services used, Merchant OS may process merchant information,
customer contact information, messages, product information, order information
and technical information required to operate the service.
</p>

<h2>How We Use Information</h2>

<p>
Information is used to provide and improve merchant services, process orders,
communicate with customers, maintain security and operate connected business
integrations.
</p>

<h2>WhatsApp Data</h2>

<p>
When WhatsApp is connected, Merchant OS may receive messages, sender
identifiers, message status information and other data made available through
the WhatsApp Business API.
</p>

<h2>Data Sharing</h2>

<p>
We do not sell personal information.
Information may be processed by connected service providers when necessary
to provide requested functionality.
</p>

<h2>Data Retention</h2>

<p>
Information is retained only for as long as reasonably necessary to provide
the service, maintain records, comply with applicable requirements and protect
the service.
</p>

<h2>Data Deletion</h2>

<p>
Users may request deletion of their personal information by following the
instructions available on the Merchant OS Data Deletion page.
</p>

<h2>Contact</h2>

<p>
For privacy-related requests, contact the Merchant OS support team through
the contact information associated with the application.
</p>

<p>
Last updated: September 2026
</p>

</body>
</html>
"""

            self.send_html(200, html)

            return

        # -------------------------------------------------
        # Data Deletion
        # -------------------------------------------------

        if parsed.path == "/data-deletion":

            html = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Merchant OS Data Deletion</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>

<body>

<h1>Merchant OS Data Deletion Instructions</h1>

<p>
Users may request deletion of personal information associated with
Merchant OS.
</p>

<h2>How to Request Deletion</h2>

<ol>

<li>
Contact the Merchant OS support team using the contact information
associated with the application.
</li>

<li>
State that you are requesting deletion of your personal data.
</li>

<li>
Provide enough information to identify the relevant account or business
connection.
</li>

</ol>

<h2>Processing the Request</h2>

<p>
We will review the request and delete eligible personal information,
subject to applicable legal, security and record-keeping requirements.
</p>

<p>
Last updated: September 2026
</p>

</body>
</html>
"""

            self.send_html(200, html)

            return

        # -------------------------------------------------
        # WhatsApp Webhook Verification
        # -------------------------------------------------

        if parsed.path != "/webhooks/whatsapp":

            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "not_found",
                },
            )

            return

        query = parse_qs(parsed.query)

        mode = query.get(
            "hub.mode",
            [""],
        )[0]

        token = query.get(
            "hub.verify_token",
            [""],
        )[0]

        challenge = query.get(
            "hub.challenge",
            [""],
        )[0]

        if (
            mode == "subscribe"
            and VERIFY_TOKEN
            and hmac.compare_digest(
                token,
                VERIFY_TOKEN,
            )
        ):

            raw = challenge.encode("utf-8")

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8",
            )

            self.send_header(
                "Content-Length",
                str(len(raw)),
            )

            self.end_headers()

            self.wfile.write(raw)

            return

        self.send_json(
            403,
            {
                "ok": False,
                "error": "verification_failed",
            },
        )

    def do_POST(self):

        parsed = urlparse(self.path)

        if parsed.path != "/webhooks/whatsapp":

            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "not_found",
                },
            )

            return

        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        raw = self.rfile.read(length)

        signature = self.headers.get(
            "X-Hub-Signature-256"
        )

        if not valid_signature(
            raw,
            signature,
        ):

            self.send_json(
                403,
                {
                    "ok": False,
                    "error": "invalid_signature",
                },
            )

            return

        try:

            payload = json.loads(
                raw.decode("utf-8")
            )

        except Exception:

            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "invalid_json",
                },
            )

            return

        if payload.get("object") not in (
            None,
            "whatsapp_business_account",
        ):

            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "unsupported_object",
                },
            )

            return

        try:

            processed = process_payload(
                payload
            )

        except Exception as exc:

            print(
                "Webhook processing error:",
                repr(exc),
            )

            self.send_json(
                500,
                {
                    "ok": False,
                    "error": "processing_failed",
                },
            )

            return

        self.send_json(
            200,
            {
                "ok": True,
                "processed": processed,
            },
        )

    def log_message(self, fmt, *args):

        print(
            "%s %s"
            % (
                self.log_date_time_string(),
                fmt % args,
            )
        )


def run():

    ensure_db()

    print(
        f"Merchant OS WhatsApp Webhook listening on "
        f"{HOST}:{PORT}"
    )

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    server.serve_forever()


if __name__ == "__main__":
    run()
