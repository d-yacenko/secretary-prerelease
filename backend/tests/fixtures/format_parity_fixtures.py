"""Deterministic minimal ODF fixtures for Format Parity Pass A tests."""

import zipfile
from pathlib import Path


def _write_odf_zip(path: Path, content_xml: str) -> None:
    mimetype = "application/vnd.oasis.opendocument.text"
    if path.suffix == ".ods":
        mimetype = "application/vnd.oasis.opendocument.spreadsheet"
    elif path.suffix == ".odp":
        mimetype = "application/vnd.oasis.opendocument.presentation"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", mimetype)
        zf.writestr("content.xml", content_xml)


def write_minimal_odt(
    path: Path,
    *,
    heading: str = "ODT Heading",
    paragraph: str = "odt distinctive phrase alpha",
) -> None:
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:text>
      <text:h>{heading}</text:h>
      <text:p>{paragraph}</text:p>
      <text:list>
        <text:list-item><text:p>list item one</text:p></text:list-item>
      </text:list>
      <table:table>
        <table:table-row>
          <table:table-cell><text:p>cell_a</text:p></table:table-cell>
          <table:table-cell><text:p>cell_b</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>"""
    _write_odf_zip(path, content_xml)


def write_malformed_odt(path: Path) -> None:
    path.write_bytes(b"not a zip archive")


def write_odt_zip_bomb(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.xml", b"x" * 1024, compress_type=zipfile.ZIP_DEFLATED)


def write_minimal_ods(path: Path) -> None:
    sheet1 = """
      <table:table table:name="Sheet1">
        <table:table-row>
          <table:table-cell><text:p>col_a</text:p></table:table-cell>
          <table:table-cell><text:p>col_b</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>ods_value</text:p></table:table-cell>
          <table:table-cell table:formula="of:=[.A2]*2" office:value-type="float" office:value="4"><text:p>4</text:p></table:table-cell>
        </table:table-row>
      </table:table>"""
    sheet2 = """
      <table:table table:name="Sheet2">
        <table:table-row>
          <table:table-cell><text:p>sheet2_marker</text:p></table:table-cell>
        </table:table-row>
      </table:table>"""
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      {sheet1}
      {sheet2}
    </office:spreadsheet>
  </office:body>
</office:document-content>"""
    _write_odf_zip(path, content_xml)


def write_ods_with_repeated_rows(path: Path, repeat_count: int = 200) -> None:
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Repeated">
        <table:table-row>
          <table:table-cell><text:p>key</text:p></table:table-cell>
          <table:table-cell><text:p>value</text:p></table:table-cell>
        </table:table-row>
        <table:table-row table:number-rows-repeated="{repeat_count}">
          <table:table-cell><text:p>row</text:p></table:table-cell>
          <table:table-cell table:number-columns-repeated="3"><text:p>cell</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>"""
    _write_odf_zip(path, content_xml)


def write_minimal_odp(path: Path, slide_text: str = "odp distinctive phrase gamma") -> None:
    slide1 = f"""
    <draw:page draw:name="page1">
      <text:h>{slide_text}</text:h>
      <text:list><text:list-item><text:p>bullet one</text:p></text:list-item></text:list>
    </draw:page>"""
    slide2 = """
    <draw:page draw:name="page2">
      <text:p>second slide text</text:p>
      <table:table>
        <table:table-row>
          <table:table-cell><text:p>slide_table_a</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </draw:page>"""
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">
  <office:body>
    <office:presentation>
      {slide1}
      {slide2}
    </office:presentation>
  </office:body>
</office:document-content>"""
    _write_odf_zip(path, content_xml)


def write_large_csv(path: Path, row_count: int, *, marker_row: int | None = None) -> None:
    marker = marker_row if marker_row is not None else row_count - 1
    lines = ["id,label,value"]
    for index in range(row_count):
        label = f"format_parity_marker_row_{index}" if index == marker else f"row_{index}"
        lines.append(f"{index},{label},{index * 2}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_odf_zip_too_many_entries(path: Path) -> None:
    from app.content_extraction.constants import MAX_OOXML_ZIP_ENTRIES

    content_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body><office:text><text:p>safe</text:p></office:text></office:body>
</office:document-content>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", content_xml)
        for index in range(MAX_OOXML_ZIP_ENTRIES):
            zf.writestr(f"extra/{index}.txt", "x")


def write_ods_oversized_repeated_rows(path: Path, repeat_count: int) -> None:
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body><office:spreadsheet>
    <table:table table:name="BigRepeat">
      <table:table-row table:number-rows-repeated="{repeat_count}">
        <table:table-cell><text:p>row</text:p></table:table-cell>
      </table:table-row>
    </table:table>
  </office:spreadsheet></office:body>
</office:document-content>"""
    _write_odf_zip(path, content_xml)


def write_ods_oversized_repeated_columns(path: Path, repeat_count: int) -> None:
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body><office:spreadsheet>
    <table:table table:name="WideRepeat">
      <table:table-row>
        <table:table-cell table:number-columns-repeated="{repeat_count}"><text:p>cell</text:p></table:table-cell>
      </table:table-row>
    </table:table>
  </office:spreadsheet></office:body>
</office:document-content>"""
    _write_odf_zip(path, content_xml)


def write_ods_large_structural_text(path: Path, cell_text: str) -> None:
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body><office:spreadsheet>
    <table:table table:name="Huge">
      <table:table-row>
        <table:table-cell><text:p>{cell_text}</text:p></table:table-cell>
        <table:table-cell><text:p>{cell_text}</text:p></table:table-cell>
      </table:table-row>
    </table:table>
  </office:spreadsheet></office:body>
</office:document-content>"""
    _write_odf_zip(path, content_xml)


def write_variable_width_csv(path: Path, row_count: int) -> None:
    """Narrow first row for budget estimate; later rows are very wide."""
    lines = ["id,payload", "0,tiny"]
    for index in range(1, row_count):
        lines.append(f"{index},{'W' * 12_000}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_large_parquet(path: Path, row_count: int, *, marker_row: int | None = None) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    marker = marker_row if marker_row is not None else row_count - 1
    labels = [
        f"format_parity_marker_row_{index}" if index == marker else f"row_{index}"
        for index in range(row_count)
    ]
    table = pa.table(
        {
            "id": list(range(row_count)),
            "label": labels,
            "value": [index * 2 for index in range(row_count)],
        }
    )
    pq.write_table(table, path)


def write_multi_rowgroup_parquet(path: Path, row_count: int) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "id": list(range(row_count)),
            "label": [f"row_{index}" for index in range(row_count)],
        }
    )
    pq.write_table(table, path, row_group_size=1)
