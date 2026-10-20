"""A cited passage from optional documentation attached to one API specification."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentationPassage:
    text: str
    location: str
    endpoint: str = ""
