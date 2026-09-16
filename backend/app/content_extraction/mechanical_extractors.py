"""Bounded mechanical text/dataset/office extractors — no LLM."""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from app.content_extraction.constants import (
    MAX_PDF_PAGES,
    MAX_PPTX_SLIDES,
    MAX_REPRESENTATION_PARTS,
    MAX_XLSX_COLUMNS,
    MAX_XLSX_ROWS_PER_SHEET,
    MAX_XLSX_SHEETS,
)
from app.content_extraction.dataset_sampling import (
    IndexedRow,
    build_indexed_dataset_representations,
    compact_preview_indices,
    plan_searchable_indices,
)
from app.content_extraction.odf_extractors import (
    extract_odp_representations,
    extract_ods_representations,
    extract_odt_representations,
)
from app.content_extraction.text_representation import (
    build_bounded_text_representations,
    build_text_representations,
)
from app.content_extraction.text_representation import (
    cap_text as _cap_text,
)
from app.content_extraction.zip_safety import validate_zip_archive
from app.db.models import Representation
from app.local.bounded_io import (
    bounded_parquet_stats,
    count_csv_rows,
    read_bounded_text,
    read_csv_header,
    read_csv_indexed_rows,
    read_csv_sample_rows,
    read_parquet_indexed_rows,
    read_parquet_sample_rows,
    read_parquet_schema,
    stream_csv_stats,
)
from app.services.representation_service import (
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
    _format_sample_text,
    _format_schema_text,
)

DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
PPTX_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
XLSX_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

XLSX_CELL_REF_RE = re.compile(r"^([A-Za-z]+)(\d+)$")
XLSX_STRUCTURAL_PARTS = 3


def extract_from_path(object_id, path: Path) -> tuple[list[Representation], dict[str, Any]]:
    suffix = path.suffix.lower()
    truncated = False
    source_bytes = path.stat().st_size

    if suffix in {".txt", ".md"}:
        text, source_meta = read_bounded_text(path)
        reps, truncated = build_text_representations(object_id, text, source_meta)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": suffix,
            "content_truncated": truncated or bool(source_meta.get("truncated")),
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    if suffix == ".csv":
        reps, dataset_meta = _build_csv_representations(object_id, path)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".csv",
            "content_truncated": dataset_meta.get("dataset_sampling_truncated", False),
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
            **dataset_meta,
        }

    if suffix == ".parquet":
        reps, dataset_meta = _build_parquet_representations(object_id, path)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".parquet",
            "content_truncated": dataset_meta.get("dataset_sampling_truncated", False),
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
            **dataset_meta,
        }

    if suffix == ".pdf":
        text, truncated = _extract_pdf_text(path)
        reps, text_truncated = build_text_representations(
            object_id,
            text,
            {"source_bytes": source_bytes},
        )
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".pdf",
            "content_truncated": truncated or text_truncated,
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    if suffix == ".docx":
        text, truncated = _extract_docx_text(path)
        reps, text_truncated = build_text_representations(
            object_id,
            text,
            {"source_bytes": source_bytes},
        )
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".docx",
            "content_truncated": truncated or text_truncated,
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    if suffix == ".xlsx":
        reps, truncated = _build_xlsx_representations(object_id, path)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".xlsx",
            "content_truncated": truncated,
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    if suffix == ".pptx":
        reps, truncated = _build_pptx_representations(object_id, path)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".pptx",
            "content_truncated": truncated,
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    if suffix == ".odt":
        reps, truncated = extract_odt_representations(object_id, path, source_bytes)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".odt",
            "content_truncated": truncated,
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    if suffix == ".ods":
        reps, truncated = extract_ods_representations(object_id, path)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".ods",
            "content_truncated": truncated,
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    if suffix == ".odp":
        reps, truncated = extract_odp_representations(object_id, path, source_bytes)
        extracted_chars = sum(len(rep.text) for rep in reps)
        return reps, {
            "content_format": ".odp",
            "content_truncated": truncated,
            "content_source_bytes": source_bytes,
            "content_extracted_chars": extracted_chars,
        }

    raise ValueError(f"unsupported mechanical extraction suffix: {suffix}")


