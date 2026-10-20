"""Persist optional documentation under its API ID, independently of spec upload paths."""

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from api_mapper.loaders.documentation import read_documentation
from api_mapper.models import ApiSpec
from api_mapper.models.documentation import DocumentationPassage


@dataclass(frozen=True)
class DocumentAttachment:
    id: str
    file_id: str
    names: tuple[str, ...]
    path: str
    endpoint: str = ''


def store_documents(root: Path, file_id: str, spec: ApiSpec, uploads: list[tuple[str, bytes]], endpoint: str = '') -> DocumentAttachment:
    if not uploads:
        raise ValueError('Choose documentation or paste text first')
    if endpoint and endpoint not in {e.key for e in spec.endpoints}:
        raise ValueError('Choose an endpoint belonging to this API')
    passages = [p for name, content in uploads for p in read_documentation(name, content, endpoint)]
    identifier = uuid.uuid4().hex[:12]
    folder = root / 'documentation' / identifier
    folder.mkdir(parents=True)
    path = folder / 'passages.json'
    try:
        path.write_text(json.dumps([asdict(p) for p in passages]), encoding='utf-8')
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return DocumentAttachment(identifier, file_id, tuple(Path(name).name for name, _ in uploads), str(path), endpoint)


def apply_documents(spec: ApiSpec, attachments: list[DocumentAttachment], file_id: str) -> ApiSpec:
    passages = tuple(DocumentationPassage(**p) for attachment in attachments if attachment.file_id == file_id
                     for p in json.loads(Path(attachment.path).read_text(encoding='utf-8')))
    return replace(spec, documentation=passages)
