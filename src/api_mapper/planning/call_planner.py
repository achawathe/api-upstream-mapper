"""Works out which downstream calls each upstream endpoint needs, in what order.

Every path parameter of a downstream call must come from somewhere: the upstream
request (`accountId`), or a field returned by an earlier call (`acctNum` from the core
account record). When an earlier call returns that field inside an array, the later
call runs once per item (fan-out). Calls that only exist to supply such inputs are
added automatically. Optional query parameters are bound when the upstream request
has a clear counterpart (`from` <- `startDate`). JSON body scalars and scalar arrays
bind only to an exact compatible request input; credentials remain caller context.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from api_mapper.models import (
    ApiSpec,
    BindingSource,
    CallStep,
    Endpoint,
    EndpointCallPlan,
    FieldMapping,
    FieldNode,
    FieldProfile,
    InputBinding,
    MappingStatus,
    Parameter,
)
from api_mapper.models.field_node import MAP_KEY_SEGMENT
from api_mapper.normalize import value_kinds
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.normalize.inputs import bindable_body, compatible_body_input, input_name
from api_mapper.normalize.lexicon import ENTITY_CONCEPT, Lexicon

EXACT = 0.99
MAP_KEY_LOCATION = "map key"
QUERY_MATCH = 0.75
MAX_SUPPLIER_DEPTH = 2
_PLANNED_STATUSES = (MappingStatus.AUTO, MappingStatus.REVIEW, MappingStatus.MANUAL)

EndpointKey = tuple[str, str]


@dataclass(frozen=True)
class _Supply:
    score: float
    source: BindingSource
    reference: str
    fanout: bool = False
    supplier: EndpointKey | None = None
    neutral: bool = True
    specific: bool = True


class CallPlanner:
    def __init__(
        self, lexicon: Lexicon, upstream: ApiSpec, downstreams: Iterable[ApiSpec], profiles: list[FieldProfile]
    ):
        self.lexicon = lexicon
        self.upstream = upstream
        self.endpoints: dict[EndpointKey, Endpoint] = {
            (spec.name, e.key): e for spec in downstreams for e in spec.endpoints
        }
        self.fields: dict[EndpointKey, list[FieldProfile]] = {}
        for profile in profiles:
            self.fields.setdefault((profile.node.api, profile.node.endpoint), []).append(profile)
        self.echoes: dict[str, dict[str, FieldNode]] = {}
        for node in flatten_spec(upstream):
            if not node.parent_segments:
                self.echoes.setdefault(node.endpoint, {})[node.path] = node

    def plan(self, mappings: list[FieldMapping]) -> list[EndpointCallPlan]:
        by_endpoint: dict[str, list[FieldMapping]] = {}
        for mapping in mappings:
            if mapping.chosen and mapping.status in _PLANNED_STATUSES:
                by_endpoint.setdefault(mapping.target.endpoint, []).append(mapping)
        return [
            _EndpointPlanner(self, endpoint, by_endpoint.get(endpoint.key, [])).build()
            for endpoint in self.upstream.endpoints
        ]

    def param_concepts(self, name: str, path: str) -> frozenset[str]:
        concepts = list(self.lexicon.concepts(name))
        if self.lexicon.is_generic(concepts):
            segments = path.split("/")
            position = next((i for i, s in enumerate(segments) if s == f"{{{name}}}"), len(segments))
            resource = next((s for s in reversed(segments[:position]) if s and not s.startswith("{")), "")
            concepts = [*self.lexicon.concepts(resource), *concepts]
        return self.without_qualifiers(concepts)

    def field_concepts(self, field: FieldProfile) -> frozenset[str]:
        if field.leaf_is_generic:
            return self.without_qualifiers(c for c, share in field.bag.items() if share >= 1.0)
        return self.without_qualifiers(field.leaf)

    def without_qualifiers(self, concepts: Iterable[str]) -> frozenset[str]:
        """`debitAccountId`, `loan_id` and `accountId` all name the account."""
        return frozenset(ENTITY_CONCEPT if c in self.lexicon.families else c for c in concepts)

    def overlap(self, wanted: frozenset[str], offered: frozenset[str]) -> float:
        if not wanted or not offered:
            return 0.0
        if wanted == offered:
            return 1.0
        matched = sum(max((self.lexicon.relatedness(x, y) for y in offered), default=0.0) for x in wanted)
        return matched / max(len(wanted), len(offered))

    def directional_overlap(self, wanted: frozenset[str], offered: frozenset[str]) -> float:
        if not wanted:
            return 0.0
        return sum(max((self.lexicon.relatedness(x, y) for y in offered), default=0.0) for x in wanted) / len(wanted)


class _EndpointPlanner:
    def __init__(self, planner: CallPlanner, upstream_endpoint: Endpoint, mappings: list[FieldMapping]):
        self.p = planner
        self.upstream_endpoint = upstream_endpoint
        self.upstream_params = {
            param.name: (param, planner.param_concepts(param.name, upstream_endpoint.path))
            for param in upstream_endpoint.parameters
            if not param.context_only
        }
        self.variants: dict[EndpointKey, set[str]] = {}
        self.field_counts: dict[EndpointKey, int] = {}
        self.pending_counts: dict[EndpointKey, int] = {}
        self.maps: dict[EndpointKey, set[str]] = {}
        for mapping in mappings:
            key = (mapping.chosen.source.api, mapping.chosen.source.endpoint)
            if mapping.chosen.source.map_path is not None:
                self.maps.setdefault(key, set()).add(mapping.chosen.source.map_path)
            self.variants.setdefault(key, set()).add(mapping.target.variant or "")
            self.field_counts[key] = self.field_counts.get(key, 0) + 1
            if mapping.status is MappingStatus.REVIEW:
                self.pending_counts[key] = self.pending_counts.get(key, 0) + 1
        self.ordered: list[EndpointKey] = []
        self.bindings: dict[EndpointKey, tuple[InputBinding, ...]] = {}
        self.in_progress: set[EndpointKey] = set()
        self.suppliers: set[EndpointKey] = set()
        self.unresolved: list[str] = []

    def build(self) -> EndpointCallPlan:
        for key in sorted(self.variants):
            self._schedule(key, depth=0)
        steps = tuple(
            CallStep(
                order=index + 1,
                api=key[0],
                endpoint=key[1],
                bindings=self.bindings[key],
                variants=tuple(sorted(v for v in self.variants.get(key, ()) if v)),
                supplies_fields=self.field_counts.get(key, 0),
                pending_review_fields=self.pending_counts.get(key, 0),
                supplies_only_inputs=key not in self.variants,
            )
            for index, key in enumerate(self.ordered)
        )
        return EndpointCallPlan(self.upstream_endpoint.key, steps, tuple(self.unresolved))

    def _schedule(self, key: EndpointKey, depth: int) -> None:
        if key in self.bindings or key in self.in_progress:
            return
        self.in_progress.add(key)
        endpoint = self.p.endpoints[key]
        bindings = [self._bind_path(key, endpoint, parameter, depth) for parameter in endpoint.path_parameters]
        bindings.extend(
            b for b in (self._bind_query(endpoint, q) for q in endpoint.parameters if q.location == "query") if b
        )
        bindings.extend(
            b for b in (self._bind_body(endpoint, p) for p in endpoint.parameters if p.location == "body") if b
        )
        bindings.extend(self._bind_map_key(key, map_path) for map_path in sorted(self.maps.get(key, ())))
        self.in_progress.discard(key)
        self.bindings[key] = tuple(bindings)
        self.ordered.append(key)

    def _bind_map_key(self, key: EndpointKey, map_path: str) -> InputBinding:
        """A map keyed by data needs the entry chosen: by a request input that names the same thing, or by a person."""
        field = next((f for f in self.p.fields.get(key, []) if f.node.path == f"{map_path}.{MAP_KEY_SEGMENT}"), None)
        wanted = self.p.field_concepts(field) if field else frozenset()
        for name, (_, concepts) in self.upstream_params.items():
            if self.p.overlap(wanted, concepts) >= EXACT:
                return InputBinding(map_path, BindingSource.UPSTREAM_REQUEST, name, location=MAP_KEY_LOCATION)
        # Keys hold the same specific kind of data as the response field that echoes an input (currency codes).
        keys = value_kinds.observed_kind(field.node) if field else None
        echoes = self.p.echoes.get(self.upstream_endpoint.key, {})
        matching = [
            name
            for name in self.upstream_params
            if name in echoes and keys and value_kinds.agreement(value_kinds.expected_kind(echoes[name]), keys[0])
        ]
        if len(matching) == 1:
            return InputBinding(map_path, BindingSource.UPSTREAM_REQUEST, matching[0], location=MAP_KEY_LOCATION)
        self.unresolved.append(f"{key[0]} {key[1]}: entry of {map_path}")
        return InputBinding(
            map_path, BindingSource.UNRESOLVED, "choose which entry this request needs", location=MAP_KEY_LOCATION
        )

    def _bind_path(self, key: EndpointKey, endpoint: Endpoint, parameter: Parameter, depth: int) -> InputBinding:
        supply = self._best_supply(key, self.p.param_concepts(parameter.name, endpoint.path), depth)
        if supply is None:
            self.unresolved.append(f"{key[0]} {key[1]}: {parameter.name}")
            return InputBinding(
                parameter.name, BindingSource.UNRESOLVED, "supply from caller context, e.g. the token subject"
            )
        if supply.supplier is not None:
            self.suppliers.add(supply.supplier)
            self._schedule(supply.supplier, depth + 1)
        step = self.ordered.index(supply.supplier) + 1 if supply.supplier in self.ordered else None
        return InputBinding(parameter.name, supply.source, supply.reference, supply.fanout, step)

    def _bind_query(self, endpoint: Endpoint, parameter: Parameter) -> InputBinding | None:
        wanted = self.p.param_concepts(parameter.name, endpoint.path)
        scored = []
        for name, (upstream_param, concepts) in self.upstream_params.items():
            score = self.p.directional_overlap(wanted, concepts)
            same_format = upstream_param.schema.get("format") == parameter.schema.get("format")
            scored.append((score, same_format, name))
        best = max(scored, default=None)
        if best and best[0] >= QUERY_MATCH:
            return InputBinding(parameter.name, BindingSource.UPSTREAM_REQUEST, best[2], location="query")
        if parameter.required:
            self.unresolved.append(f"{endpoint.key}: query {parameter.name}")
            return InputBinding(
                parameter.name,
                BindingSource.UNRESOLVED,
                "required query parameter with no upstream source",
                location="query",
            )
        return None

    def _bind_body(self, endpoint: Endpoint, parameter: Parameter) -> InputBinding | None:
        wanted = self.p.param_concepts(input_name(parameter, self.p.lexicon), endpoint.path)
        if bindable_body(parameter):
            matches = sorted(
                name
                for name, (upstream, concepts) in self.upstream_params.items()
                if wanted
                and wanted == concepts
                and not upstream.context_only
                and compatible_body_input(upstream.schema, parameter.schema)
            )
            if len(matches) == 1:
                return InputBinding(parameter.name, BindingSource.UPSTREAM_REQUEST, matches[0], location="body")
        if parameter.required or parameter.context_only:
            if parameter.required:
                self.unresolved.append(f"{endpoint.key}: body {parameter.name}")
            requirement = "required" if parameter.required else "optional"
            return InputBinding(
                parameter.name,
                BindingSource.UNRESOLVED,
                f"{requirement} JSON body input supplied by caller context",
                location="body",
            )
        return None

    def _best_supply(self, requester: EndpointKey, wanted: frozenset[str], depth: int) -> _Supply | None:
        options = [
            _Supply(self.p.overlap(wanted, concepts), BindingSource.UPSTREAM_REQUEST, name)
            for name, (_, concepts) in self.upstream_params.items()
        ]
        if max((o.score for o in options), default=0.0) < EXACT:
            options.extend(self._field_supplies(requester, wanted, depth))
        # Sharing `identifier` does not make an account ID a customer ID.
        viable = sorted((o for o in options if o.score >= EXACT), key=lambda o: o.reference)
        if not viable:
            return None
        return max(viable, key=self._preference)

    def _field_supplies(self, requester: EndpointKey, wanted: frozenset[str], depth: int) -> list[_Supply]:
        supplies = []
        for key, fields in self.p.fields.items():
            already_called = key in self.ordered
            if key == requester or key in self.in_progress:
                continue
            if not already_called and (depth >= MAX_SUPPLIER_DEPTH or not self._callable(key)):
                continue
            for field in fields:
                if self.p.overlap(wanted, self.p.field_concepts(field)) >= EXACT:
                    supplies.append(
                        _Supply(
                            score=1.0,
                            source=BindingSource.PRIOR_STEP,
                            reference=f"{key[0]} {key[1]} -> {field.node.path}",
                            fanout=field.node.array_depth > 0,
                            supplier=key,
                            neutral=not field.families,
                            specific=bool(self.p.endpoints[key].path_parameters),
                        )
                    )
        return supplies

    def _callable(self, key: EndpointKey) -> bool:
        endpoint = self.p.endpoints[key]
        return all(
            any(
                self.p.overlap(self.p.param_concepts(param.name, endpoint.path), concepts) >= EXACT
                for _, concepts in self.upstream_params.values()
            )
            for param in endpoint.path_parameters
        )

    def _preference(self, supply: _Supply) -> tuple:
        """The request over extra calls, single records over lists, calls already
        planned, then sources valid for every account type. Ties keep alphabetical order."""
        already_called = supply.supplier in self.ordered if supply.supplier else True
        return (
            supply.score,
            supply.source is BindingSource.UPSTREAM_REQUEST,
            not supply.fanout,
            supply.specific,
            already_called,
            supply.neutral,
        )
