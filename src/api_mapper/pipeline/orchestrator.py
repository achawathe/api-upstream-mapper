"""Runs the whole mapping process and reports each stage as it happens."""

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter

from api_mapper.errors.catalog import (
    ErrorCatalog,
    downstream_errors,
    load_error_catalog,
)
from api_mapper.errors.error_mapper import ErrorMapper
from api_mapper.loaders import SpecLoadError, load_any
from api_mapper.matching.assigner import Thresholds, assign
from api_mapper.matching.engine import MatchingEngine, PreparedMatch
from api_mapper.matching.reachability import Reachability
from api_mapper.matching.semantic import NlpSettings
from api_mapper.models import (
    ApiSpec,
    FieldMapping,
    FieldProfile,
    MappingRun,
    Override,
    ProgressEvent,
    StageState,
)
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.normalize.profiler import Profiler
from api_mapper.pipeline.overrides import apply_overrides
from api_mapper.planning.call_planner import CallPlanner

Listener = Callable[[ProgressEvent], None]
DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class PipelineInputs:
    """`endpoints` limits mapping to these upstream endpoint keys; empty maps every endpoint."""

    upstream: ApiSpec
    downstreams: tuple[ApiSpec, ...]
    error_catalog: ErrorCatalog | None = None
    overrides: tuple[Override, ...] = ()
    load_warnings: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()


@dataclass
class PipelineResult:
    run: MappingRun
    prepared: PreparedMatch = field(repr=False)
    sources: list[FieldProfile] = field(default_factory=list, repr=False)
    automatic: list[FieldMapping] = field(default_factory=list, repr=False)


class MappingPipeline:
    def __init__(
        self,
        lexicon: Lexicon,
        thresholds: Thresholds = DEFAULT_THRESHOLDS,
        listener: Listener | None = None,
        nlp: NlpSettings | None = None,
    ):
        self.lexicon = lexicon
        self.thresholds = thresholds
        self.engine = MatchingEngine(lexicon, thresholds, nlp)
        self._listener = listener
        self._events: list[ProgressEvent] = []

    def load(
        self,
        upstream: Path,
        downstreams: list[Path],
        error_catalog: Path | None = None,
        overrides: tuple[Override, ...] = (),
    ) -> PipelineInputs:
        warnings: list[str] = []
        with self._stage("load", "reading specs and samples") as counts:
            upstream_spec = load_any(upstream, _api_name(upstream))
            loaded = []
            for path in downstreams:
                try:
                    loaded.append(load_any(path, _api_name(path)))
                except SpecLoadError as error:
                    warnings.append(f"skipped downstream {error.source}: {error.reason}")
                    self._emit(ProgressEvent("load", StageState.FAILED, warnings[-1]))
            catalog = load_error_catalog(error_catalog) if error_catalog else None
            counts.update(
                upstream_endpoints=len(upstream_spec.endpoints), downstream_apis=len(loaded), skipped=len(warnings)
            )
        return PipelineInputs(upstream_spec, tuple(_unique_names(loaded)), catalog, overrides, tuple(warnings))

    def run(self, inputs: PipelineInputs) -> PipelineResult:
        self._events = []
        warnings = list(inputs.load_warnings)
        for spec in (inputs.upstream, *inputs.downstreams):
            warnings.extend(f"{spec.name}: {w}" for w in spec.warnings)

        with self._stage("flatten", "turning schemas into fields") as counts:
            upstream_nodes = flatten_spec(inputs.upstream)
            downstream_nodes = {spec.name: flatten_spec(spec) for spec in inputs.downstreams}
            scope = _scope(inputs.endpoints, inputs.upstream, warnings)
            counts.update(
                upstream_fields=sum(_in_scope(n.endpoint, scope) for n in upstream_nodes),
                downstream_fields=sum(map(len, downstream_nodes.values())),
            )
            if scope:
                counts.update(selected_endpoints=len(scope))
            documented = sum(
                bool(n.documentation)
                for n in [*upstream_nodes, *(n for nodes in downstream_nodes.values() for n in nodes)]
            )
            if any(s.documentation for s in (inputs.upstream, *inputs.downstreams)):
                self._emit(
                    ProgressEvent(
                        "flatten",
                        StageState.INFO,
                        "Documentation attached to declared fields; ambiguous or unnamed passages are not used",
                        {"documented_fields": documented},
                    )
                )

        with self._stage("profile", "reading names, context and qualifiers") as counts:
            profiler = Profiler(self.lexicon, Profiler.vocabulary_of(upstream_nodes))
            every_target = profiler.profile_spec(inputs.upstream, upstream_nodes)
            targets = [t for t in every_target if _in_scope(t.node.endpoint, scope)]
            sources = [
                p for spec in inputs.downstreams for p in profiler.profile_spec(spec, downstream_nodes[spec.name])
            ]
            counts.update(profiles=len(targets) + len(sources))

        with self._stage("score", "scoring candidate pairs") as counts:
            if self.engine.nlp.model_path:
                self._emit(ProgressEvent("score", StageState.INFO, f"local NLP enabled: {self.engine.nlp.model_path}"))
            reachability = Reachability(inputs.downstreams, sources, profiler.param_identity, self.lexicon)
            prepared = self.engine.prepare(targets, sources, reachability, every_target)
            candidates = prepared.score_all()
            counts.update(pairs_scored=sum(map(len, candidates.values())))

        with self._stage("assign", "choosing a source per field") as counts:
            automatic = assign(targets, candidates, self.thresholds)
            mappings = [_copy(m) for m in automatic]
            active, notes = _active_overrides(inputs.overrides, scope)
            warnings.extend(notes)
            warnings.extend(apply_overrides(mappings, active, prepared.score_pair))
            counts.update(fields=len(mappings), overrides=len(active))

        run = MappingRun(
            upstream=inputs.upstream,
            downstreams=inputs.downstreams,
            mappings=mappings,
            scope=tuple(sorted(scope or ())),
        )
        counts_by_status = run.status_counts()
        self._emit(ProgressEvent("assign", StageState.INFO, "status breakdown", counts_by_status))

        with self._stage("errors", "mapping downstream error responses") as counts:
            if inputs.error_catalog:
                found = [e for spec in inputs.downstreams for e in downstream_errors(spec)]
                run.error_mappings = ErrorMapper(inputs.error_catalog, self.lexicon).map_all(found)
            counts.update(errors=len(run.error_mappings))

        with self._stage("plan", "planning downstream calls") as counts:
            plans = CallPlanner(self.lexicon, inputs.upstream, inputs.downstreams, sources).plan(mappings)
            run.call_plans = [plan for plan in plans if _in_scope(plan.upstream_endpoint, scope)]
            counts.update(calls=sum(len(plan.steps) for plan in run.call_plans))

        run.warnings = warnings
        run.events = list(self._events)
        return PipelineResult(run=run, prepared=prepared, sources=sources, automatic=automatic)

    def reapply_overrides(self, result: PipelineResult, overrides: tuple[Override, ...]) -> list[str]:
        """Re-decides from the automatic baseline with a new set of overrides, without re-scoring."""
        mappings = [_copy(m) for m in result.automatic]
        scope = frozenset(result.run.scope) or None
        active, warnings = _active_overrides(overrides, scope)
        warnings.extend(apply_overrides(mappings, active, result.prepared.score_pair))
        result.run.mappings = mappings
        plans = CallPlanner(self.lexicon, result.run.upstream, result.run.downstreams, result.sources).plan(mappings)
        result.run.call_plans = [plan for plan in plans if _in_scope(plan.upstream_endpoint, scope)]
        return warnings

    @contextmanager
    def _stage(self, name: str, message: str) -> Iterator[dict[str, int]]:
        started = perf_counter()
        counts: dict[str, int] = {}
        self._emit(ProgressEvent(name, StageState.STARTED, message))
        try:
            yield counts
        except Exception as error:
            self._emit(ProgressEvent(name, StageState.FAILED, str(error), counts, _ms(started)))
            raise
        self._emit(ProgressEvent(name, StageState.FINISHED, message, counts, _ms(started)))

    def _emit(self, event: ProgressEvent) -> None:
        self._events.append(event)
        if self._listener:
            self._listener(event)