def _extract_pdf_text(path: Path) -> tuple[str, bool]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("encrypted pdf")
    pages = reader.pages[:MAX_PDF_PAGES]
    truncated = len(reader.pages) > MAX_PDF_PAGES
    parts: list[str] = []
    for index, page in enumerate(pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if page_text:
            parts.append(f"[page {index}]\n{page_text}")
    text = "\n\n".join(parts).strip()
    if not text:
        raise ValueError("no_extractable_text")
    capped, char_truncated = _cap_text(text)
    return capped, truncated or char_truncated


def _extract_docx_text(path: Path) -> tuple[str, bool]:
    with zipfile.ZipFile(path) as archive:
        validate_zip_archive(archive)
        xml_bytes = archive.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", DOCX_NS):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", DOCX_NS)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    for table in root.findall(".//w:tbl", DOCX_NS):
        for row in table.findall(".//w:tr", DOCX_NS):
            cells = row.findall(".//w:tc", DOCX_NS)
            cell_texts: list[str] = []
            for cell in cells:
                cell_text = "".join(
                    (node.text or "") for node in cell.findall(".//w:t", DOCX_NS)
                ).strip()
                cell_texts.append(cell_text)
            if any(cell_texts):
                paragraphs.append("| " + " | ".join(cell_texts) + " |")
    text = "\n".join(paragraphs)
    capped, truncated = _cap_text(text)
    return capped, truncated


def _build_csv_representations(
    object_id, path: Path
) -> tuple[list[Representation], dict[str, Any]]:
    fieldnames = read_csv_header(path)
    stats_meta, stats_lines, column_types = stream_csv_stats(path, fieldnames)
    total_rows = stats_meta.get("row_count")
    if total_rows is None:
        total_rows = count_csv_rows(path)

    _, estimate_rows = read_csv_sample_rows(path, 1)
    estimate_row = estimate_rows[0] if estimate_rows else {name: "" for name in fieldnames}
    structural_bytes = len(
        _format_schema_text(fieldnames, column_types).encode("utf-8")
    ) + len("\n".join(stats_lines).encode("utf-8"))

    compact_indices = compact_preview_indices(total_rows)
    compact_estimate = _format_sample_text(
        [estimate_row] * min(len(compact_indices), 1), fieldnames
    )
    searchable_indices, sampling_mode, sampling_truncated = plan_searchable_indices(
        total_rows=total_rows,
        fieldnames=fieldnames,
        estimate_row=estimate_row,
        structural_bytes=structural_bytes,
        compact_sample_bytes=len(compact_estimate.encode("utf-8")),
    )
    all_indices = sorted(set(compact_indices) | set(searchable_indices))
    indexed_rows = [
        IndexedRow(index=index, values=values)
        for index, values in read_csv_indexed_rows(path, fieldnames, all_indices)
    ]
    return build_indexed_dataset_representations(
        object_id,
        fieldnames=fieldnames,
        column_types=column_types,
        stats_meta=stats_meta,
        stats_lines=stats_lines,
        total_rows=total_rows,
        indexed_rows=indexed_rows,
        compact_indices=compact_indices,
        searchable_indices=searchable_indices,
        sampling_mode=sampling_mode,
        sampling_truncated=sampling_truncated,
    )


def _build_parquet_representations(
    object_id, path: Path
) -> tuple[list[Representation], dict[str, Any]]:
    fieldnames, column_types, row_count = read_parquet_schema(path)
    stats_meta, stats_lines = bounded_parquet_stats(path, fieldnames, column_types, row_count)

    _, estimate_rows = read_parquet_sample_rows(path, 1)
    estimate_row = estimate_rows[0] if estimate_rows else {name: "" for name in fieldnames}
    structural_bytes = len(
        _format_schema_text(fieldnames, column_types).encode("utf-8")
    ) + len("\n".join(stats_lines).encode("utf-8"))

    compact_indices = compact_preview_indices(row_count)
    compact_estimate = _format_sample_text(
        [estimate_row] * min(len(compact_indices), 1), fieldnames
    )
    searchable_indices, sampling_mode, sampling_truncated = plan_searchable_indices(
        total_rows=row_count,
        fieldnames=fieldnames,
        estimate_row=estimate_row,
        structural_bytes=structural_bytes,
        compact_sample_bytes=len(compact_estimate.encode("utf-8")),
    )
    all_indices = sorted(set(compact_indices) | set(searchable_indices))
    _, indexed_tuples = read_parquet_indexed_rows(path, all_indices)
    indexed_rows = [IndexedRow(index=index, values=values) for index, values in indexed_tuples]
    return build_indexed_dataset_representations(
        object_id,
        fieldnames=fieldnames,
        column_types=column_types,
        stats_meta=stats_meta,
        stats_lines=stats_lines,
        total_rows=row_count,
        indexed_rows=indexed_rows,
        compact_indices=compact_indices,
        searchable_indices=searchable_indices,
        sampling_mode=sampling_mode,
        sampling_truncated=sampling_truncated,
    )


