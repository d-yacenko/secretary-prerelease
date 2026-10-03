"""Proposal-only role import extraction. Does not write graph facts."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.assistant_error_responses import (
    build_assistant_error_detail,
    build_openai_daily_budget_error_detail,
)
from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.llm.openai_role_import_provider import OpenAIRoleImportExtractionProvider
from app.services.errors import NotFoundError, ValidationError
from app.services.openai_daily_budget import OpenAIDailyBudgetExhaustedError
from app.services.person_role_import_extraction_service import (
    PersonRoleImportExtractionService,
    RoleImportProposal,
)
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError

router = APIRouter()


class RoleImportExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: UUID


@router.post("/people/role-import/extract", response_model=RoleImportProposal)
def extract_role_import(
    body: RoleImportExtractRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> RoleImportProposal:
    try:
        provider = OpenAIRoleImportExtractionProvider.for_user(session, current_user.user_id)
        service = PersonRoleImportExtractionService(
            session,
            current_user.user_id,
            provider,
            Path(settings.resource_upload_root),
        )
        return service.extract(body.source_object_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    except OpenAIDailyBudgetExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=build_openai_daily_budget_error_detail(exc),
        ) from exc
    except UserOpenAICredentialConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=build_assistant_error_detail(exc),
        ) from exc
