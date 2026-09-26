from .database import (
    ensure_schema,
    upsert_customer,
    get_or_create_conversation,
    save_message,
)


def intake_message(message_id, wa_id, sender_name, message_type, text, raw_payload):
    if not wa_id:
        raise ValueError("Missing WhatsApp customer ID")

    ensure_schema()
    customer = upsert_customer(wa_id=wa_id, name=sender_name)
    conversation = get_or_create_conversation(customer_id=customer["customer_id"])

    save_message(
        message_id=message_id,
        conversation_id=conversation["conversation_id"],
        customer_id=customer["customer_id"],
        direction="inbound",
        message_type=message_type,
        text=text,
        raw_payload=raw_payload,
    )

    return {
        "customer": {
            "id": customer["customer_id"],
            "wa_id": customer["wa_id"],
            "name": customer["name"],
        },
        "conversation": {
            "id": conversation["conversation_id"],
            "status": conversation["status"],
        },
        "message": {
            "id": message_id,
            "type": message_type,
            "text": text,
        },
    }
