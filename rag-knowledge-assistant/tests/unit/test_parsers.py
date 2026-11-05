from pathlib import Path

import pytest

from app.ingestion.parsers import ParseError, parse_file, parse_markdown_body, parse_text_body
from tests.conftest import ROOT, write_doc


def test_markdown_front_matter_headings_and_tables(tmp_path):
    p = write_doc(tmp_path, "pol.md", {"doc_id": "Pol 1", "title": "Policy", "team": "HR", "version": "2.0",
                                       "updated": "2026-01-01", "visibility": "team", "audience": ["hr"]}, """
        # Policy
        ## Section A
        2.1 First clause text.
        2.2 Second clause text.
        ## Rates
        | Tier | Amount |
        | --- | --- |
        | 1 | $95 |
    """)
    doc = parse_file(p)
    assert doc.meta.doc_id == "pol-1" and doc.meta.team == "hr" and doc.meta.version_label == "2.0"
    assert doc.meta.visibility == "team" and doc.meta.audience == ["hr"] and str(doc.meta.updated) == "2026-01-01"
    kinds = [(b.kind, b.heading_path) for b in doc.blocks if b.kind != "heading"]
    assert ("clause", ("Policy", "Section A")) in kinds
    table = next(b for b in doc.blocks if b.kind == "table")
    assert table.heading_path == ("Policy", "Rates") and table.text.count("\n") == 2


def test_clauses_are_separate_units():
    blocks = parse_markdown_body("# T\n3.1 Alpha clause.\n3.2 Beta clause.\n")
    assert [b.text for b in blocks if b.kind == "clause"] == ["3.1 Alpha clause.", "3.2 Beta clause."]


def test_plain_text_caps_headings_and_line_lists():
    blocks = parse_text_body("TITLE HERE\n\nINTRO\nSome intro sentence.\n\nDAYS\nMonday - one\nTuesday - two\n")
    heads = [b.text for b in blocks if b.kind == "heading"]
    assert heads == ["TITLE HERE", "INTRO", "DAYS"]
    assert [b.text for b in blocks if b.kind == "list_item"] == ["- Monday - one", "- Tuesday - two"]


def test_pdf_tables_and_sidecar_metadata():
    doc = parse_file(ROOT / "data" / "sample_docs" / "security" / "security-incident-reporting.pdf")
    assert doc.meta.doc_id == "sec-incident-reporting" and doc.meta.team == "security"
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 1 and "| Critical | Ransomware, active intrusion | 15 minutes |" in tables[0].text
    # table cells must not leak into body paragraphs
    assert not any("Ransomware" in b.text for b in doc.blocks if b.kind == "paragraph")
    assert any(b.kind == "heading" and b.text == "How to Report" for b in doc.blocks)


@pytest.mark.parametrize("front,err", [
    ({"visibility": "secret"}, "invalid visibility"),
    ({"visibility": "restricted"}, "allowed_roles"),
])
def test_invalid_metadata_rejected(tmp_path, front, err):
    p = write_doc(tmp_path, "bad.md", {"title": "x", **front}, "# X\nbody text here")
    with pytest.raises(ParseError, match=err):
        parse_file(p)


def test_unsupported_type(tmp_path):
    (tmp_path / "a.docx").write_bytes(b"x")
    with pytest.raises(ParseError):
        parse_file(Path(tmp_path / "a.docx"))
