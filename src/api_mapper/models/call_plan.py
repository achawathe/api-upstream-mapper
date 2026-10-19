from dataclasses import dataclass, field
from enum import StrEnum


class BindingSource(StrEnum):
    UPSTREAM_REQUEST = "upstream-request"
    PRIOR_STEP = "prior-step"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class InputBinding:
    parameter: str
    source: BindingSource
    reference: str = ""
    fanout: bool = False
    from_step: int | None = None
    location: str = "path"

    @property
    def key(self) -> str:
        return f"{self.location}:{self.parameter}"


@dataclass(frozen=True)
class CallStep:
    order: int
    api: str
    endpoint: str
    bindings: tuple[InputBinding, ...]
    variants: tuple[str, ...] = ()
    supplies_fields: int = 0
    pending_review_fields: int = 0
    supplies_only_inputs: bool = False

    @property
    def is_fanout(self) -> bool:
        return any(b.fanout for b in self.bindings)

    @property
    def awaits_review(self) -> bool:
        """Every field this call supplies is still unconfirmed, so the call may turn out unnecessary."""
        return self.supplies_fields > 0 and self.pending_review_fields == self.supplies_fields


@dataclass(frozen=True)
class EndpointCallPlan:
    upstream_endpoint: str
    steps: tuple[CallStep, ...] = ()
    unresolved_inputs: tuple[str, ...] = field(default=())
