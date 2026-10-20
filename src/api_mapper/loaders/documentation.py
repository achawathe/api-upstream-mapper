"""Extract local text with page/paragraph provenance; scanned PDFs require supplied text."""

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from api_mapper.models.documentation import DocumentationPassage

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARACTERS = 500_000


def read_documentation(name: str, content: bytes, endpoint: str = "") -> tuple[DocumentationPassage, ...]:
    name = Path(name).name
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Documentation files must be nonempty and at most 10 MB")
    suffix = Path(name).suffix.lower()
    try:
        if suffix == ".pdf":
            sections = _pdf(content)
        elif suffix == ".docx":
            sections = _docx(content)
        elif suffix in {".txt", ".md", ".markdown"}:
            sections = [("text", content.decode("utf-8-sig"))]
        else:
            raise ValueError("Use PDF, DOCX, TXT or Markdown documentation")
        if sum(len(text) for _, text in sections) > MAX_TEXT_CHARACTERS:
            raise ValueError("Extracted documentation exceeds 500,000 characters; split the document")
        passages = tuple(
            DocumentationPassage(text.strip(), f"{name} · {location}", endpoint)
            for location, text in sections
            if text.strip()
        )
        if not passages:
            raise ValueError(
                "No readable text found; paste the text or supply a text-based document (scanned PDFs need OCR)"
            )
        return passages
    except (UnicodeError, BadZipFile, ElementTree.ParseError, KeyError) as error:
        raise ValueError(f"Could not read {name}; check its format and encoding") from error


def _pdf(content: bytes) -> list[tuple[str, str]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("Use an unencrypted PDF")
        if len(reader.pages) > 200:
            raise ValueError("PDF documentation is limited to 200 pages per file")
        return [(f"page {index + 1}", page.extract_text() or "") for index, page in enumerate(reader.pages)]
    except PdfReadError as error:
        raise ValueError("Could not read this PDF") from error


def _docx(content: bytes) -> list[tuple[str, str]]:
    with ZipFile(BytesIO(content)) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > MAX_FILE_BYTES:
            raise ValueError("DOCX document text is too large")
        root = ElementTree.fromstring(archive.read(info))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return [
        (
            f"paragraph {index + 1}",
            "".join(p.itertext()) if not list(p) else "".join(t.text or "" for t in p.findall(".//w:t", ns)),
        )
        for index, p in enumerate(root.findall(".//w:p", ns))
    ]