def _build_xlsx_representations(object_id, path: Path) -> tuple[list[Representation], bool]:
    with zipfile.ZipFile(path) as archive:
        validate_zip_archive(archive)
        shared_strings = _read_xlsx_shared_strings(archive)
        sheet_names = _read_xlsx_sheet_names(archive)
        truncated = len(sheet_names) > MAX_XLSX_SHEETS
        selected_sheets = sheet_names[:MAX_XLSX_SHEETS]

        schema_lines = ["schema"]
        sample_lines = ["sample"]
        stats_lines = ["statistics"]
        searchable_lines: list[str] = []
        for sheet_name in selected_sheets:
            parsed_rows, sheet_truncated, max_used_cols = _read_xlsx_sheet_parsed(
                archive, sheet_name, shared_strings
            )
            truncated = truncated or sheet_truncated
            if not parsed_rows:
                schema_lines.append(f"{sheet_name}: (empty)")
                stats_lines.append(f"{sheet_name}: rows=0, columns=0")
                continue

            header_index = _xlsx_header_row_index(parsed_rows)
            header_row_num, header_cells = parsed_rows[header_index]
            data_rows = parsed_rows[header_index + 1 :]

            schema_cols = _format_xlsx_sparse_columns(header_cells)
            schema_lines.append(f"{sheet_name}: {schema_cols}")

            sample_lines.append(f"[{sheet_name}]")
            sample_lines.append(_format_xlsx_sparse_row(header_row_num, header_cells))
            for row_num, cells in data_rows[:5]:
                sample_lines.append(_format_xlsx_sparse_row(row_num, cells))

            stats_lines.append(
                f"{sheet_name}: rows={len(data_rows)}, columns={max_used_cols}"
            )

            for row_num, cells in parsed_rows:
                searchable_lines.append(
                    _format_xlsx_searchable_row(sheet_name, row_num, cells)
                )

        schema_text, schema_trunc = _cap_text("\n".join(schema_lines))
        sample_text, sample_trunc = _cap_text("\n".join(sample_lines))
        stats_text, stats_trunc = _cap_text("\n".join(stats_lines))
        truncated = truncated or schema_trunc or sample_trunc or stats_trunc

        structural_reps = [
            Representation(
                object_id=object_id,
                kind=KIND_SCHEMA,
                text=schema_text,
                metadata_={"sheet_count": len(selected_sheets)},
            ),
            Representation(
                object_id=object_id,
                kind=KIND_SAMPLE,
                text=sample_text,
                metadata_={"sheet_count": len(selected_sheets)},
            ),
            Representation(
                object_id=object_id,
                kind=KIND_STATISTICS,
                text=stats_text,
                metadata_={"sheet_count": len(selected_sheets)},
            ),
        ]

        remaining_parts = max(0, MAX_REPRESENTATION_PARTS - XLSX_STRUCTURAL_PARTS)
        searchable_text = "\n".join(searchable_lines)
        searchable_reps, searchable_trunc = build_bounded_text_representations(
            object_id,
            searchable_text,
            remaining_parts,
            {"sheet_count": len(selected_sheets)},
        )
        truncated = truncated or searchable_trunc

        return structural_reps + searchable_reps, truncated


def _build_pptx_representations(object_id, path: Path) -> tuple[list[Representation], bool]:
    with zipfile.ZipFile(path) as archive:
        validate_zip_archive(archive)
        slide_paths = sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        truncated = len(slide_paths) > MAX_PPTX_SLIDES
        selected = slide_paths[:MAX_PPTX_SLIDES]
        lines: list[str] = []
        for index, slide_path in enumerate(selected, start=1):
            xml_bytes = archive.read(slide_path)
            root = ET.fromstring(xml_bytes)
            texts = [
                node.text.strip()
                for node in root.findall(".//a:t", PPTX_NS)
                if node.text and node.text.strip()
            ]
            lines.append(f"[slide {index}]")
            lines.extend(texts)
        text, char_trunc = _cap_text("\n".join(lines))
        reps, text_trunc = build_text_representations(
            object_id,
            text,
            {"slide_count": len(selected)},
        )
        return reps, truncated or char_trunc or text_trunc


def _read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("main:si", XLSX_NS):
        texts = [node.text or "" for node in item.findall(".//main:t", XLSX_NS)]
        strings.append("".join(texts))
    return strings


