"""Bounded adaptive row sampling for CSV/Parquet dataset representations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.content_extraction.constants import (
    DATASET_STRUCTURAL_PARTS,
    MAX_REPRESENTATION_PART_BYTES,
    MAX_REPRESENTATION_PARTS,
    MAX_REPRESENTATION_TOTAL_BYTES,
)
from app.content_extraction.text_representation import (
    build_bounded_text_representations,
    cap_structural_text,
)
from app.db.models import Representation
from app.services.representation_service import (
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
    _format_sample_text,
    _format_schema_text,
)

COMPACT_SAMPLE_MAX_ROWS = 5
MAX_SAMPLED_INDEX_LIST = 64


@dataclass(frozen=True)
class IndexedRow:
    index: int
    values: dict[str, Any]


def select_distributed_row_indices(total_rows: int, target_count: int) -> list[int]:
    """Deterministically select row indices spanning the full dataset range."""
    if total_rows <= 0 or target_count <= 0:
        return []
    if target_count >= total_rows:
        return list(range(total_rows))
    if target_count == 1:
        return [total_rows // 2]
    indices: list[int] = []
    for i in range(target_count):
        idx = round(i * (total_rows - 1) / (target_count - 1))
        indices.append(int(idx))
    return sorted(set(indices))


def compact_preview_indices(total_rows: int) -> list[int]:
    """Small fixed preview indices for the compact sample representation."""
    if total_rows <= 0:
        return []
    if total_rows <= COMPACT_SAMPLE_MAX_ROWS:
        return list(range(total_rows))
    return list(range(COMPACT_SAMPLE_MAX_ROWS))


def estimate_row_bytes(fieldnames: list[str], sample_row: dict[str, Any]) -> int:
    if not fieldnames:
        return 1
    line = ",".join(str(sample_row.get(name, "")) for name in fieldnames)
    return max(1, len(line.encode("utf-8")) + 1)


def estimate_searchable_row_bytes(
    fieldnames: list[str],
    sample_row: dict[str, Any],
    row_index: int,
) -> int:
    row_line = _format_sample_text([sample_row], fieldnames).split("\n", 1)[-1]
    block = f"[row={row_index + 1}]\n{row_line}"
    return len(block.encode("utf-8")) + 1


def estimate_rows_for_budget(
    fieldnames: list[str],
    sample_row: dict[str, Any],
    byte_budget: int,
    *,
    searchable: bool = False,
    row_index: int = 0,
) -> int:
    if not fieldnames or byte_budget <= 0:
        return 0
    if searchable:
        row_bytes = estimate_searchable_row_bytes(fieldnames, sample_row, row_index)
        return max(1, byte_budget // row_bytes)
    header_bytes = len(("sample\n" + ",".join(fieldnames)).encode("utf-8")) + 1
    row_bytes = estimate_row_bytes(fieldnames, sample_row)
    available = byte_budget - header_bytes
    if available <= 0:
        return 0
    return max(1, available // row_bytes)


def estimate_structural_bytes(fieldnames: list[str], stats_lines: list[str]) -> int:
    schema_text = _format_schema_text(fieldnames, {name: "string" for name in fieldnames})
    stats_text = "\n".join(stats_lines)
    return len(schema_text.encode("utf-8")) + len(stats_text.encode("utf-8"))


def fit_compact_sample_pairs(
    pairs: list[IndexedRow],
    fieldnames: list[str],
    total_rows: int,
) -> tuple[list[IndexedRow], str, bool]:
    """Shrink loaded preview pairs until compact sample fits one part."""
    current = list(pairs)
    while current:
        sample_text = _format_sample_text([row.values for row in current], fieldnames)
        if len(sample_text.encode("utf-8")) <= MAX_REPRESENTATION_PART_BYTES:
            return current, sample_text, False
        if len(current) <= 1:
            clipped, _ = cap_structural_text(sample_text)
            return current[:1], clipped, True
        current = current[: max(1, len(current) // 2)]
    return [], "sample\n(empty)", True


def plan_searchable_indices(
    *,
    total_rows: int,
    fieldnames: list[str],
    estimate_row: dict[str, Any],
    structural_bytes: int,
    compact_sample_bytes: int,
) -> tuple[list[int], str, bool]:
    remaining_bytes = max(
        0,
        MAX_REPRESENTATION_TOTAL_BYTES - structural_bytes - compact_sample_bytes,
    )
    remaining_parts = max(0, MAX_REPRESENTATION_PARTS - DATASET_STRUCTURAL_PARTS)
    byte_budget = min(
        remaining_bytes,
        remaining_parts * MAX_REPRESENTATION_PART_BYTES,
    )
    max_rows = estimate_rows_for_budget(
        fieldnames,
        estimate_row,
        byte_budget,
        searchable=True,
        row_index=total_rows // 2 if total_rows else 0,
    )
    if total_rows <= max_rows:
        return list(range(total_rows)), "full", False
    indices = select_distributed_row_indices(total_rows, max_rows)
    return indices, "distributed", len(indices) < total_rows


def fit_searchable_pairs_to_budget(
    pairs: list[IndexedRow],
    fieldnames: list[str],
    byte_budget: int,
    max_parts: int,
) -> list[IndexedRow]:
    """Select a distributed subset of loaded pairs that fits searchable budget."""
    if not pairs or byte_budget <= 0 or max_parts <= 0:
        return []
    eligible = [
        pair
        for pair in pairs
        if searchable_row_block_bytes(pair, fieldnames) <= MAX_REPRESENTATION_PART_BYTES
    ]
    if not eligible:
        return []
    part_budget = min(byte_budget, max_parts * MAX_REPRESENTATION_PART_BYTES)
    low, high = 1, len(eligible)
    best: list[IndexedRow] = []
    while low <= high:
        mid = (low + high) // 2
        positions = select_distributed_row_indices(len(eligible), mid)
        trial_pairs = [eligible[position] for position in positions]
        text = format_searchable_dataset_rows(trial_pairs, fieldnames)
        if len(text.encode("utf-8")) <= part_budget:
            best = trial_pairs
            low = mid + 1
        else:
            high = mid - 1
    return best


def format_searchable_dataset_rows(pairs: list[IndexedRow], fieldnames: list[str]) -> str:
    lines: list[str] = []
    for pair in pairs:
        lines.append(f"[row={pair.index + 1}]")
        lines.append(_format_sample_text([pair.values], fieldnames).split("\n", 1)[-1])
    return "\n".join(lines)


def searchable_row_block_bytes(pair: IndexedRow, fieldnames: list[str]) -> int:
    row_line = _format_sample_text([pair.values], fieldnames).split("\n", 1)[-1]
    block = f"[row={pair.index + 1}]\n{row_line}"
    return len(block.encode("utf-8"))


def parse_persisted_searchable_row_indices(reps: list[Representation]) -> set[int]:
    indices: set[int] = set()
    for rep in reps:
        for line in rep.text.splitlines():
            if line.startswith("[row=") and line.endswith("]"):
                indices.add(int(line[5:-1]) - 1)
    return indices


def build_dataset_sample_metadata(
    *,
    total_rows: int,
    represented_rows: int,
    sampling_mode: str,
    sampling_truncated: bool,
    sampled_indices: list[int],
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "dataset_row_count": total_rows,
        "dataset_rows_represented": represented_rows,
        "dataset_sampling_mode": sampling_mode,
        "dataset_sampling_truncated": sampling_truncated,
    }
    if sampled_indices and len(sampled_indices) <= MAX_SAMPLED_INDEX_LIST:
        meta["sampled_row_indices"] = sampled_indices
    return meta


def build_indexed_dataset_representations(
    object_id,
    *,
    fieldnames: list[str],
    column_types: dict[str, str],
    stats_meta: dict[str, Any],
    stats_lines: list[str],
    total_rows: int,
    indexed_rows: list[IndexedRow],
    compact_indices: list[int],
    searchable_indices: list[int],
    sampling_mode: str,
    sampling_truncated: bool,
) -> tuple[list[Representation], dict[str, Any]]:
    rows_by_index = {row.index: row for row in indexed_rows}
    compact_pairs = [rows_by_index[i] for i in compact_indices if i in rows_by_index]
    searchable_pairs = sorted(
        [rows_by_index[i] for i in searchable_indices if i in rows_by_index],
        key=lambda pair: pair.index,
    )

    compact_pairs, compact_text, compact_truncated = fit_compact_sample_pairs(
        compact_pairs,
        fieldnames,
        total_rows,
    )

    structural_bytes = estimate_structural_bytes(fieldnames, stats_lines)
    compact_bytes = len(compact_text.encode("utf-8"))
    remaining_bytes = max(
        0,
        MAX_REPRESENTATION_TOTAL_BYTES - structural_bytes - compact_bytes,
    )
    remaining_parts = max(0, MAX_REPRESENTATION_PARTS - DATASET_STRUCTURAL_PARTS)
    searchable_byte_budget = min(
        remaining_bytes,
        remaining_parts * MAX_REPRESENTATION_PART_BYTES,
    )
    fitted_searchable = fit_searchable_pairs_to_budget(
        searchable_pairs,
        fieldnames,
        searchable_byte_budget,
        remaining_parts,
    )
    searchable_text = format_searchable_dataset_rows(fitted_searchable, fieldnames)

    compact_persisted_indices = {pair.index for pair in compact_pairs}

    schema_text, schema_truncated = cap_structural_text(
        _format_schema_text(fieldnames, column_types)
    )
    stats_text, stats_truncated = cap_structural_text("\n".join(stats_lines))

    structural_reps = [
        Representation(
            object_id=object_id,
            kind=KIND_SCHEMA,
            text=schema_text,
            metadata_={
                "columns": [{"name": name, "type": column_types[name]} for name in fieldnames]
            },
        ),
        Representation(
            object_id=object_id,
            kind=KIND_SAMPLE,
            text=compact_text,
            metadata_={
                "row_count_in_sample": len(compact_pairs),
                "compact_preview": True,
            },
        ),
        Representation(
            object_id=object_id,
            kind=KIND_STATISTICS,
            text=stats_text,
            metadata_=stats_meta,
        ),
    ]

    searchable_reps, searchable_truncated = build_bounded_text_representations(
        object_id,
        searchable_text,
        remaining_parts,
        None,
    )
    searchable_persisted_indices = parse_persisted_searchable_row_indices(searchable_reps)
    represented_indices = sorted(compact_persisted_indices | searchable_persisted_indices)
    represented_count = len(represented_indices)
    final_sampling_mode = "full" if represented_count == total_rows else "distributed"
    final_truncated = (
        represented_count < total_rows
        or compact_truncated
        or schema_truncated
        or stats_truncated
        or searchable_truncated
    )

    dataset_meta = build_dataset_sample_metadata(
        total_rows=total_rows,
        represented_rows=represented_count,
        sampling_mode=final_sampling_mode,
        sampling_truncated=final_truncated,
        sampled_indices=represented_indices,
    )
    for rep in searchable_reps:
        rep.metadata_ = {**dataset_meta, **(rep.metadata_ or {})}

    return structural_reps + searchable_reps, dataset_meta
