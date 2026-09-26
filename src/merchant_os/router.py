import re


INTENTS = (
    "purchase",
    "price_request",
    "order_status",
    "complaint",
    "human_agent",
    "information",
    "unknown",
)


def normalize(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def detect_intent(text):
    text = normalize(text)
    if not text:
        return "unknown"

    purchase_words = ["اشتري", "شراء", "اريد", "أريد", "اطلب", "طلب", "احجز", "حجز"]
    price_words = ["سعر", "كم", "بكم", "التكلفة", "اسعار", "أسعار"]
    status_words = ["طلبي", "الطلب", "وصل", "التوصيل", "الشحنة", "شحن"]
    complaint_words = ["شكوى", "مشكله", "مشكلة", "سيء", "سيئ", "لم يصل", "ما وصل"]
    human_words = ["موظف", "موظفة", "شخص", "خدمة العملاء", "اكلم احد", "أكلم أحد"]
    information_words = ["معلومات", "كيف", "هل يوجد", "هل متوفر", "متوفر", "ما هو"]

    if any(word in text for word in complaint_words):
        return "complaint"
    if any(word in text for word in human_words):
        return "human_agent"
    if any(word in text for word in status_words):
        return "order_status"
    if any(word in text for word in price_words):
        return "price_request"
    if any(word in text for word in purchase_words):
        return "purchase"
    if any(word in text for word in information_words):
        return "information"
    return "unknown"


def route_message(text):
    intent = detect_intent(text)
    agent_map = {
        "purchase": "sales_agent",
        "price_request": "sales_agent",
        "order_status": "order_agent",
        "complaint": "customer_agent",
        "human_agent": "human_handoff",
        "information": "customer_agent",
        "unknown": "general_router",
    }
    return {"intent": intent, "agent": agent_map[intent]}
