from typing import Any, Dict
from .research_tools import DuckDuckGoResearchProvider, ResearchProvider, WebPageEnricher, ResearchResult
from .merchant_intelligence import MerchantIntelligenceEngine
from .source_discovery import SourceDiscoveryPlanner, classify_source, MerchantEntityResolver
from .taxonomy import enrich_merchant, enrich_customer
from .data_intelligence import DataIntelligenceAgent
from .strategist import StrategicDeveloperAgent

class SpecialistBase:
    def __init__(self, name: str): self.name = name
    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"specialist": self.name, "finding": {"subject": payload.get("subject", {}), "evidence_count": len(payload.get("evidence", []))}}

class ResearchAgent(SpecialistBase):
    def __init__(self, name="research", provider: ResearchProvider | None = None):
        super().__init__(name); self.provider = provider or DuckDuckGoResearchProvider()

    def run(self, payload):
        candidates = list(payload.get("candidates", []))
        subject = payload.get("subject", {})
        query = payload.get("query") or subject.get("research_query")
        discovery_enabled = bool(subject.get("discovery_enabled", True))
        category = subject.get("category", "")
        city = subject.get("city", "")
        source_types = subject.get("source_types")
        max_queries = int(subject.get("max_discovery_queries", 40))
        per_query_limit = int(subject.get("per_query_limit", 5))
        total_limit = int(payload.get("limit", subject.get("discovery_limit", 100)))
        search_trace = []

        if query and not candidates:
            try:
                if discovery_enabled and (category or city or subject.get("discovery_terms") or source_types):
                    planned = SourceDiscoveryPlanner().plan(
                        category, city, subject.get("discovery_terms", []), source_types, max_queries
                    )
                    for dq in planned:
                        if len(candidates) >= total_limit:
                            break
                        results = self.provider.search(dq.query, min(per_query_limit, total_limit - len(candidates)))
                        search_trace.append({"source_type": dq.source_type, "platform": dq.platform,
                                             "query": dq.query, "results": len(results)})
                        candidates.extend({
                            "name": r.title, "url": r.url, "source_url": r.url, "snippet": r.snippet,
                            "channel": dq.platform, "source_type": dq.source_type,
                            "category": category, "city": city, "captured_at": r.captured_at
                        } for r in results)
                else:
                    results = self.provider.search(query, total_limit)
                    search_trace.append({"source_type": "web_search", "platform": "web",
                                         "query": query, "results": len(results)})
                    candidates = [{
                        "name": r.title, "url": r.url, "source_url": r.url, "snippet": r.snippet,
                        "channel": payload.get("channel"),
                        "source_type": classify_source(r.url, r.title, r.snippet),
                        "category": category, "city": city, "captured_at": r.captured_at
                    } for r in results]
            except Exception as exc:
                return {"research": [], "evidence": [], "research_error": str(exc),
                        "research_query": query, "discovery_trace": search_trace}

        findings, evidence, seen_urls = [], [], set()
        for c in candidates[:total_limit]:
            url = c.get("url") or c.get("source_url")
            if url and url in seen_urls:
                continue
            if url: seen_urls.add(url)
            source_type = c.get("source_type") or classify_source(
                url or "", c.get("name", ""), c.get("snippet", "")
            )
            item = {
                "name": c.get("name"), "url": url, "source_url": url, "source_type": source_type,
                "platform": c.get("platform") or c.get("channel"), "channel": c.get("channel"),
                "channels": c.get("channels"), "phone": c.get("phone"), "whatsapp": c.get("whatsapp"),
                "email": c.get("email"), "category": c.get("category"), "city": c.get("city"),
                "snippet": c.get("snippet", ""), "captured_at": c.get("captured_at")
            }
            findings.append(item)
            evidence.append({"source": url or "candidate_input", "captured_at": item.get("captured_at"),
                             "data": item})

        findings = MerchantEntityResolver().resolve(findings)
        findings = [enrich_merchant(x) for x in findings]

        enriched = []
        enricher = WebPageEnricher()
        max_enrich = int(subject.get("max_enrichment", 50))
        for index, item in enumerate(findings):
            if index >= max_enrich or not item.get("url"):
                enriched.append(item)
                continue
            try:
                extra = enricher.enrich(ResearchResult(
                    title=item.get("name") or "", url=item.get("url") or "",
                    snippet=item.get("snippet") or "", captured_at=item.get("captured_at") or ""
                ))
                item["enrichment"] = extra
                if extra.get("channels"):
                    item["channels"] = sorted(set(item.get("channels", []) or []) | set(extra["channels"]))
                    item["channel"] = item["channels"][0] if item["channels"] else item.get("channel")
                if extra.get("phones") and not item.get("phone"):
                    item["phone"] = extra["phones"][0]
            except Exception as exc:
                item["enrichment_error"] = str(exc)
            enriched.append(item)

        return {
            "research": enriched,
            "evidence": evidence,
            "research_query": query,
            "research_provider": type(self.provider).__name__,
            "discovery_trace": search_trace,
            "discovery_stats": {
                "queries": len(search_trace),
                "raw_candidates": len(candidates),
                "unique_merchants": len(enriched),
                "facebook_results": sum(x.get("results", 0) for x in search_trace if x.get("platform") == "facebook"),
                "whatsapp_results": sum(x.get("results", 0) for x in search_trace if x.get("platform") == "whatsapp"),
            }
        }

