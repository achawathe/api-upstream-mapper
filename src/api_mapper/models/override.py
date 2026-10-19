from dataclasses import dataclass
from enum import StrEnum


class OverrideAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    CHOOSE = "choose"


@dataclass(frozen=True)
class Override:
    """A person's decision on one target field; survives re-runs."""

    target_key: str
    action: OverrideAction
    source_key: str | None = None
    note: str = ""
    author: str = ""
