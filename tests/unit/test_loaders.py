from pathlib import Path

import pytest

from api_mapper.loaders import SpecLoadError, build_api_spec, infer_schema, load_any, parse_document
from api_mapper.loaders.ref_resolver import CYCLE_KEY, SCHEMA_NAME_KEY, UNRESOLVED_KEY
from api_mapper.models import SpecKind
from tests.conftest import FIXTURES, SAMPLES


class TestParseDocument:
    def test_yes_no_and_dates_stay_strings(self):
        parsed = parse_document("flag: no\nwhen: 2024-01-31\nenum: [Y, N, on, off]\nreal: true", "t")
        assert parsed == {"flag": "no", "when": "2024-01-31", "enum": ["Y", "N", "on", "off"], "real": True}

    def test_yaml_flow_mapping_is_not_mistaken_for_json(self):
        assert parse_document("{a: 1, b: two}", "t") == {"a": 1, "b": "two"}

    def test_empty_file_is_reported(self):
        with pytest.raises(SpecLoadError, match="empty"):
            parse_document("   \n", "t")

    def test_broken_yaml_is_reported(self):
        with pytest.raises(SpecLoadError, match="not valid"):
            parse_document("a: [unclosed", "t")


class TestRefResolution:
    def test_cycles_missing_refs_and_external_files(self):
        spec = load_any(FIXTURES / "cyclic.yaml")
        node = spec.endpoint("GET /nodes").response_schema
        assert node[SCHEMA_NAME_KEY] == "Node"
        assert node["properties"]["parent"] == {CYCLE_KEY: "Node"}
        assert UNRESOLVED_KEY in node["properties"]["missing"]
        assert node["properties"]["shared"]["description"] == "Shared amount from another file."
        assert any("DoesNotExist" in warning for warning in spec.warnings)


class TestSpecKinds:
    def test_swagger_2_path_level_parameters_and_examples(self):
        spec = load_any(SAMPLES / "downstream/deposits/swagger.json", "deposits")
        endpoint = spec.endpoint("GET /deposits/{debitAccountId}/balances")
        assert spec.kind is SpecKind.SWAGGER_2
        assert [p.name for p in endpoint.path_parameters] == ["debitAccountId"]
        assert endpoint.response_examples[0]["debitAccount"]["id"] == "ACC-000123"
        assert {e.status for e in endpoint.error_responses} == {"403", "404", "409", "503"}

    def test_external_ref_error_responses(self):
        spec = load_any(SAMPLES / "downstream/core-accounts/openapi.yaml", "core-accounts")
        errors = spec.endpoint("GET /v2/accounts/{accountId}").error_responses
        not_found = next(e for e in errors if e.status == "404")
        assert not_found.examples[0]["code"] == "ACCT_NOT_FOUND"

    def test_schema_fragment_becomes_pseudo_endpoints(self):
        document = {
            "components": {"schemas": {"Account": {"type": "object", "properties": {"id": {"type": "string"}}}}}
        }
        spec = build_api_spec(document, source="mem", base_dir=Path("."), name="frag")
        assert spec.kind is SpecKind.FRAGMENT
        assert spec.endpoints[0].key == "SCHEMA /Account"

    def test_unrecognised_document_is_rejected(self):
        with pytest.raises(SpecLoadError):
            build_api_spec({"hello": "world"}, source="mem", base_dir=Path("."), name="x")

    def test_sample_manifest_infers_schema(self):
        spec = load_any(SAMPLES / "downstream/routing/manifest.yaml")
        endpoint = spec.endpoint("GET /payments/routing/{acctNum}")
        assert spec.kind is SpecKind.SAMPLES
        assert endpoint.response_schema["properties"]["routing"]["properties"]["wire"]["nullable"] is True
        assert [p.name for p in endpoint.path_parameters] == ["acctNum"]


class TestSampleInference:
    def test_optional_nullable_and_mixed_numbers(self):
        schema = infer_schema([{"a": 1, "b": None}, {"a": 2.5}])
        assert schema["required"] == ["a"]
        assert schema["properties"]["a"]["type"] == "number"
        assert schema["properties"]["b"]["nullable"] is True

    def test_formats_and_arrays(self):
        schema = infer_schema([{"when": "2024-01-31T10:00:00Z", "tags": ["x", "y"]}])
        assert schema["properties"]["when"]["format"] == "date-time"
        assert schema["properties"]["tags"]["items"]["type"] == "string"

    def test_mixed_scalar_types_fall_back_to_string(self):
        schema = infer_schema(["7", 7])
        assert schema["type"] == "string"
        assert schema["x-mixed-types"] == ["integer", "string"]