class IntelligenceAgent(SpecialistBase):
    def run(self, payload):
        merchants = payload.get("research", [])
        ranked = MerchantIntelligenceEngine().rank(merchants, payload.get("evidence", []), payload.get("subject", {}))
        return {"intelligence": [{"merchant": x["merchant"].get("name"), "signals": x["factors"]} for x in ranked],
                "merchant_scores": ranked}

class DataAgent(SpecialistBase):
    def run(self, payload):
        records = payload.get("research", [])
        customers = payload.get("customers", [])
        intelligence = DataIntelligenceAgent().analyze(records, customers, payload.get("business_events"))
        return {
            "data_quality": {
                "records": len(records),
                "missing_city": sum(not x.get("city") for x in records),
                "missing_channel": sum(not x.get("channel") and not x.get("channels") for x in records),
                "taxonomy": intelligence["merchant_metrics"],
            },
            "data_intelligence": intelligence,
        }

class MarketAgent(SpecialistBase):
    def run(self, payload):
        s = payload.get("subject", {})
        return {"market_analysis": {"category": s.get("category"), "city": s.get("city"), "candidate_count": len(payload.get("research", []))}}

class CustomerAgent(SpecialistBase):
    def run(self, payload):
        profile = dict(payload.get("subject", {}).get("customer_profile", {}) or {})
        return {"customer_profile": enrich_customer(profile)}

class SalesAgent(SpecialistBase):
    def run(self, payload):
        return {"sales_signals": [{"merchant": x.get("name"), "channel": x.get("channel")} for x in payload.get("research", []) if x.get("channel") or x.get("channels")]}

class StrategyAgent(SpecialistBase):
    def run(self, payload):
        context = {
            "merchants": payload.get("research", []),
            "customers": payload.get("customers", []),
            "data_intelligence": payload.get("data_intelligence", {}),
        }
        development = StrategicDeveloperAgent().analyze(context)
        return {
            "strategy": payload.get("subject", {}).get("strategy", "commission_marketplace"),
            "next_action": "merchant_outreach",
            "strategic_development": development,
        }

class VerificationAgent(SpecialistBase):
    def run(self, payload):
        items = payload.get("evidence", [])
        valid = [x for x in items if x.get("source") and isinstance(x.get("data"), dict)]
        return {"verified": bool(items) and len(valid) == len(items), "verification": {"checked": len(items), "valid": len(valid)}}

