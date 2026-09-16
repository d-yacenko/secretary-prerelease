GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
PRIMARY_CALENDAR_ID = "primary"

GOOGLE_OAUTH_SCOPES = [
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    CALENDAR_READONLY_SCOPE,
    CALENDAR_EVENTS_SCOPE,
    DRIVE_READONLY_SCOPE,
]

DEFAULT_SYNC_LIMIT = 50
MAX_SYNC_LIMIT = 100
DEFAULT_SYNC_DAYS = 30
MAX_EMAIL_BODY_CHARS = 8000

DEFAULT_CALENDAR_SYNC_DAYS_BACK = 60
DEFAULT_CALENDAR_SYNC_DAYS_FORWARD = 90
DEFAULT_CALENDAR_SYNC_MAX_EVENTS = 100
MAX_CALENDAR_SYNC_EVENTS = 100
MAX_CALENDAR_SYNC_CALENDARS = 10
LIVE_CALENDAR_LOOKBACK_DAYS = 1
LIVE_CALENDAR_PAGE_SIZE = 50
LIVE_CALENDAR_MAX_PAGES_PER_CALENDAR = 8
LIVE_COVERAGE_STATE_KEY = "live_coverage"
LIVE_COVERAGE_VERSION = 1
MAX_EVENT_BODY_CHARS = 8000

OAUTH_STATE_TTL_MINUTES = 10

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

GOOGLE_DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DRIVE_PROVIDER = "google_drive"
GOOGLE_DRIVE_MAX_PARENTS = 20
DRIVE_FILE_METADATA_FIELDS = (
    "id,name,mimeType,createdTime,modifiedTime,size,md5Checksum,parents,driveId,trashed,webViewLink,version"
)

EXPLICIT_LINK_MAX_URL_CHARS = 2048

GMAIL_LIST_QUERY_EXCLUSIONS = (
    "-in:spam",
    "-in:trash",
    "-category:promotions",
    "-category:social",
    "-category:forums",
)


def build_gmail_list_query(after_date: str, before_date: str | None = None) -> str:
    parts = [f"after:{after_date}", *GMAIL_LIST_QUERY_EXCLUSIONS]
    if before_date is not None:
        parts.insert(1, f"before:{before_date}")
    return " ".join(parts)
