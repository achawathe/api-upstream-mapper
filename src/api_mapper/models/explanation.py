"""Read-only requests for explaining an unsaved mapping and its conversion steps."""

from typing import Any

from pydantic import BaseModel


class ExplanationRequest(BaseModel):
    target_key: str
    source_key: str
    transforms: list[dict[str, Any]] | None = None
