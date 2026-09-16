import math

from app.llm.embedding_text import EMBEDDING_DIMENSION

# Test stub: maps finance-related concepts to one unit vector, unrelated text to another.


def _unit_vector(seed: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    for offset in range(16):
        index = (seed + offset * 97) % EMBEDDING_DIMENSION
        vector[index] = 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


_FINANCE_VECTOR = _unit_vector(42)
_OTHER_VECTOR = _unit_vector(999)

_FINANCE_MARKERS = frozenset(
    {
        "forecast",
        "financial",
        "finance",
        "revenue",
        "quarter",
        "planning",
        "budget",
        "expense",
    }
)


class ConceptStubEmbeddingService:
    """Maps selected concept groups to fixed similar vectors for offline semantic tests."""

    def embed(self, text: str) -> list[float]:
        lower = text.lower()
        if any(marker in lower for marker in _FINANCE_MARKERS):
            return list(_FINANCE_VECTOR)
        return list(_OTHER_VECTOR)
