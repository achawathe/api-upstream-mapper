"""Context gives meaning where names cannot: guessed parent names, and values named only by their keys."""

from api_mapper.loaders.sample_loader import api_from_payloads
from api_mapper.matching.assigner import assign
from api_mapper.matching.context_fallback import suggest_from_context
from api_mapper.matching.engine import MatchingEngine
from api_mapper.models import ApiSpec, Endpoint, MappingStatus, Parameter, Signal, SpecKind
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.normalize.profiler import Profiler


def upstream(path, properties, parameters=()):
    schema = {"type": "object", "properties": properties}
    return ApiSpec(
        "up",
        "up",
        "1",
        SpecKind.OPENAPI_3,
        "up",
        endpoints=(Endpoint("GET", path, "op", parameters=parameters, response_schema=schema),),
    )


def run(lexicon, target, payloads_by_endpoint, title=""):
    source = api_from_payloads("down", payloads_by_endpoint, title)
    profiler = Profiler(lexicon)
    targets = profiler.profile_spec(target, flatten_spec(target))
    sources = profiler.profile_spec(source, flatten_spec(source))
    prepared = MatchingEngine(lexicon).prepare(targets, sources)
    mappings = assign(targets, prepared.score_all())
    suggest_from_context(mappings, prepared, lexicon)
    return {m.target.path: m for m in mappings}


def test_a_guessed_array_name_agrees_through_any_of_its_words(lexicon):
    target = upstream(
        "/accounts/{accountId}/contact",
        {"addresses": {"type": "array", "items": {"type": "object", "properties": {"city": {"type": "string"}}}}},
    )
    found = run(lexicon, target, {"GET /parties/{partyId}": [{"addrsssPstl": [{"city": "Ottawa"}]}]})
    chosen = found["addresses[].city"].chosen
    assert chosen.source.path == "addrsssPstl[].city"
    assert not any(e.signal is Signal.COLLECTION for e in chosen.evidence)


def test_a_clearly_named_array_keeps_its_head_noun(lexicon):
    target = upstream(
        "/accounts/{accountId}/transactions",
        {"transactions": {"type": "array", "items": {"type": "object", "properties": {"amount": {"type": "number"}}}}},
    )
    found = run(lexicon, target, {"GET /accounts/{accountId}/networks": [{"assetTransferNetworks": [{"amount": 1.5}]}]})
    mapping = found["transactions[].amount"]
    candidate = mapping.chosen or next(iter(mapping.alternatives), None)
    assert candidate is None or any(e.signal is Signal.COLLECTION for e in candidate.evidence)


WEATHER = {"temperature": {"type": "number", "description": "Current air temperature in degrees Celsius."}}
CITY = (Parameter("city", "path", True, {"type": "string"}),)


def test_a_value_named_only_by_its_keys_is_suggested_from_shared_context(lexicon):
    payloads = [
        {"weather": {"city": {"toronto": 12.5, "ottawa": 8.4, "calgary": 4.2}}, "station": "TS-1"},
        {"weather": {"city": {"toronto": 13.1, "regina": 2.0, "halifax": 9.9}}, "station": "TS-1"},
    ]
    found = run(lexicon, upstream("/cities/{city}/weather", WEATHER, CITY), {"GET /weather/snapshot": payloads})
    mapping = found["temperature"]
    assert mapping.status is MappingStatus.REVIEW
    assert mapping.chosen.source.path == "weather.city.{key}"
    assert any("shared weather context" in note for note in mapping.notes)


def test_no_suggestion_when_another_number_could_be_it(lexicon):
    payloads = [
        {"weather": {"city": {"toronto": 12.5, "ottawa": 8.4, "calgary": 4.2}}, "humidity": 71},
        {"weather": {"city": {"toronto": 13.1, "regina": 2.0, "halifax": 9.9}}, "humidity": 64},
    ]
    found = run(lexicon, upstream("/cities/{city}/weather", WEATHER, CITY), {"GET /weather/snapshot": payloads})
    assert found["temperature"].status is MappingStatus.UNMAPPED