_GENERIC_STEMS = frozenset({"openapi", "swagger", "spec", "api", "manifest", "index"})


def _copy(mapping: FieldMapping) -> FieldMapping:
    return FieldMapping(
        mapping.target, mapping.status, mapping.chosen, mapping.alternatives, list(mapping.notes), mapping.category
    )


def _api_name(path: Path) -> str | None:
    """Names an API after its file, or its folder when the file is just `openapi.yaml`.

    Returns None for generated upload folders, so the spec's own title names it instead.
    """
    if path.stem.lower() not in _GENERIC_STEMS:
        return path.stem
    if re.fullmatch(r"[0-9a-f]{12}", path.parent.name):
        return None
    return path.parent.name


def _scope(selected: tuple[str, ...], upstream: ApiSpec, warnings: list[str]) -> frozenset[str] | None:
    """None maps every endpoint; a selection that names no real endpoint maps nothing."""
    if not selected:
        return None
    known = {endpoint.key for endpoint in upstream.endpoints}
    warnings.extend(f"selected endpoint {key} is not in the upstream spec" for key in selected if key not in known)
    return frozenset(key for key in selected if key in known)


def _in_scope(endpoint: str, scope: frozenset[str] | None) -> bool:
    return scope is None or endpoint in scope


def _active_overrides(
    overrides: tuple[Override, ...], scope: frozenset[str] | None
) -> tuple[tuple[Override, ...], list[str]]:
    """Saved decisions for endpoints outside the selection are kept for later runs, not applied."""
    active = tuple(o for o in overrides if _in_scope(_endpoint_of(o.target_key), scope))
    kept = len(overrides) - len(active)
    note = [f"{kept} saved decisions belong to endpoints outside the selection; kept, not applied"] if kept else []
    return active, note


def _endpoint_of(target_key: str) -> str:
    parts = target_key.split("|")
    return parts[1] if len(parts) == 3 else ""


def _ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 1)


def _unique_names(specs: list[ApiSpec]) -> list[ApiSpec]:
    """Two downstreams with the same name would make field keys collide; suffix the later ones."""
    seen: dict[str, int] = {}
    unique = []
    for spec in specs:
        count = seen.get(spec.name, 0)
        seen[spec.name] = count + 1
        if count:
            spec = replace(spec, name=f"{spec.name}-{count + 1}")
        unique.append(spec)
    return unique
