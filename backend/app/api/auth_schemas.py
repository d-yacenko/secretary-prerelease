from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.task_completion import TASK_COMPLETION_FINITE, TASK_COMPLETION_ONGOING
from app.services.capture_service import (
    MAX_CAPTURE_CONTEXT_IDS,
    MAX_CAPTURE_DEPENDS_ON_IDS,
    MAX_CAPTURE_TEXT_CHARS,
    MAX_CAPTURE_TITLE_CHARS,
)


class UserMeOut(BaseModel):
    id: UUID
    display_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GoogleConnectionOut(BaseModel):
    connected: bool
    email: str | None = None
    gmail_available: bool = False
    calendar_available: bool = False
    drive_available: bool = False


class YandexMailConnectionOut(BaseModel):
    connected: bool
    email: str | None = None


class YandexCalendarConnectionOut(BaseModel):
    connected: bool
    email: str | None = None


class MattermostConnectionOut(BaseModel):
    account_id: UUID
    server_url: str
    remote_user_id: str
    username: str
    display_name: str | None = None
    email: str | None = None


class TeamsConnectionOut(BaseModel):
    configured: bool = False
    connected: bool = False
    reconnect_required: bool = False
    display_name: str | None = None
    upn: str | None = None
    tenant_id: str | None = None


class ConnectionsOut(BaseModel):
    google: GoogleConnectionOut
    yandex_mail: YandexMailConnectionOut
    yandex_calendar: YandexCalendarConnectionOut
    mattermost: list[MattermostConnectionOut] = Field(default_factory=list)
    teams: TeamsConnectionOut = Field(default_factory=TeamsConnectionOut)


class CaptureTaskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CAPTURE_TEXT_CHARS)
    title: str | None = Field(default=None, max_length=MAX_CAPTURE_TITLE_CHARS)
    context_object_ids: list[UUID] = Field(default_factory=list, max_length=MAX_CAPTURE_CONTEXT_IDS)
    depends_on_ids: list[UUID] = Field(default_factory=list, max_length=MAX_CAPTURE_DEPENDS_ON_IDS)
    completion_mode: Literal[TASK_COMPLETION_FINITE, TASK_COMPLETION_ONGOING] | None = None

    @model_validator(mode="after")
    def reject_null_completion_mode(self) -> Self:
        if "completion_mode" in self.model_fields_set and self.completion_mode is None:
            raise ValueError("completion_mode must be finite or ongoing")
        return self

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value

    @field_validator("title")
    @classmethod
    def title_not_blank_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be empty when provided")
        return value


class CaptureTaskOut(BaseModel):
    task_id: UUID
    context_edge_ids: list[UUID]
    dependency_edge_ids: list[UUID]


class CaptureNoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CAPTURE_TEXT_CHARS)
    title: str | None = Field(default=None, max_length=MAX_CAPTURE_TITLE_CHARS)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value

    @field_validator("title")
    @classmethod
    def title_not_blank_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be empty when provided")
        return value


class CaptureNoteOut(BaseModel):
    note_id: UUID
