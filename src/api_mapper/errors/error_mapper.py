"""Maps every downstream error to the upstream status and code the aggregate API should return.

1. keyword   the downstream code/message names a catalog error ("Account is closed" -> 705)
2. status    passthrough of the HTTP status when no catalog entry fits (code left empty)
3. upstream-fault  502/503/504 become 503: the caller cannot fix a downstream outage
"""

from api_mapper.errors.catalog import ErrorCatalog
from api_mapper.models import DownstreamError, ErrorMapping, UpstreamError
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.normalize.tokenizer import singularize, split_identifier

MIN_KEYWORD_HITS = 2
GATEWAY_STATUSES = frozenset({"502", "503", "504"})


class ErrorMapper:
    def __init__(self, catalog: ErrorCatalog, lexicon: Lexicon):
        self.catalog = catalog
        self.lexicon = lexicon

    def map_all(self, errors: list[DownstreamError]) -> list[ErrorMapping]:
        return [self.map(error) for error in errors]

    def map(self, error: DownstreamError) -> ErrorMapping:
        best, hits = self._best_keyword_match(error)
        same_status = best is not None and best.http_status == error.http_status
        if best and (hits >= MIN_KEYWORD_HITS or (hits == 1 and same_status)):
            confidence = min(1.0, 0.6 + 0.1 * hits + (0.1 if same_status else 0.0))
            return ErrorMapping(error, best.http_status or error.http_status, best.code, f"keyword ({hits} matched)", round(confidence, 2))
        if error.http_status in GATEWAY_STATUSES:
            return ErrorMapping(error, "503", None, "upstream-fault: downstream outage reported as 503", 0.8)
        if error.http_status.startswith("5"):
            return ErrorMapping(error, "500", None, "upstream-fault: downstream failure reported as 500", 0.7)
        return ErrorMapping(error, error.http_status, None, "status passthrough; no catalog code fits", 0.5)

    def _best_keyword_match(self, error: DownstreamError) -> tuple[UpstreamError | None, int]:
        words = self._words(f"{error.code or ''} {error.message}")
        best: UpstreamError | None = None
        best_hits = 0
        for candidate in self.catalog.errors:
            hits = len(words & {singularize(k) for k in candidate.keywords})
            if hits > best_hits or (hits == best_hits and best and candidate.http_status == error.http_status):
                best, best_hits = candidate, hits
        return best, best_hits

    def _words(self, text: str) -> set[str]:
        tokens = split_identifier(text)
        concepts = self.lexicon.concepts_of_tokens(tokens)
        return {singularize(t) for t in tokens} | set(concepts)
