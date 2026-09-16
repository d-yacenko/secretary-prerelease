from uuid import UUID

# Single bootstrap owner for the operational single-user deployment.
# Created by migration 0010; resolved via CurrentUserContext until real auth exists.
BOOTSTRAP_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
BOOTSTRAP_DISPLAY_NAME = "Owner"
