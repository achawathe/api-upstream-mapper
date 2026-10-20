"""Optional documents are scoped to their API/endpoint and retain cited source text."""

import io
import json
from dataclasses import replace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from api_mapper.api.workspace import FileRole, Workspace
from api_mapper.loaders.documentation import read_documentation
from api_mapper.models import ApiSpec, Endpoint, FieldNode, SpecKind
from api_mapper.models.purpose import ContextClue
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.transforms.inference import TypeFitter


def spec():
    return ApiSpec(
        "weather",
        "Weather",
        "1",
        SpecKind.OPENAPI_3,
        "test",
        endpoints=tuple(
            Endpoint(
                "GET",
                path,
                path,
                response_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}, "code": {"type": "string"}},
                },
            )
            for path in ("/weather", "/stations")
        ),
    )


def test_document_sections_do_not_leak_between_endpoints():
    api = replace(
        spec(),
        documentation=read_documentation(
            "guide.md", b"GET /weather\nvalue: Air temperature.\nGET /stations\nvalue: Station identifier."
        ),
    )
    fields = flatten_spec(api)
    assert [n.documentation[0].text for n in fields if n.name == "value"] == ["Air temperature.", "Station identifier."]
    assert all(not n.documentation for n in fields if n.name == "code")
    assert all(n.type == "string" and n.description == "" for n in fields)


def test_ambiguous_names_without_endpoint_are_not_assigned():
    api = replace(spec(), documentation=read_documentation("guide.txt", b"value: Air temperature."))
    assert all(not n.documentation for n in flatten_spec(api))


def test_explicit_scope_and_unknown_endpoint_sections():
    api = replace(spec(), documentation=read_documentation("guide.txt", b"value: Air temperature.", "GET /weather"))
    assert sum(bool(n.documentation) for n in flatten_spec(api)) == 1
    api = replace(spec(), documentation=read_documentation("guide.txt", b"GET /absent\nvalue: Air temperature."))
    assert all(not n.documentation for n in flatten_spec(api))


def test_docx_keeps_paragraph_citations():
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>reading: Temperature in Celsius.</w:t></w:r></w:p></w:body></w:document>',
        )
    passages = read_documentation("manual.docx", stream.getvalue())
    assert passages[0].text == "reading: Temperature in Celsius."
    assert "paragraph 1" in passages[0].location


def test_pdf_extracts_text_with_page_citation():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(500, 500)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    text = DecodedStreamObject()
    text.set_data(b"BT /F1 12 Tf 20 400 Td (reading: Temperature in Celsius.) Tj ET")
    page[NameObject("/Contents")] = text
    stream = io.BytesIO()
    writer.write(stream)
    passages = read_documentation("manual.pdf", stream.getvalue())
    assert "Temperature" in passages[0].text
    assert "page 1" in passages[0].location


@pytest.mark.parametrize(
    ("name", "data"), [("bad.docx", b"bad"), ("bad.txt", b"\xff"), ("bad.exe", b"abc"), ("empty.md", b"   ")]
)
def test_invalid_documents_fail_clearly(name, data):
    with pytest.raises(ValueError):
        read_documentation(name, data)


def test_documented_numeric_strings_allow_reviewed_conversion(lexicon):
    target = FieldNode("up", "GET /stock", "quantity", "integer")
    source = FieldNode(
        "down",
        "GET /stock",
        "q9",
        "string",
        documentation=(ContextClue("An integer encoded as a string.", "guide.txt"),),
    )
    fit = TypeFitter(lexicon).fit(target, source, False)
    assert fit.score == 0.85
    assert fit.steps[0].params == {"to": "integer"}
    assert source.type == "string"


def test_documentation_api_persists_and_removes_attachments(tmp_path, monkeypatch):
    from api_mapper.api import app as app_module

    workspace = Workspace(tmp_path)
    document = {"openapi": "3.0.3", "info": {"title": "Weather", "version": "1"}, "paths": {}}
    stored = workspace.add_file(FileRole.UPSTREAM, "weather.json", json.dumps(document).encode())
    monkeypatch.setattr(app_module, "workspace", workspace)
    with TestClient(app_module.app) as client:
        response = client.post(
            f"/api/files/{stored.id}/documentation", files=[("files", ("guide.txt", b"Weather guide"))]
        )
        assert response.status_code == 200
        identifier = response.json()["document"]["id"]
        assert len(Workspace(tmp_path).documents) == 1
        assert (
            client.post(f"/api/files/{stored.id}/documentation", files=[("files", ("bad.exe", b"bad"))]).status_code
            == 400
        )
        assert len(workspace.documents) == 1
        assert client.delete(f"/api/documentation/{identifier}").status_code == 200
        assert Workspace(tmp_path).documents == []
    assert "Weather guide" not in workspace.activity.path.read_text()