def _read_xlsx_sheet_names(archive: zipfile.ZipFile) -> list[str]:
    if "xl/workbook.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/workbook.xml"))
    names: list[str] = []
    for sheet in root.findall(".//main:sheet", XLSX_NS):
        name = sheet.attrib.get("name")
        if name:
            names.append(name)
    return names


def _col_letter_to_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _index_to_col_letter(index: int) -> str:
    index += 1
    letters: list[str] = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def _parse_xlsx_cell_ref(ref: str) -> tuple[str, int] | None:
    match = XLSX_CELL_REF_RE.match(ref)
    if match is None:
        return None
    return match.group(1).upper(), int(match.group(2))


def _xlsx_header_row_index(parsed_rows: list[tuple[int, dict[str, str]]]) -> int:
    for index, (_, cells) in enumerate(parsed_rows):
        if len(cells) >= 2:
            return index
    return 0


def _format_xlsx_sparse_columns(cells: dict[str, str]) -> str:
    ordered = sorted(cells.items(), key=lambda item: _col_letter_to_index(item[0]))
    return ", ".join(f"{col}={value}" for col, value in ordered)


def _format_xlsx_sparse_row(row_num: int, cells: dict[str, str]) -> str:
    ordered = sorted(cells.items(), key=lambda item: _col_letter_to_index(item[0]))
    parts = [f"{col}={value}" for col, value in ordered]
    return f"row={row_num} " + " | ".join(parts)


def _format_xlsx_searchable_row(sheet_name: str, row_num: int, cells: dict[str, str]) -> str:
    ordered = sorted(cells.items(), key=lambda item: _col_letter_to_index(item[0]))
    parts = [f"{col}={value}" for col, value in ordered]
    return f"[sheet={sheet_name} row={row_num}]\n" + " | ".join(parts)


def _read_xlsx_sheet_parsed(
    archive: zipfile.ZipFile,
    sheet_name: str,
    shared_strings: list[str],
) -> tuple[list[tuple[int, dict[str, str]]], bool, int]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheet_id = None
    for sheet in workbook.findall(".//main:sheet", XLSX_NS):
        if sheet.attrib.get("name") == sheet_name:
            rel_id = sheet.attrib.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
            sheet_id = rel_id
            break
    if sheet_id is None:
        return [], False, 0

    rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = None
    for rel in rels_root:
        if rel.attrib.get("Id") == sheet_id:
            target = rel.attrib.get("Target")
            break
    if not target:
        return [], False, 0
    sheet_path = target if target.startswith("worksheets/") else f"worksheets/{target}"
    if not sheet_path.startswith("xl/"):
        sheet_path = f"xl/{sheet_path}"
    if sheet_path not in archive.namelist():
        return [], False, 0

    root = ET.fromstring(archive.read(sheet_path))
    parsed_rows: list[tuple[int, dict[str, str]]] = []
    truncated = False
    max_used_cols = 0
    for row_elem in root.findall(".//main:row", XLSX_NS):
        if len(parsed_rows) >= MAX_XLSX_ROWS_PER_SHEET:
            truncated = True
            break
        row_num = int(row_elem.attrib.get("r", str(len(parsed_rows) + 1)))
        cells: dict[str, str] = {}
        row_truncated = False
        for cell in row_elem.findall("main:c", XLSX_NS):
            ref = cell.attrib.get("r")
            if not ref:
                continue
            parsed_ref = _parse_xlsx_cell_ref(ref)
            if parsed_ref is None:
                continue
            col_letter, _ = parsed_ref
            col_index = _col_letter_to_index(col_letter)
            if col_index >= MAX_XLSX_COLUMNS:
                row_truncated = True
                truncated = True
                break
            value = _xlsx_cell_value(cell, shared_strings).strip()
            if value:
                cells[col_letter] = value
                max_used_cols = max(max_used_cols, col_index + 1)
        if row_truncated:
            break
        if cells:
            parsed_rows.append((row_num, cells))
    return parsed_rows, truncated, min(max_used_cols, MAX_XLSX_COLUMNS)


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("main:v", XLSX_NS)
    if value_node is None or value_node.text is None:
        inline = cell.find("main:is", XLSX_NS)
        if inline is not None:
            texts = [node.text or "" for node in inline.findall(".//main:t", XLSX_NS)]
            return "".join(texts)
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value_node.text)]
        except (ValueError, IndexError):
            return value_node.text
    return value_node.text
