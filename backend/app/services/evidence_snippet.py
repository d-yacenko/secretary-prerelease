"""Deterministic query-centered evidence snippets for retrieval and context."""

from __future__ import annotations

import re

from app.services.retrieval_constants import MAX_QUERY_ATOMS, MAX_QUERY_TOKENS_SCANNED

MARKER_RE = re.compile(r"\[(?:slide|page)\s+\d+\]", re.IGNORECASE)
TOKEN_RE = re.compile(r"\w+", re.UNICODE)
GENERIC_QUERY_PREFIX_RE = re.compile(
    r"^(?:найди(?:\s+мне)?|найти(?:\s+мне)?|посмотри|find(?:\s+me)?|search(?:\s+for)?)\s+",
    re.IGNORECASE,
)
MIN_TOKEN_LENGTH = 3
LOCAL_WINDOW_CHARS = 240

CONTEXT_EVIDENCE_MAX_CHARS = 1200

_REPRESENTATION_KIND_PRIORITY = {
    "chunk": 0,
    "full": 1,
    "summary": 2,
    "sample": 3,
    "schema": 4,
    "statistics": 5,
}


def normalize_lexical_text(text: str) -> str:
    return " ".join(text.lower().split())


def lexical_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in normalize_lexical_text(text).split():
        cleaned = token.strip(".,;:!?\"'«»()[]{}")
        if len(cleaned) >= MIN_TOKEN_LENGTH:
            tokens.add(cleaned)
    return tokens


def ordered_query_tokens(query: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    scanned = 0
    for token in TOKEN_RE.findall(query.lower()):
        scanned += 1
        if scanned > MAX_QUERY_TOKENS_SCANNED:
            break
        if len(token) < MIN_TOKEN_LENGTH:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= MAX_QUERY_ATOMS:
            break
    return tokens


def bounded_query_tokens(query: str, atoms: list[str] | None = None) -> list[str]:
    tokens = ordered_query_tokens(query)
    if not atoms or len(tokens) >= MAX_QUERY_ATOMS:
        return tokens
    seen = set(tokens)
    for atom in atoms:
        normalized = atom.strip().lower()
        if len(normalized) < MIN_TOKEN_LENGTH:
            continue
        if normalized in seen:
            continue
        tokens.append(normalized)
        seen.add(normalized)
        if len(tokens) >= MAX_QUERY_ATOMS:
            break
    return tokens


def find_exact_phrase_span(text: str, phrase: str) -> tuple[int, int] | None:
    candidate = phrase.strip()
    if not candidate or not text:
        return None

    pos = text.find(candidate)
    if pos >= 0:
        return pos, pos + len(candidate)

    text_lower = text.lower()
    phrase_lower = candidate.lower()
    pos = text_lower.find(phrase_lower)
    if pos >= 0:
        return pos, pos + len(phrase_lower)

    words = normalize_lexical_text(candidate).split()
    if len(words) < 2:
        return None
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words), re.IGNORECASE)
    match = pattern.search(text)
    if match is None:
        return None
    return match.start(), match.end()


def exact_match_score(text: str, query: str) -> float:
    if not query.strip() or not text:
        return 0.0
    if find_exact_phrase_span(text, query) is not None:
        return 1.0
    stripped = GENERIC_QUERY_PREFIX_RE.sub("", query.strip()).strip()
    if stripped and stripped != query.strip():
        if find_exact_phrase_span(text, stripped) is not None:
            return 1.0
    return 0.0


def lexical_match_score(text: str, query: str) -> tuple[float, float]:
    exact = exact_match_score(text, query)
    query_tokens = lexical_tokens(query)
    if not query_tokens:
        return exact, 0.0
    text_tokens = lexical_tokens(text)
    coverage = len(query_tokens & text_tokens) / len(query_tokens)
    return exact, coverage


def find_atom_evidence_span(text: str, atoms: list[str]) -> tuple[int, int] | None:
    if not atoms or not text:
        return None
    text_lower = text.lower()
    best: tuple[int, int, int] | None = None
    for atom in atoms:
        atom_lower = atom.lower().strip()
        if len(atom_lower) < MIN_TOKEN_LENGTH:
            continue
        start = 0
        while True:
            pos = text_lower.find(atom_lower, start)
            if pos < 0:
                break
            span = (pos, pos + len(atom_lower), len(atom_lower))
            if best is None or span[2] > best[2]:
                best = span
            start = pos + 1
    if best is None:
        return None
    return best[0], best[1]


