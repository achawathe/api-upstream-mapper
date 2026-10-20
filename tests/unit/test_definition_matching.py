"""Regressions for lost definitions, record ownership and misleading field names."""

from api_mapper.matching.engine import MatchingEngine
from api_mapper.models import ApiSpec, Endpoint, MappingStatus, SpecKind
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.normalize.profiler import Profiler


def match(lexicon, target_properties, source_properties):
    up = ApiSpec(
        "up",
        "up",
        "1",
        SpecKind.OPENAPI_3,
        "up",
        endpoints=(
            Endpoint("GET", "/accounts", "up", response_schema={"type": "object", "properties": target_properties}),
        ),
    )
    down = ApiSpec(
        "down",
        "down",
        "1",
        SpecKind.OPENAPI_3,
        "down",
        endpoints=(
            Endpoint("GET", "/accounts", "down", response_schema={"type": "object", "properties": source_properties}),
        ),
    )
    profiler = Profiler(lexicon)
    targets = profiler.profile_spec(up, flatten_spec(up))
    sources = profiler.profile_spec(down, flatten_spec(down))
    return MatchingEngine(lexicon).match(targets, sources)


def records(properties):
    return {"type": "array", "items": {"type": "object", "properties": properties}}


def test_scalar_array_keeps_the_property_definition():
    schema = {
        "type": "array",
        "description": "API products enabled for the Item.",
        "items": {"type": "string", "description": "A supported product.", "enum": ["auth", "identity"]},
    }
    spec = ApiSpec(
        "down",
        "down",
        "1",
        SpecKind.OPENAPI_3,
        "down",
        endpoints=(Endpoint("GET", "/x", "x", response_schema={"type": "object", "properties": {"products": schema}}),),
    )
    node = flatten_spec(spec)[0]
    assert node.description == "API products enabled for the Item."
    assert node.enum == ("auth", "identity")
    assert node.path == "products[]"


def test_account_currency_prefers_account_record_over_transaction_record(lexicon):
    field = {"type": "string", "description": "ISO currency code"}
    mapping = match(
        lexicon,
        {"currency": field},
        {
            "transactions": records({"currency": field}),
            "accounts": records({"currency": field}),
        },
    )[0]
    assert mapping.chosen.source.path == "accounts[].currency"
    wrong = next(c for c in mapping.alternatives if c.source.path == "transactions[].currency")
    assert any(e.signal == "collection" for e in wrong.evidence)


def test_definitions_retrieve_names_without_equating_nickname_and_official_name(lexicon):
    mappings = match(
        lexicon,
        {
            "productName": {"type": "string", "description": "Marketed product name for this account."},
            "nickname": {"type": "string", "description": "Account nickname"},
        },
        {
            "accounts": records(
                {
                    "z9": {
                        "type": "string",
                        "description": "The official name of the account as given by the financial institution",
                    },
                    "x2": {
                        "type": "string",
                        "description": (
                            "The name of the account, either assigned by the user "
                            "or by the financial institution itself"
                        ),
                    },
                }
            )
        },
    )
    assert [m.chosen.source.path if m.chosen else None for m in mappings] == ["accounts[].z9", "accounts[].x2"]
    assert all(m.status is MappingStatus.REVIEW for m in mappings)


def test_purpose_support_does_not_override_record_ownership(lexicon):
    definition = {
        "type": "string",
        "description": "The official name of the account as given by the financial institution",
    }
    mapping = match(
        lexicon,
        {"productName": {"type": "string", "description": "Marketed product name for this account."}},
        {"transactions": records({"caption": definition})},
    )[0]
    assert mapping.chosen is None


def test_product_identifier_cannot_be_supplied_by_a_product_label(lexicon):
    mapping = match(
        lexicon,
        {"productId": {"type": "string", "description": "Unique ID of the marketed product for this account"}},
        {
            "accounts": records(
                {"productId": {"type": "string", "description": "Marketed product name for this account."}}
            )
        },
    )[0]
    assert mapping.chosen is None
