"""Bounded mechanical ODF extractors — ODT, ODS, ODP."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from app.content_extraction.constants import (
    DATASET_STRUCTURAL_PARTS,
    MAX_ODF_COLUMNS,
    MAX_ODF_REPEAT_EXPANSION,
    MAX_ODF_ROWS_PER_SHEET,
    MAX_ODF_SHEETS,
    MAX_ODP_SLIDES,
    MAX_REPRESENTATION_PARTS,
)
from app.content_extraction.text_representation import (
    build_bounded_text_representations,
    build_text_representations,
    cap_structural_text,
)
from app.content_extraction.text_representation import (
    cap_text as _cap_text,
)
from app.content_extraction.zip_safety import validate_zip_archive
from app.db.models import Representation
from app.services.representation_service import (
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
)

OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
DRAW_NS = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"

ODF_NS = {
    "office": OFFICE_NS,
    "text": TEXT_NS,
    "table": TABLE_NS,
    "draw": DRAW_NS,
}


def _odf_tag(ns_key: str, local: str) -> str:
    return f"{{{ODF_NS[ns_key]}}}{local}"


def _bounded_repeat(raw: str | None, default: int = 1) -> tuple[int, bool]:
    if not raw:
        return default, False
    try:
        value = int(raw)
    except ValueError:
        return default, False
    if value > MAX_ODF_REPEAT_EXPANSION:
        return MAX_ODF_REPEAT_EXPANSION, True
    if value < 1:
        return 1, False
    return value, False


def _element_text(element: ET.Element) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element.iter():
        if child is element:
            continue
        if child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def _read_odf_content_xml(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        validate_zip_archive(archive)
        if "content.xml" not in archive.namelist():
            raise ValueError("missing content.xml")
        return ET.fromstring(archive.read("content.xml"))


def _odt_paragraph_text(element: ET.Element) -> str:
    return _element_text(element)


def _odt_table_rows(table: ET.Element) -> list[str]:
    lines: list[str] = []
    for row_elem in table.findall("table:table-row", ODF_NS):
        row_cells: list[str] = []
        for cell in row_elem.findall("table:table-cell", ODF_NS):
            repeat, _ = _bounded_repeat(
                cell.attrib.get(f"{{{TABLE_NS}}}number-columns-repeated")
            )
            cell_text = _element_text(cell)
            for _ in range(repeat):
                if len(row_cells) >= MAX_ODF_COLUMNS:
                    break
                row_cells.append(cell_text)
        if any(row_cells):
            lines.append("| " + " | ".join(row_cells) + " |")
    return lines


def _odt_list_items(list_elem: ET.Element) -> list[str]:
    items: list[str] = []
    for item in list_elem.findall(".//text:list-item", ODF_NS):
        text = _element_text(item)
        if text:
            items.append(f"- {text}")
    return items


def extract_odt_text(path: Path) -> tuple[str, bool]:
    root = _read_odf_content_xml(path)
    body = root.find(".//office:body", ODF_NS)
    if body is None:
        raise ValueError("missing office:body")
    office_text = body.find("office:text", ODF_NS)
    if office_text is None:
        raise ValueError("missing office:text")

    lines: list[str] = []
    for child in office_text:
        tag = child.tag
        if tag == _odf_tag("text", "h") or tag == _odf_tag("text", "p"):
            text = _odt_paragraph_text(child)
            if text:
                lines.append(text)
        elif tag == _odf_tag("text", "list"):
            lines.extend(_odt_list_items(child))
        elif tag == _odf_tag("table", "table"):
            lines.extend(_odt_table_rows(child))

    text = "\n".join(lines)
    if not text.strip():
        raise ValueError("no_extractable_text")
    capped, truncated = _cap_text(text)
    return capped, truncated


def extract_odt_representations(
    object_id, path: Path, source_bytes: int
) -> tuple[list[Representation], bool]:
    text, truncated = extract_odt_text(path)
    reps, text_truncated = build_text_representations(
        object_id,
        text,
        {"source_bytes": source_bytes},
    )
    return reps, truncated or text_truncated


def _odp_page_lines(page: ET.Element) -> list[str]:
    table_descendant_ids = {
        id(desc)
        for cell in page.findall(".//table:table-cell", ODF_NS)
        for desc in cell.iter()
    }
    lines: list[str] = []
    for element in page.iter():
        tag = element.tag
        if tag == _odf_tag("text", "h"):
            text = _element_text(element)
            if text:
                lines.append(text)
        elif tag == _odf_tag("text", "list-item"):
            text = _element_text(element)
            if text:
                lines.append(f"- {text}")
        elif tag == _odf_tag("table", "table-row"):
            row_cells: list[str] = []
            for cell in element.findall("table:table-cell", ODF_NS):
                repeat, _ = _bounded_repeat(
                    cell.attrib.get(f"{{{TABLE_NS}}}number-columns-repeated")
                )
                cell_text = _element_text(cell)
                for _ in range(repeat):
                    if len(row_cells) >= MAX_ODF_COLUMNS:
                        break
                    row_cells.append(cell_text)
            if any(row_cells):
                lines.append("| " + " | ".join(row_cells) + " |")
        elif tag == _odf_tag("text", "p"):
            if id(element) in table_descendant_ids:
                continue
            text = _element_text(element)
            if text:
                lines.append(text)
    return lines


def extract_odp_representations(
    object_id, path: Path, source_bytes: int
) -> tuple[list[Representation], bool]:
    root = _read_odf_content_xml(path)
    presentation = root.find(".//office:presentation", ODF_NS)
    if presentation is None:
        raise ValueError("missing office:presentation")
    pages = list(presentation.findall("draw:page", ODF_NS))
    truncated = len(pages) > MAX_ODP_SLIDES
    selected = pages[:MAX_ODP_SLIDES]

    lines: list[str] = []
    for index, page in enumerate(selected, start=1):
        lines.append(f"[slide {index}]")
        lines.extend(_odp_page_lines(page))

    text, char_trunc = _cap_text("\n".join(lines))
    reps, text_trunc = build_text_representations(
        object_id,
        text,
        {"slide_count": len(selected), "source_bytes": source_bytes},
    )
    return reps, truncated or char_trunc or text_trunc


def _ods_cell_value(cell: ET.Element) -> str:
    formula = cell.attrib.get(f"{{{TABLE_NS}}}formula")
    text = _element_text(cell)
    if text:
        return text
    value_type = cell.attrib.get(f"{{{OFFICE_NS}}}value-type")
    if value_type == "float":
        raw = cell.attrib.get(f"{{{OFFICE_NS}}}value")
        return raw or ""
    if formula:
        return ""
    return text


def _parse_ods_sheet_rows(table: ET.Element) -> tuple[list[tuple[int, dict[str, str]]], bool, int]:
    parsed_rows: list[tuple[int, dict[str, str]]] = []
    truncated = False
    max_used_cols = 0
    row_num = 0

    for row_elem in table.findall("table:table-row", ODF_NS):
        row_repeat, row_repeat_truncated = _bounded_repeat(
            row_elem.attrib.get(f"{{{TABLE_NS}}}number-rows-repeated")
        )
        truncated = truncated or row_repeat_truncated
        for _ in range(row_repeat):
            if len(parsed_rows) >= MAX_ODF_ROWS_PER_SHEET:
                truncated = True
                return parsed_rows, truncated, max_used_cols
            row_num += 1
            cells: dict[str, str] = {}
            col_index = 0
            row_truncated = False
            for cell in row_elem.findall("table:table-cell", ODF_NS):
                col_repeat, col_repeat_truncated = _bounded_repeat(
                    cell.attrib.get(f"{{{TABLE_NS}}}number-columns-repeated")
                )
                truncated = truncated or col_repeat_truncated
                value = _ods_cell_value(cell).strip()
                for _ in range(col_repeat):
                    if col_index >= MAX_ODF_COLUMNS:
                        row_truncated = True
                        truncated = True
                        break
                    if value:
                        col_letter = _index_to_col_letter(col_index)
                        cells[col_letter] = value
                        max_used_cols = max(max_used_cols, col_index + 1)
                    col_index += 1
                if row_truncated:
                    break
            if cells:
                parsed_rows.append((row_num, cells))
    return parsed_rows, truncated, min(max_used_cols, MAX_ODF_COLUMNS)


def _index_to_col_letter(index: int) -> str:
    index += 1
    letters: list[str] = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def _col_letter_to_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _format_ods_sparse_columns(cells: dict[str, str]) -> str:
    ordered = sorted(cells.items(), key=lambda item: _col_letter_to_index(item[0]))
    return ", ".join(f"{col}={value}" for col, value in ordered)


def _format_ods_sparse_row(row_num: int, cells: dict[str, str]) -> str:
    ordered = sorted(cells.items(), key=lambda item: _col_letter_to_index(item[0]))
    parts = [f"{col}={value}" for col, value in ordered]
    return f"row={row_num} " + " | ".join(parts)


def _format_ods_searchable_row(sheet_name: str, row_num: int, cells: dict[str, str]) -> str:
    ordered = sorted(cells.items(), key=lambda item: _col_letter_to_index(item[0]))
    parts = [f"{col}={value}" for col, value in ordered]
    return f"[sheet={sheet_name} row={row_num}]\n" + " | ".join(parts)


def _ods_header_row_index(parsed_rows: list[tuple[int, dict[str, str]]]) -> int:
    for index, (_, cells) in enumerate(parsed_rows):
        if len(cells) >= 2:
            return index
    return 0


def extract_ods_representations(
    object_id, path: Path
) -> tuple[list[Representation], bool]:
    root = _read_odf_content_xml(path)
    tables = root.findall(".//table:table", ODF_NS)
    truncated = len(tables) > MAX_ODF_SHEETS
    selected_tables = tables[:MAX_ODF_SHEETS]

    schema_lines = ["schema"]
    sample_lines = ["sample"]
    stats_lines = ["statistics"]
    searchable_lines: list[str] = []

    for table in selected_tables:
        sheet_name = table.attrib.get(f"{{{TABLE_NS}}}name", "Sheet")
        parsed_rows, sheet_truncated, max_used_cols = _parse_ods_sheet_rows(table)
        truncated = truncated or sheet_truncated
        if not parsed_rows:
            schema_lines.append(f"{sheet_name}: (empty)")
            stats_lines.append(f"{sheet_name}: rows=0, columns=0")
            continue

        header_index = _ods_header_row_index(parsed_rows)
        header_row_num, header_cells = parsed_rows[header_index]
        data_rows = parsed_rows[header_index + 1 :]

        schema_lines.append(f"{sheet_name}: {_format_ods_sparse_columns(header_cells)}")
        sample_lines.append(f"[{sheet_name}]")
        sample_lines.append(_format_ods_sparse_row(header_row_num, header_cells))
        for row_num, cells in data_rows[:5]:
            sample_lines.append(_format_ods_sparse_row(row_num, cells))
        stats_lines.append(
            f"{sheet_name}: rows={len(data_rows)}, columns={max_used_cols}"
        )
        for row_num, cells in parsed_rows:
            searchable_lines.append(_format_ods_searchable_row(sheet_name, row_num, cells))

    schema_text, schema_trunc = cap_structural_text("\n".join(schema_lines))
    sample_text, sample_trunc = cap_structural_text("\n".join(sample_lines))
    stats_text, stats_trunc = cap_structural_text("\n".join(stats_lines))
    truncated = truncated or schema_trunc or sample_trunc or stats_trunc

    structural_reps = [
        Representation(
            object_id=object_id,
            kind=KIND_SCHEMA,
            text=schema_text,
            metadata_={"sheet_count": len(selected_tables)},
        ),
        Representation(
            object_id=object_id,
            kind=KIND_SAMPLE,
            text=sample_text,
            metadata_={"sheet_count": len(selected_tables)},
        ),
        Representation(
            object_id=object_id,
            kind=KIND_STATISTICS,
            text=stats_text,
            metadata_={"sheet_count": len(selected_tables)},
        ),
    ]

    remaining_parts = max(0, MAX_REPRESENTATION_PARTS - DATASET_STRUCTURAL_PARTS)
    searchable_text = "\n".join(searchable_lines)
    searchable_reps, searchable_trunc = build_bounded_text_representations(
        object_id,
        searchable_text,
        remaining_parts,
        {"sheet_count": len(selected_tables)},
    )
    return structural_reps + searchable_reps, truncated or searchable_trunc
