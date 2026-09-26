from dataclasses import dataclass
from typing import Callable, Dict, Any

from .router import route_message


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    handler: Callable[[str, Dict[str, Any]], Dict[str, Any]]


def sales_agent(text, context):
    intent = context.get("intent", "unknown")
    if intent == "price_request":
        return {"type": "text", "text": "أكيد، أرسل اسم المنتج أو صورته وسأتحقق لك من السعر والتوفر."}
    if intent == "purchase":
        return {"type": "text", "text": "أكيد. أرسل اسم المنتج والكمية، وسأكمل معك الطلب."}
    return {"type": "text", "text": "أكيد، كيف أقدر أساعدك في المنتج؟"}


def order_agent(text, context):
    return {"type": "text", "text": "أكيد. أرسل رقم الطلب لأتحقق من حالته."}


def customer_agent(text, context):
    return {"type": "text", "text": "أهلاً بك. وضّح لي طلبك وسأساعدك مباشرة."}


def human_handoff(text, context):
    return {"type": "text", "text": "تمام، سأحوّل المحادثة لموظف خدمة العملاء."}


def general_router(text, context):
    return {"type": "text", "text": "أهلاً بك في Merchant OS. كيف أقدر أخدمك؟"}


AGENTS = {
    "sales_agent": Agent("sales_agent", "Sales and product inquiries", sales_agent),
    "order_agent": Agent("order_agent", "Order status and order operations", order_agent),
    "customer_agent": Agent("customer_agent", "Customer information and support", customer_agent),
    "human_handoff": Agent("human_handoff", "Human support escalation", human_handoff),
    "general_router": Agent("general_router", "Fallback routing agent", general_router),
}


def run_agent(text, context=None):
    context = dict(context or {})
    routing = route_message(text)
    context.update(routing)
    agent_name = routing["agent"]
    agent = AGENTS[agent_name]
    result = agent.handler(text, context)
    result.update({"agent": agent_name, "intent": routing["intent"]})
    return result
