from __future__ import annotations

from localdataextractor.models import DocumentMetadata, NormalizedDocument, TableBlock
from localdataextractor.render.markdown_renderer import render_markdown


def test_render_markdown_with_table() -> None:
    doc = NormalizedDocument(
        schema_version="1.0",
        source=DocumentMetadata(source_path="a.txt", file_size=1, file_type="txt"),
        title="Doc",
        paragraphs=[{"text": "Hello"}],
        tables=[
            TableBlock(
                table_id="tbl_1",
                header_rows=[["Col1", "Col2"]],
                body_rows=[["1", "2"]],
                column_count=2,
                row_count=1,
                confidence=99.0,
            )
        ],
    )
    out = render_markdown(doc)
    assert "# Doc" in out
    assert "| Col1 | Col2 |" in out
    assert "| 1 | 2 |" in out
