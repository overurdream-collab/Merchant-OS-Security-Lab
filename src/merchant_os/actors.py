"""Trusted actor context boundary; authentication remains an injected adapter."""
from dataclasses import dataclass
from typing import Protocol

from .commerce_errors import IdentityRequired


@dataclass(frozen=True)
class VerifiedIdentityContext:
    actor_type: str
    actor_ref: str
    verification_id: str
    verified_by: str
    verified_at: str


class IdentityVerifier(Protocol):
    def verify(self, context: VerifiedIdentityContext, action: str, resource: dict) -> bool: ...


def require_actor(context, verifier, action: str, resource: dict) -> VerifiedIdentityContext:
    if (not isinstance(context, VerifiedIdentityContext) or verifier is None
            or not context.verification_id.strip()
            or context.actor_type not in {"SYSTEM", "CUSTOMER", "MERCHANT", "ADMIN"}
            or verifier.verify(context, action, resource) is not True):
        raise IdentityRequired()
    return context
