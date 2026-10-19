from pathlib import Path

from api_mapper.normalize.lexicon import Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline, PipelineResult
from tests.conftest import SAMPLES

DOWNSTREAMS = [
    SAMPLES / "downstream" / path
    for path in (
        "core-accounts/openapi.yaml",
        "deposits/swagger.json",
        "cards/openapi.json",
        "loans/openapi.yaml",
        "parties/openapi.yaml",
        "ledger/openapi.json",
        "routing/manifest.yaml",
        "transfers/openapi.yaml",
    )
]
UPSTREAM = SAMPLES / "upstream/fdx/core-exchange-6.4.yaml"
ERROR_CATALOG = SAMPLES / "upstream/fdx/error-catalog.yaml"
ANSWER_KEY = SAMPLES / "answer_key.yaml"


def run_sample(lexicon: Lexicon, downstreams: list[Path] | None = None, overrides=()) -> PipelineResult:
    pipeline = MappingPipeline(lexicon)
    inputs = pipeline.load(UPSTREAM, downstreams or DOWNSTREAMS, ERROR_CATALOG, tuple(overrides))
    return pipeline.run(inputs)
