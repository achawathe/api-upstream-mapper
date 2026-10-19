from pathlib import Path

from api_mapper.loaders.document import SpecLoadError, load_document, parse_document
from api_mapper.loaders.openapi_loader import build_api_spec, load_api_spec
from api_mapper.loaders.sample_inference import infer_schema
from api_mapper.loaders.sample_loader import api_from_payloads, is_sample_manifest, load_sample_manifest
from api_mapper.models import ApiSpec


def load_any(path: Path, name: str | None = None) -> ApiSpec:
    """Loads an OpenAPI/Swagger spec, schema fragment, or sample manifest, whichever the file is."""
    document = load_document(path)
    if is_sample_manifest(document):
        return load_sample_manifest(path)
    return build_api_spec(document, source=str(path), base_dir=path.parent, name=name)


__all__ = [
    "SpecLoadError",
    "api_from_payloads",
    "build_api_spec",
    "infer_schema",
    "load_any",
    "load_api_spec",
    "load_document",
    "load_sample_manifest",
    "parse_document",
]
