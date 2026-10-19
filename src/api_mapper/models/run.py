from dataclasses import dataclass, field
from enum import StrEnum

from api_mapper.models.api_spec import ApiSpec
from api_mapper.models.call_plan import EndpointCallPlan
from api_mapper.models.error_mapping import ErrorMapping
from api_mapper.models.mapping import FieldMapping, MappingStatus


class StageState(StrEnum):
    STARTED = "started"
    FINISHED = "finished"
    FAILED = "failed"
    INFO = "info"


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    state: StageState
    message: str
    counts: dict[str, int] = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass
class MappingRun:
    upstream: ApiSpec
    downstreams: tuple[ApiSpec, ...]
    mappings: list[FieldMapping]
    error_mappings: list[ErrorMapping] = field(default_factory=list)
    call_plans: list[EndpointCallPlan] = field(default_factory=list)
    events: list[ProgressEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_status(self, status: MappingStatus) -> list[FieldMapping]:
        return [m for m in self.mappings if m.status == status]

    def status_counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in MappingStatus}
        for mapping in self.mappings:
            counts[mapping.status.value] += 1
        return counts
