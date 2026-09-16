"""Generate tiny non-sensitive fixtures for PHASE 29A mechanical extraction tests."""

import zipfile
from pathlib import Path


def write_txt(path: Path, text: str = "phase29a distinctive phrase alpha") -> None:
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path) -> None:
    path.write_text("name,value\nalpha,1\nbeta,2\n", encoding="utf-8")


def write_minimal_docx(path: Path, text: str = "docx paragraph with distinctive phrase beta") -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>cell1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>cell2</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", document_xml)


def write_minimal_xlsx(path: Path) -> None:
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
    <sheet name="Sheet2" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>"""
    sheet1 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>col_a</t></is></c><c r="B1" t="inlineStr"><is><t>col_b</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>xlsx_value</t></is></c><c r="B2" t="inlineStr"><is><t>2</t></is></c></row>
  </sheetData>
</worksheet>"""
    sheet2 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>sheet2</t></is></c></row>
  </sheetData>
</worksheet>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1)
        zf.writestr("xl/worksheets/sheet2.xml", sheet2)


def write_xlsx_search_regression_workbook(
    path: Path,
    *,
    target_phrase: str = "phase29a_row15_target_phrase_marker",
    data_rows: int = 46,
    header_row: int = 14,
) -> None:
    """Synthetic workbook: preamble rows, sparse columns, target phrase at first data row."""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Учебный план" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    rows_xml: list[str] = []
    for preamble_row in range(1, header_row):
        rows_xml.append(f'<row r="{preamble_row}"></row>')
    rows_xml.append(
        f'<row r="{header_row}">'
        f'<c r="A{header_row}" t="inlineStr"><is><t>Раздел</t></is></c>'
        f'<c r="D{header_row}" t="inlineStr"><is><t>Тема</t></is></c>'
        f'<c r="H{header_row}" t="inlineStr"><is><t>Часы</t></is></c>'
        f"</row>"
    )
    for offset in range(data_rows):
        row_num = header_row + 1 + offset
        topic = target_phrase if offset == 0 else f"topic_row_{row_num}"
        rows_xml.append(
            f'<row r="{row_num}">'
            f'<c r="A{row_num}" t="inlineStr"><is><t>Учебная часть</t></is></c>'
            f'<c r="D{row_num}" t="inlineStr"><is><t>{topic}</t></is></c>'
            f'<c r="H{row_num}" t="inlineStr"><is><t>2</t></is></c>'
            f"</row>"
        )
    sheet1 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        + "".join(rows_xml)
        + "</sheetData></worksheet>"
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1)


def write_minimal_pptx(path: Path, slide_text: str = "slide distinctive phrase gamma") -> None:
    slide = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>{slide_text}</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"""
    slide2 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>second slide</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/slides/slide1.xml", slide)
        zf.writestr("ppt/slides/slide2.xml", slide2)


def write_minimal_pdf(path: Path, text: str = "pdf distinctive phrase delta") -> None:
    path.write_bytes(_minimal_pdf_bytes(text))


def _minimal_pdf_bytes(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET"
    objs = [
        "1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        "2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        "3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n",
        f"4 0 obj<< /Length {len(stream)} >>stream\n{stream}\nendstream endobj\n",
        "5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    header = b"%PDF-1.4\n"
    body_parts: list[bytes] = []
    xref_positions: list[int] = []
    pos = len(header)
    for obj in objs:
        xref_positions.append(pos)
        chunk = obj.encode()
        body_parts.append(chunk)
        pos += len(chunk)
    body = b"".join(body_parts)
    xref_start = pos
    xref_lines = ["xref\n", f"0 {len(objs) + 1}\n", "0000000000 65535 f \n"]
    for offset in xref_positions:
        xref_lines.append(f"{offset:010d} 00000 n \n")
    xref = "".join(xref_lines).encode()
    trailer = f"trailer<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode()
    return header + body + xref + trailer


def write_blank_pdf(path: Path) -> None:
    """PDF page with no extractable text layer."""
    path.write_bytes(_blank_pdf_bytes())


def _blank_pdf_bytes() -> bytes:
    objs = [
        "1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        "2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        "3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>endobj\n",
    ]
    header = b"%PDF-1.4\n"
    body_parts: list[bytes] = []
    xref_positions: list[int] = []
    pos = len(header)
    for obj in objs:
        xref_positions.append(pos)
        chunk = obj.encode()
        body_parts.append(chunk)
        pos += len(chunk)
    body = b"".join(body_parts)
    xref_start = pos
    xref_lines = ["xref\n", f"0 {len(objs) + 1}\n", "0000000000 65535 f \n"]
    for offset in xref_positions:
        xref_lines.append(f"{offset:010d} 00000 n \n")
    xref = "".join(xref_lines).encode()
    trailer = f"trailer<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode()
    return header + body + xref + trailer


def write_minimal_parquet(path: Path, marker: str = "parquet_marker_alpha") -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "marker": [marker, "row_two"],
            "value": [1, 2],
        }
    )
    pq.write_table(table, path)


def write_zip_bomb(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.txt", b"0" * (1024 * 1024), compress_type=zipfile.ZIP_DEFLATED)