class ExecutionAgent(SpecialistBase):
    """Route approved work to Commerce Core without bypassing the control plane.

    Legacy non-commerce execution keeps using AgentNetwork. Commerce actions
    require an injected CommerceControlPlane and CommerceService; the caller
    supplies a persisted approval_id plus the exact Proposal that was approved.
    """

    COMMERCE_ACTION_SCOPES = {
        "catalog": ("commerce/catalog",),
        "offers": ("commerce/catalog",),
        "cart": ("commerce/cart",),
        "add_to_cart": ("commerce/cart",),
        "update_cart_quantity": ("commerce/cart",),
        "remove_from_cart": ("commerce/cart",),
        "clear_cart": ("commerce/cart",),
        "set_cart_delivery_zone": ("commerce/cart",),
        "quote": ("commerce/quote",),
        "checkout": ("commerce/orders",),
        "orders": ("commerce/orders",),
        "cancel": ("commerce/orders",),
        "delivery": ("commerce/delivery",),
        "settlement": ("commerce/settlement",),
    }

    def __init__(self, name="execution", network=None, commerce_service=None, commerce_control_plane=None):
        super().__init__(name)
        self.network = network
        self.commerce_service = commerce_service
        self.commerce_control_plane = commerce_control_plane

    def _register_commerce_actions(self):
        if self.commerce_service is None or self.commerce_control_plane is None:
            return
        for action, scopes in self.COMMERCE_ACTION_SCOPES.items():
            if action in getattr(self.commerce_control_plane, "_actions", {}):
                continue

            def handler(proposal, action_name=action):
                parameters = dict(proposal.parameters or {})
                service_method = getattr(self.commerce_service, action_name, None)
                if service_method is None:
                    raise ValueError(f"commerce_action_not_supported:{action_name}")
                result = service_method(**parameters)
                return result if isinstance(result, dict) else {"result": result}

            self.commerce_control_plane._scope_configuration.setdefault(action, scopes)
            self.commerce_control_plane.register_action(action, handler)

    @staticmethod
    def _proposal_from_payload(payload):
        from .commerce_agent import Proposal

        proposal = payload.get("proposal")
        if isinstance(proposal, Proposal):
            return proposal
        if not isinstance(proposal, dict):
            return None
        required = ("task_id", "action", "scope", "summary")
        if not all(key in proposal for key in required):
            return None
        return Proposal(
            task_id=str(proposal["task_id"]),
            action=str(proposal["action"]),
            scope=tuple(str(item) for item in proposal["scope"]),
            summary=str(proposal["summary"]),
            parameters=dict(proposal.get("parameters") or {}),
            proposal_id=str(proposal.get("proposal_id") or ""),
        )

    def _run_commerce(self, payload):
        if self.commerce_service is None or self.commerce_control_plane is None:
            return {"status": "blocked", "reason": "commerce_control_plane_unavailable"}

        approval_id = payload.get("approval_id")
        proposal = self._proposal_from_payload(payload)
        if not isinstance(approval_id, str) or not approval_id.strip():
            return {"status": "blocked", "reason": "approval_id_required"}
        if proposal is None:
            return {"status": "blocked", "reason": "proposal_required"}

        try:
            self._register_commerce_actions()
            result = self.commerce_control_plane.execute(proposal, approval_id)
            return {
                "status": "executed",
                "agent": self.name,
                "commerce_action": proposal.action,
                "approval_id": approval_id,
                "result": dict(result),
            }
        except Exception as exc:
            return {
                "status": "blocked",
                "reason": "commerce_execution_rejected",
                "detail": str(exc),
                "commerce_action": proposal.action,
                "approval_id": approval_id,
            }

    def run(self, payload):
        if payload.get("commerce_action"):
            return self._run_commerce(payload)
        if not payload.get("approved"):
            return {"status": "blocked", "reason": "approval_required"}
        if not self.network:
            return {"status": "blocked", "reason": "agent_network_unavailable"}
        return self.network.dispatch(payload.get("agent", "general_router"), payload)


class SupervisorAgent(SpecialistBase):
    def run(self, payload):
        veto = bool(payload.get("supervisor_veto", False) or payload.get("subject", {}).get("supervisor_veto", False))
        return {"veto": veto, "status":"reviewed", "reason":"explicit supervisor veto" if veto else "no veto"}

def build_specialist_agents(network=None, research_provider=None, commerce_service=None, commerce_control_plane=None):
    return {"research":ResearchAgent(provider=research_provider), "intelligence":IntelligenceAgent("intelligence"),
            "data":DataAgent("data"), "market":MarketAgent("market"), "customer":CustomerAgent("customer"),
            "sales":SalesAgent("sales"), "strategy":StrategyAgent("strategy"),
            "verification":VerificationAgent("verification"),
            "execution":ExecutionAgent(network=network, commerce_service=commerce_service,
                                       commerce_control_plane=commerce_control_plane),
            "supervisor":SupervisorAgent("supervisor")}
