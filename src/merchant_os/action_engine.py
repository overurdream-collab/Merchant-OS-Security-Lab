from typing import Any, Dict

class ActionEngine:
    """Action dispatcher requiring an injected verifier and approval record.

    ``approved=True`` is retained as a compatibility argument only. A boolean
    can never authorize an action. Commerce Core actions should use
    CommerceControlPlane, which also binds approval to proposal and scope.
    """
    def __init__(self, approval_verifier=None):
        self._handlers: Dict[str, Any] = {}
        self._approval_verifier = approval_verifier
    def register(self, action: str, handler: Any) -> None:
        self._handlers[action] = handler
    def execute(self, action: str, payload: Dict[str, Any], approved: bool = False,
                approval_record: Any = None) -> Dict[str, Any]:
        del approved  # A caller-supplied flag is deliberately not authorization.
        try:
            verified = (self._approval_verifier is not None and approval_record is not None
                        and self._approval_verifier(action, payload, approval_record) is True)
        except Exception:
            verified = False
        if not verified:
            return {"status": "blocked", "reason": "verified_approval_record_required", "action": action}
        handler = self._handlers.get(action)
        if not handler:
            return {"status": "blocked", "reason": "no_action_handler", "action": action}
        return {"status": "executed", "action": action, "result": handler(payload)}
