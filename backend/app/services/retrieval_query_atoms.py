import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.retrieval_constants import (
    ATOM_PROBE_LIMIT,
    CLOUD_CURRENT_REPRESENTATION_GATE_SQL,
    CLOUD_CURRENT_REPRESENTATION_SQL,
    FTS_DOCUMENT_SQL,
    GENERIC_QUERY_WORDS,
    MAX_QUERY_ATOMS,
    MAX_QUERY_TOKENS_SCANNED,
    MAX_SELECTED_ATOMS,
    MIN_ATOM_LENGTH,
    RETRIEVAL_REPRESENTATION_KINDS_SQL,
    RUSSIAN_FTS_DOCUMENT_SQL,
)

_BASE_WHERE = """
    o.user_id = :user_id
    AND o.deleted_at IS NULL
    AND (o.status IS NULL OR o.status != 'deleted')
    AND o.state != 'rejected'
"""

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_PROBE_RUSSIAN_SQL = f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {{filter_suffix}}
      AND ({RUSSIAN_FTS_DOCUMENT_SQL}) @@ plainto_tsquery('russian', :atom)
    LIMIT :probe_limit
"""

_PROBE_SIMPLE_SQL = f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {{filter_suffix}}
      AND ({FTS_DOCUMENT_SQL}) @@ plainto_tsquery('simple', :atom)
    LIMIT :probe_limit
"""

_PROBE_TRIGRAM_SQL = f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {{filter_suffix}}
      AND o.title % :atom
    LIMIT :probe_limit
"""

_PROBE_REP_SIMPLE_SQL = f"""
    SELECT DISTINCT o.id
    FROM representations r
    INNER JOIN objects o ON o.id = r.object_id
    WHERE {_BASE_WHERE}
      {{filter_suffix}}
      {CLOUD_CURRENT_REPRESENTATION_SQL}
      AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
      AND to_tsvector('simple', coalesce(r.text, ''))
          @@ plainto_tsquery('simple', :atom)
    LIMIT :probe_limit
"""

_PROBE_REP_RUSSIAN_SQL = f"""
    SELECT DISTINCT o.id
    FROM representations r
    INNER JOIN objects o ON o.id = r.object_id
    WHERE {_BASE_WHERE}
      {{filter_suffix}}
      {CLOUD_CURRENT_REPRESENTATION_SQL}
      AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
      AND to_tsvector('russian', coalesce(r.text, ''))
          @@ plainto_tsquery('russian', :atom)
    LIMIT :probe_limit
"""


def extract_query_atoms(query: str) -> list[str]:
    seen: set[str] = set()
    non_generic: list[str] = []
    generic: list[str] = []
    scanned = 0

    for token in _TOKEN_RE.findall(query.lower()):
        scanned += 1
        if scanned > MAX_QUERY_TOKENS_SCANNED:
            break
        if len(token) < MIN_ATOM_LENGTH:
            continue
        if token in seen:
            continue
        seen.add(token)
        if token in GENERIC_QUERY_WORDS:
            generic.append(token)
        else:
            non_generic.append(token)

    atoms: list[str] = []
    for token in non_generic:
        if len(atoms) >= MAX_QUERY_ATOMS:
            break
        atoms.append(token)
    if len(atoms) < MAX_QUERY_ATOMS:
        for token in generic:
            if len(atoms) >= MAX_QUERY_ATOMS:
                break
            atoms.append(token)
    return atoms


def filter_non_generic_atoms(atoms: list[str]) -> list[str]:
    return [atom for atom in atoms if atom not in GENERIC_QUERY_WORDS]


def is_cyrillic_atom(atom: str) -> bool:
    return any("\u0400" <= char <= "\u04ff" for char in atom)


def is_technical_atom(atom: str) -> bool:
    return any(char.isascii() and (char.isalpha() or char.isdigit()) for char in atom)


def probe_atom_selectivity(
    session: Session,
    user_id: UUID,
    atom: str,
    filter_suffix: str,
    params: dict,
) -> int:
    probe_limit = ATOM_PROBE_LIMIT + 1
    base_params = {
        **params,
        "user_id": user_id,
        "atom": atom,
        "probe_limit": probe_limit,
    }
    counts: list[int] = []

    if is_cyrillic_atom(atom):
        russian_ids = session.execute(
            text(_PROBE_RUSSIAN_SQL.format(filter_suffix=filter_suffix)),
            base_params,
        ).scalars()
        counts.append(len(list(russian_ids)))
        rep_russian_ids = session.execute(
            text(_PROBE_REP_RUSSIAN_SQL.format(filter_suffix=filter_suffix)),
            base_params,
        ).scalars()
        counts.append(len(list(rep_russian_ids)))

    if is_technical_atom(atom) or not is_cyrillic_atom(atom):
        simple_ids = session.execute(
            text(_PROBE_SIMPLE_SQL.format(filter_suffix=filter_suffix)),
            base_params,
        ).scalars()
        counts.append(len(list(simple_ids)))
        rep_simple_ids = session.execute(
            text(_PROBE_REP_SIMPLE_SQL.format(filter_suffix=filter_suffix)),
            base_params,
        ).scalars()
        counts.append(len(list(rep_simple_ids)))

    trigram_ids = session.execute(
        text(_PROBE_TRIGRAM_SQL.format(filter_suffix=filter_suffix)),
        base_params,
    ).scalars()
    counts.append(len(list(trigram_ids)))

    if not counts:
        return 0
    return min(max(counts), ATOM_PROBE_LIMIT)


def select_selective_atoms(
    session: Session,
    user_id: UUID,
    atoms: list[str],
    filter_suffix: str,
    params: dict,
) -> list[str]:
    candidates = filter_non_generic_atoms(atoms)
    if not candidates:
        candidates = list(atoms)
    if not candidates:
        return []

    scored: list[tuple[int, str]] = []
    for atom in candidates:
        selectivity = probe_atom_selectivity(
            session,
            user_id,
            atom,
            filter_suffix,
            params,
        )
        if selectivity > 0:
            scored.append((selectivity, atom))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [atom for _, atom in scored[:MAX_SELECTED_ATOMS]]
