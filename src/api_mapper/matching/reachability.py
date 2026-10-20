"""Which downstream endpoints can be called for the record an upstream request names.

`GET /accounts/{accountId}/contact` is about one account, so a source must be callable
for that account: with the request's own inputs, or with ids returned by calls that are
themselves reachable (holders -> partyId -> party). A list of every address change in
the bank, or a fee schedule whose id nothing supplies, is not a source for one account.
JSON body selectors establish conditional reachability; caller context and identifier
compatibility still need review, including calls reached through those selectors.
Upstream endpoints without inputs (`GET /accounts`) are not limited.
"""

from api_mapper.models import ApiSpec, FieldProfile
from api_mapper.normalize.inputs import bindable_body, input_name
from api_mapper.normalize.lexicon import Lexicon

EndpointKey = tuple[str, str]
Identity = frozenset[str]


class Reachability:
    def __init__(
        self, specs: tuple[ApiSpec, ...], sources: list[FieldProfile], param_identity, lexicon: Lexicon | None = None
    ):
        self._params: dict[EndpointKey, list[tuple[Identity, bool]]] = {}
        self._body: dict[EndpointKey, set[Identity]] = {}
        self._has_body: set[EndpointKey] = set()
        for spec in specs:
            for endpoint in spec.endpoints:
                key = (spec.name, endpoint.key)
                body = [p for p in endpoint.parameters if p.location == "body"]
                if body:
                    self._has_body.add(key)
                self._body[key] = {
                    param_identity(input_name(p, lexicon) if lexicon else p.name, endpoint.path)
                    for p in body
                    if bindable_body(p)
                }
                self._params[key] = [
                    (param_identity(p.name, endpoint.path), p.location == "path" or p.required)
                    for p in endpoint.parameters
                    if p.location in ("path", "query")
                ]
        self._outputs: dict[EndpointKey, set[Identity]] = {}
        for source in sources:
            self._outputs.setdefault((source.node.api, source.node.endpoint), set()).add(source.identity)
        self._cache: dict[frozenset[Identity], frozenset[EndpointKey]] = {}
        self._without_body: dict[frozenset[Identity], frozenset[EndpointKey]] = {}

    def reachable(self, inputs: frozenset[Identity], endpoint: EndpointKey) -> bool:
        if not inputs:
            return True
        if inputs not in self._cache:
            self._cache[inputs] = self._scoped(inputs)
        return endpoint in self._cache[inputs]

    def selectable(self, inputs: frozenset[Identity], endpoint: EndpointKey) -> bool:
        """A map keyed by data returns every record, and the request's input picks the entry; it only
        needs its own required inputs, from the request or from reachable calls."""
        if self.reachable(inputs, endpoint):
            return True
        if inputs not in self._cache:
            self._cache[inputs] = self._scoped(inputs)
        known = set(inputs).union(*(self._outputs.get(key, set()) for key in self._cache[inputs]))
        return all(identity in known for identity, required in self._params.get(endpoint, []) if required)

    def requires_body_review(self, endpoint: EndpointKey, inputs: frozenset[Identity] = frozenset()) -> bool:
        if endpoint in self._has_body:
            return True
        if not inputs or not self.reachable(inputs, endpoint):
            return False
        if inputs not in self._without_body:
            self._without_body[inputs] = self._scoped(inputs, allow_body=False)
        return endpoint not in self._without_body[inputs]

    def _scoped(self, inputs: frozenset[Identity], allow_body: bool = True) -> frozenset[EndpointKey]:
        available = set(inputs)
        scoped: set[EndpointKey] = set()
        changed = True
        while changed:
            changed = False
            for key, params in self._params.items():
                if key in scoped or (not allow_body and key in self._has_body):
                    continue
                required_known = all(identity in available for identity, required in params if required)
                ties_to_record = any(identity in available for identity, _ in params) or bool(
                    self._body[key] & available
                )
                if required_known and ties_to_record:
                    scoped.add(key)
                    available |= self._outputs.get(key, set())
                    changed = True
        return frozenset(scoped)
