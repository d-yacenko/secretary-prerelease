MAX_INDEXED_TEXT_CHUNKS = 64


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        if end >= text_len:
            break
        start = end - overlap
    return chunks


def select_bounded_chunk_indices(total_chunks: int, max_chunks: int) -> list[int]:
    if total_chunks <= 0 or max_chunks <= 0:
        return []
    if total_chunks <= max_chunks:
        return list(range(total_chunks))
    if max_chunks == 1:
        return [0]

    indices: list[int] = []
    seen: set[int] = set()
    for slot in range(max_chunks):
        index = round(slot * (total_chunks - 1) / (max_chunks - 1))
        if index not in seen:
            seen.add(index)
            indices.append(index)
    return indices


def select_bounded_chunks(
    chunks: list[str],
    max_chunks: int,
) -> tuple[list[str], list[int]]:
    indices = select_bounded_chunk_indices(len(chunks), max_chunks)
    return [chunks[index] for index in indices], indices


def build_indexing_metadata(
    source_chars: int,
    total_chunks: int,
    indexed_chunks: int,
) -> dict[str, int | bool]:
    return {
        "source_chars": source_chars,
        "total_chunks": total_chunks,
        "indexed_chunks": indexed_chunks,
        "indexing_truncated": indexed_chunks < total_chunks,
    }
