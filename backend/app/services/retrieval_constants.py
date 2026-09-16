"""Constants for PostgreSQL-first local retrieval (PHASE 22.5A)."""

from datetime import timedelta

from app.content_extraction.constants import EXTRACTION_VERSION

TIME_SENSITIVE_SOURCE_KINDS = frozenset(
    {"email", "event", "chat_message"}
)

ANCHOR_KINDS = frozenset(
    {
        "event",
        "project",
        "task",
        "topic",
        "organization",
        "person",
        "goal",
        "course",
        "decision",
    }
)

RECENT_HORIZON_DAYS = 90
YEAR_HORIZON_DAYS = 365

MAX_CANDIDATE_POOL = 100
FTS_BRANCH_LIMIT = MAX_CANDIDATE_POOL // 2
TRIGRAM_BRANCH_LIMIT = MAX_CANDIDATE_POOL // 2
DEFAULT_FINAL_HITS = 5
MAX_FINAL_HITS = 20

TITLE_FTS_WEIGHT = 4.0
BODY_FTS_WEIGHT = 1.0
TRIGRAM_WEIGHT = 3.0
ANCHOR_KIND_BOOST = 0.75
RECENCY_BONUS = 0.25
RECENCY_WINDOW = timedelta(days=RECENT_HORIZON_DAYS)

STRONG_TITLE_FTS_THRESHOLD = 0.05
STRONG_TRIGRAM_THRESHOLD = 0.35
MIN_BODY_FTS_THRESHOLD = 0.02
MIN_TITLE_QUALIFY_THRESHOLD = 0.03
MIN_TRIGRAM_QUALIFY_THRESHOLD = 0.25

SHORT_EXCERPT_MAX_CHARS = 300

RETRIEVAL_REPRESENTATION_KINDS = (
    "full",
    "chunk",
    "schema",
    "sample",
    "statistics",
    "summary",
)
RETRIEVAL_REPRESENTATION_KINDS_SQL = ", ".join(
    f"'{kind}'" for kind in RETRIEVAL_REPRESENTATION_KINDS
)

REPRESENTATION_FTS_WEIGHT = 2.0

# Cloud explicit resources: Representation FTS only when ready + current revision + version.
CLOUD_CURRENT_REPRESENTATION_GATE_SQL = f"""
    o.provider IS NULL
    OR o.provider NOT IN ('google_drive', 'yandex_disk')
    OR (
        o.metadata->>'content_extraction_status' = 'ready'
        AND o.metadata->>'content_revision' IS NOT NULL
        AND o.metadata->>'content_extraction_version' = '{EXTRACTION_VERSION}'
    )
"""

# Only Representation.text from cloud explicit resources requires READY/current revision/version.
CLOUD_CURRENT_REPRESENTATION_SQL = f"""
AND (
{CLOUD_CURRENT_REPRESENTATION_GATE_SQL}
)
"""

TIME_SCOPE_AUTO = "auto"
TIME_SCOPE_RECENT = "recent"
TIME_SCOPE_ALL = "all"

# Combined weighted document — must match migration GIN index expression.
FTS_DOCUMENT_SQL = (
    "setweight(to_tsvector('simple', coalesce(o.title, '')), 'A') "
    "|| setweight(to_tsvector('simple', coalesce(o.body, '')), 'C')"
)

# Russian morphology channel — must match migration 0017 GIN index expression.
RUSSIAN_FTS_DOCUMENT_SQL = (
    "setweight(to_tsvector('russian', coalesce(o.title, '')), 'A') "
    "|| setweight(to_tsvector('russian', coalesce(o.body, '')), 'C')"
)

MAX_QUERY_ATOMS = 8
MAX_QUERY_TOKENS_SCANNED = 64
MAX_SELECTED_ATOMS = 4
MIN_ATOM_LENGTH = 3
ATOM_PROBE_LIMIT = 20

STRICT_FALLBACK_QUOTA = MAX_CANDIDATE_POOL // 2
RELAXED_FALLBACK_QUOTA = MAX_CANDIDATE_POOL // 2

RELAXED_SIMPLE_FTS_PER_ATOM = 10
RELAXED_RUSSIAN_FTS_PER_ATOM = 10
RELAXED_TRIGRAM_PER_ATOM = 10

TERM_COVERAGE_BONUS = 0.15

RETRIEVAL_MODE_STRICT = "strict"
RETRIEVAL_MODE_RELAXED = "relaxed"

GENERIC_QUERY_WORDS = frozenset(
    {
        "посмотри",
        "посмотреть",
        "найди",
        "найти",
        "создай",
        "создать",
        "собери",
        "сделать",
        "сделай",
        "было",
        "была",
        "были",
        "есть",
        "надо",
        "нужно",
        "необходимо",
        "объект",
        "объекты",
        "объекта",
        "объектам",
        "объектов",
        "задача",
        "задачу",
        "задачи",
        "активность",
        "активности",
        "курс",
        "курсы",
        "курса",
        "курсов",
        "курсами",
        "история",
        "истории",
        "данные",
        "информация",
        "что",
        "как",
        "где",
        "когда",
        "почему",
        "зачем",
        "нас",
        "нам",
        "наш",
        "наша",
        "наше",
        "связано",
        "связанное",
        "связанные",
        "связанный",
        "всем",
        "всех",
        "все",
        "вся",
        "чего",
        "этого",
        "этом",
        "этой",
        "этих",
        "у",
        "по",
        "из",
        "для",
        "при",
        "без",
        "или",
        "ещё",
        "еще",
        "find",
        "search",
        "look",
        "create",
        "make",
        "task",
        "object",
        "objects",
        "activity",
        "related",
        "something",
        "anything",
        "everything",
        "all",
        "about",
    }
)