def find_token_evidence_anchor(text: str, tokens: list[str]) -> int | None:
    if not tokens or not text:
        return None
    text_lower = text.lower()
    token_set = {token.lower() for token in tokens if len(token) >= MIN_TOKEN_LENGTH}
    if not token_set:
        return None

    occurrences: list[tuple[int, int]] = []
    for token in sorted(token_set, key=len, reverse=True):
        start = 0
        while True:
            pos = text_lower.find(token, start)
            if pos < 0:
                break
            occurrences.append((pos, pos + len(token)))
            start = pos + 1
    if not occurrences:
        return None

    best_center: int | None = None
    best_hits = -1
    best_longest = -1
    for pos, end in occurrences:
        center = (pos + end) // 2
        window_start = max(0, center - LOCAL_WINDOW_CHARS)
        window_end = min(len(text_lower), center + LOCAL_WINDOW_CHARS)
        window = text_lower[window_start:window_end]
        hits = sum(1 for token in token_set if token in window)
        longest = max((len(token) for token in token_set if token in window), default=0)
        if (hits, longest, -center) > (best_hits, best_longest, -(best_center or 0)):
            best_hits = hits
            best_longest = longest
            best_center = center
    return best_center


def find_evidence_anchor(
    text: str,
    query: str,
    atoms: list[str] | None = None,
) -> int | None:
    if not text:
        return None

    for phrase in (query, GENERIC_QUERY_PREFIX_RE.sub("", query.strip()).strip()):
        if not phrase:
            continue
        span = find_exact_phrase_span(text, phrase)
        if span is not None:
            return (span[0] + span[1]) // 2

    if atoms:
        span = find_atom_evidence_span(text, atoms)
        if span is not None:
            return (span[0] + span[1]) // 2

    tokens = bounded_query_tokens(query, atoms)
    return find_token_evidence_anchor(text, tokens)


def _nearest_marker_start(text: str, before_pos: int) -> int | None:
    best: int | None = None
    for match in MARKER_RE.finditer(text):
        if match.start() <= before_pos:
            best = match.start()
    return best


def build_query_centered_snippet(
    text: str,
    query: str,
    max_chars: int,
    atoms: list[str] | None = None,
) -> str:
    source = text.strip()
    if not source or max_chars <= 0:
        return ""
    if len(source) <= max_chars:
        return source

    anchor = find_evidence_anchor(source, query, atoms)
    if anchor is None:
        return source[: max_chars - 1].rstrip() + "…"

    marker_start = _nearest_marker_start(source, anchor)
    start = max(0, anchor - max_chars // 2)
    if marker_start is not None and marker_start < start:
        start = marker_start
    end = min(len(source), start + max_chars)

    prefix_ellipsis = start > 0
    suffix_ellipsis = end < len(source)
    budget = max_chars - int(prefix_ellipsis) - int(suffix_ellipsis)
    if budget <= 0:
        return "…"[:max_chars]

    rel_anchor = anchor - start
    left = min(rel_anchor, budget // 2)
    slice_start = start + rel_anchor - left
    slice_end = slice_start + budget
    if slice_end > len(source):
        slice_end = len(source)
        slice_start = max(0, slice_end - budget)
    snippet = source[slice_start:slice_end]
    prefix_ellipsis = slice_start > 0
    suffix_ellipsis = slice_end < len(source)

    result = snippet
    if prefix_ellipsis:
        result = "…" + result
    if suffix_ellipsis:
        result = result + "…"
    if len(result) > max_chars:
        if prefix_ellipsis and suffix_ellipsis:
            inner = max_chars - 2
            result = "…" + snippet[:inner].rstrip() + "…"
        elif prefix_ellipsis:
            result = "…" + snippet[: max_chars - 1].rstrip()
        elif suffix_ellipsis:
            result = snippet[: max_chars - 1].rstrip() + "…"
        else:
            result = snippet[:max_chars]
    return result


def representation_evidence_score(
    text: str,
    query: str,
    atoms: list[str] | None = None,
) -> tuple[float, float, int]:
    exact, coverage = lexical_match_score(text, query)
    atom_hits = 0
    if atoms:
        text_lower = text.lower()
        for atom in atoms:
            normalized = atom.lower().strip()
            if len(normalized) >= MIN_TOKEN_LENGTH and normalized in text_lower:
                atom_hits += 1
    return exact, coverage, atom_hits


def representation_evidence_rank_key(
    *,
    text: str,
    query: str,
    atoms: list[str] | None,
    kind: str,
    part_index: int | None,
    rep_id: str,
) -> tuple[float, float, int, int, int, str]:
    exact, coverage, atom_hits = representation_evidence_score(text, query, atoms)
    kind_priority = _REPRESENTATION_KIND_PRIORITY.get(kind, 99)
    if part_index is not None:
        part_rank = -part_index
    else:
        part_rank = -(10**9)
    return (
        exact,
        coverage,
        atom_hits,
        -kind_priority,
        part_rank,
        rep_id,
    )
