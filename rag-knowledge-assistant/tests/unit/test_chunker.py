import numpy as np

from app.ingestion.chunker import chunk_document
from app.ingestion.parsers import parse_file
from app.textproc import estimate_tokens
from tests.conftest import ROOT, write_doc


def _doc(tmp_path, body, name="d.md"):
    return parse_file(write_doc(tmp_path, name, {"doc_id": "d", "title": "Doc"}, body))


def test_tables_are_never_split_and_keep_lead_in(tmp_path):
    rows = "\n".join(f"| r{i} | value {i} |" for i in range(6))
    doc = _doc(tmp_path, f"# Doc\n## Rates\nThe rates are:\n| Key | Value |\n| --- | --- |\n{rows}\n")
    chunks = chunk_document(doc, max_tokens=200)
    holder = [c for c in chunks if "| Key | Value |" in c.content]
    assert len(holder) == 1 and all(f"| r{i} |" in holder[0].content for i in range(6))
    assert "The rates are:" in holder[0].content


def test_oversized_table_split_by_rows_with_header_repeated(tmp_path):
    rows = "\n".join(f"| row{i} | " + "word " * 12 + "|" for i in range(30))
    doc = _doc(tmp_path, f"# Doc\n## Big\n| Key | Value |\n| --- | --- |\n{rows}\n")
    chunks = [c for c in chunk_document(doc, max_tokens=120) if "| Key | Value |" in c.content]
    assert len(chunks) > 1
    assert all(c.content.count("| Key | Value |") == 1 for c in chunks)
    assert sum(c.content.count("| row") for c in chunks) == 30  # no row lost or duplicated


def test_policy_clauses_stay_whole(tmp_path):
    clauses = [f"4.{i} " + " ".join(f"clause{i}word{j}" for j in range(25)) + "." for i in range(1, 9)]
    doc = _doc(tmp_path, "# Doc\n## Rules\n" + "\n".join(clauses))
    chunks = chunk_document(doc, max_tokens=90, min_tokens=20)
    assert len(chunks) > 1
    for cl in clauses:
        assert sum(cl in c.content for c in chunks) == 1, "clause split across chunks"


def test_semantic_split_prefers_low_similarity_boundary(tmp_path):
    paras = ["alpha " * 30, "alpha beta " * 15, "gamma " * 30, "gamma delta " * 15]
    doc = _doc(tmp_path, "# Doc\n## S\n" + "\n\n".join(p.strip() + "." for p in paras))

    def embed(texts):  # alpha-ish vs gamma-ish units
        return np.array([[1.0, 0.0] if "alpha" in t else [0.0, 1.0] for t in texts])

    chunks = chunk_document(doc, embed=embed, max_tokens=110, min_tokens=20)
    assert len(chunks) == 2
    assert "alpha" in chunks[0].content and "gamma" not in chunks[0].content


def test_heading_path_and_context_header():
    doc = parse_file(ROOT / "data" / "sample_docs" / "hr" / "remote-work-policy.md")
    chunks = chunk_document(doc)
    hybrid = next(c for c in chunks if "anchor days" in c.content)
    assert hybrid.context_header == "Remote and Hybrid Work Policy (HR-POL-104) > 2. Hybrid Schedule"
    assert hybrid.embed_text.startswith(hybrid.context_header)
    assert all(c.token_count <= 200 for c in chunks)


def test_small_sections_are_merged_with_related_siblings(tmp_path):
    doc = _doc(tmp_path, "# Doc\n## A\nShort one.\n## B\nShort two.\n## C\nShort three.\n")
    chunks = chunk_document(doc, max_tokens=200, min_tokens=40)
    assert len(chunks) == 1 and "## A" in chunks[0].content and "## C" in chunks[0].content


def test_chunk_hash_is_stable_and_content_sensitive(tmp_path):
    a = chunk_document(_doc(tmp_path, "# Doc\n## S\nSame text here.", "a.md"))[0]
    b = chunk_document(_doc(tmp_path, "# Doc\n## S\nSame text here.", "b.md"))[0]
    c = chunk_document(_doc(tmp_path, "# Doc\n## S\nDifferent text.", "c.md"))[0]
    assert a.content_hash == b.content_hash != c.content_hash
    assert estimate_tokens(a.content) == a.token_count
