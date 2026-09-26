from merchant_os.specialists import ExecutionAgent


class FakeCommerceService:
    def __init__(self):
        self.calls = []

    def checkout(self, **parameters):
        self.calls.append(("checkout", parameters))
        return {"order_id": 101, "status": "pending"}


class FakeCommerceControlPlane:
    def __init__(self):
        self._actions = {}
        self.executions = []

    def register_action(self, action, handler):
        self._actions[action] = handler

    def execute(self, proposal, approval_id):
        self.executions.append((proposal, approval_id))
        return self._actions[proposal.action](proposal)


def test_execution_agent_routes_commerce_action_through_control_plane():
    service = FakeCommerceService()
    control = FakeCommerceControlPlane()
    agent = ExecutionAgent(
        commerce_service=service,
        commerce_control_plane=control,
    )

    result = agent.run({
        "commerce_action": True,
        "approval_id": "approval-1",
        "proposal": {
            "task_id": "task-1",
            "action": "checkout",
            "scope": ["commerce/orders/101"],
            "summary": "Create the approved checkout",
            "parameters": {
                "cookie_header": "merchant_os_session=token",
                "idempotency_key": "pilot-order-1",
                "quote_revision_value": "quote-1",
                "recipient_name": "Pilot Customer",
                "recipient_phone": "+967700000000",
                "delivery_address": "Pilot address",
                "payment_method": "cod",
            },
            "proposal_id": "proposal-1",
        },
    })

    assert result["status"] == "executed"
    assert result["commerce_action"] == "checkout"
    assert result["approval_id"] == "approval-1"
    assert service.calls == [(
        "checkout",
        {
            "cookie_header": "merchant_os_session=token",
            "idempotency_key": "pilot-order-1",
            "quote_revision_value": "quote-1",
            "recipient_name": "Pilot Customer",
            "recipient_phone": "+967700000000",
            "delivery_address": "Pilot address",
            "payment_method": "cod",
        },
    )]
    assert len(control.executions) == 1


def test_execution_agent_blocks_commerce_without_approval_id():
    service = FakeCommerceService()
    control = FakeCommerceControlPlane()
    agent = ExecutionAgent(
        commerce_service=service,
        commerce_control_plane=control,
    )

    result = agent.run({
        "commerce_action": True,
        "proposal": {
            "task_id": "task-1",
            "action": "checkout",
            "scope": ["commerce/orders/101"],
            "summary": "Create the approved checkout",
            "parameters": {},
            "proposal_id": "proposal-1",
        },
    })

    assert result == {"status": "blocked", "reason": "approval_id_required"}
    assert not service.calls
    assert not control.executions
