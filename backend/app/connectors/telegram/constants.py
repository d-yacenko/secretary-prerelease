TELEGRAM_API_HOST = "https://api.telegram.org"
TELEGRAM_PROVIDER = "telegram"
TELEGRAM_KIND = "chat_message"
TELEGRAM_ORIGIN = "source"
TELEGRAM_STATE = "observed"
MAX_TELEGRAM_MESSAGE_BODY_CHARS = 4096
MAX_TITLE_CHARS = 240
LINK_STATE_TTL_SECONDS = 600
LINK_STATE_TOKEN_LENGTH = 48
RECENT_INBOUND_WINDOW_SECONDS = 24 * 60 * 60
TELEGRAM_START_PARAM_MAX_LENGTH = 64
TELEGRAM_START_PARAM_ALLOWED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)

TELEGRAM_ALLOWED_UPDATES = (
    "message",
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
)

PRIVATE_CHAT_TYPE = "private"
DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"
