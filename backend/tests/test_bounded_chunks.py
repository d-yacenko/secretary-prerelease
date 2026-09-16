
from app.services.bounded_chunks import (
    MAX_INDEXED_TEXT_CHUNKS,
    select_bounded_chunk_indices,
    select_bounded_chunks,
)


def test_select_bounded_chunk_indices_includes_first_and_last() -> None:
    indices = select_bounded_chunk_indices(200, MAX_INDEXED_TEXT_CHUNKS)
    assert indices[0] == 0
    assert indices[-1] == 199
    assert len(indices) == MAX_INDEXED_TEXT_CHUNKS


def test_select_bounded_chunks_spreads_across_document() -> None:
    chunks = [f"chunk-{index}" for index in range(120)]
    selected, indices = select_bounded_chunks(chunks, 8)
    assert len(selected) == 8
    assert selected[0] == "chunk-0"
    assert selected[-1] == "chunk-119"
    assert len(set(indices)) == 8
