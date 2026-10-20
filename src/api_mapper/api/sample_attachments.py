"""Persist response examples separately from their authoritative API specification."""

import uuid
from dataclasses import dataclass
from pathlib import Path

from api_mapper.loaders.response_samples import attach_responses, parse_response
from api_mapper.models import ApiSpec


@dataclass(frozen=True)
class SampleAttachment:
    id: str
    file_id: str
    endpoint: str
    names: tuple[str, ...]
    paths: tuple[str, ...]


def store_samples(
    root: Path, file_id: str, spec: ApiSpec, endpoint: str, uploads: list[tuple[str, bytes]]
) -> SampleAttachment:
    if not uploads:
        raise ValueError("choose at least one JSON response")
    samples = [(Path(name).name, parse_response(name, content)) for name, content in uploads]
    attach_responses(spec, endpoint, samples)
    identifier = uuid.uuid4().hex[:12]
    folder = root / "response-samples" / identifier
    folder.mkdir(parents=True)
    paths = []
    for index, (_, content) in enumerate(uploads):
        path = folder / f"{index}.json"
        path.write_bytes(content)
        paths.append(str(path))
    return SampleAttachment(identifier, file_id, endpoint, tuple(name for name, _ in samples), tuple(paths))


def apply_samples(spec: ApiSpec, attachments: list[SampleAttachment], file_id: str) -> ApiSpec:
    for attachment in attachments:
        if attachment.file_id == file_id:
            samples = [
                (name, parse_response(name, Path(path).read_bytes()))
                for name, path in zip(attachment.names, attachment.paths, strict=True)
            ]
            spec = attach_responses(spec, attachment.endpoint, samples)
    return spec
