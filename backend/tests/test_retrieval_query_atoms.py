"""Unit tests for retrieval query atom extraction."""

from app.services.retrieval_query_atoms import extract_query_atoms

LIVE_NL_PHRASE = (
    "Посмотри по всем объектам. У нас есть что-то связанное "
    "с курсами по норникелю? и собери из этого задачу"
)


def test_extract_query_atoms_live_phrase_preserves_nornickel() -> None:
    atoms = extract_query_atoms(LIVE_NL_PHRASE)
    assert "норникелю" in atoms


def test_extract_query_atoms_generic_filler_before_distinctive() -> None:
    filler = (
        "посмотри найди создай объект задача активность сделать курсы по "
        "всем объектам нас есть что связанное курсами"
    )
    query = f"{filler} норникелю"
    atoms = extract_query_atoms(query)
    assert "норникелю" in atoms


def test_extract_query_atoms_generic_only_query_still_works() -> None:
    atoms = extract_query_atoms("курсы по обучению")
    assert atoms
    assert "обучению" in atoms or "курсы" in atoms
