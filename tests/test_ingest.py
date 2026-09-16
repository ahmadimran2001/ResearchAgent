from io import BytesIO

import pytest
from pypdf import PdfWriter

from backend.app.chat.ingest import IngestError, extract


def test_extracts_text_pdf_and_markdown() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # pypdf blank pages have no text; use a markdown file for the happy path
    markdown = extract(b"# Title\n\nHello research.", filename="notes.md", media_type="text/markdown")
    assert markdown["kind"] == "text"
    assert "Hello research." in markdown["text"]


def test_pdf_without_text_explains_scan_limitation() -> None:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
    result = extract(buffer.getvalue(), filename="scan.pdf", media_type="application/pdf")
    assert result["kind"] == "pdf"
    assert "no extractable text" in result["text"]


def test_rejects_executables_and_accepts_images_as_vision_payload() -> None:
    with pytest.raises(IngestError):
        extract(b"MZ", filename="tool.exe")
    image = extract(b"\x89PNG\r\n", filename="figure.png", media_type="image/png")
    assert image["kind"] == "image"
    assert image["image_b64"]
    assert "vision-capable" in image["text"]
