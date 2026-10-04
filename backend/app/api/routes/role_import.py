"""Proposal-only role import extraction. Does not write graph facts."""

from datetime import datetime
from pathlib import Path
from typing import Any
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
from app.services.person_role_import_batch_models import ApplyRoleImportBatchInput
from app.services.person_role_import_batch_service import PersonRoleImportBatchService
from app.services.person_role_import_extraction_service import (
    PersonRoleImportExtractionService,
    RoleImportProposal,
)
from app.services.person_role_import_grounding_service import (
    PersonRoleImportGroundingService,
    RoleImportGroundedProposal,
    RoleImportGroundRequest,
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


@router.post("/people/role-import/ground", response_model=RoleImportGroundedProposal)
def ground_role_import(
    body: RoleImportGroundRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> RoleImportGroundedProposal:
    try:
        service = PersonRoleImportGroundingService(
            session,
            current_user.user_id,
            Path(settings.resource_upload_root),
        )
        return service.ground(body)
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


class RoleImportActionPlanResponse(BaseModel):
    id: UUID
    status: str
    expires_at: datetime
    actions: list[dict[str, Any]]


@router.post("/people/role-import/action-plan", response_model=RoleImportActionPlanResponse)
def create_role_import_action_plan(
    body: ApplyRoleImportBatchInput,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> RoleImportActionPlanResponse:
    try:
        plan = PersonRoleImportBatchService(
            session,
            current_user.user_id,
            Path(settings.resource_upload_root),
        ).prepare_plan(body)
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
    return RoleImportActionPlanResponse(
        id=plan.id,
        status=plan.status,
        expires_at=plan.expires_at,
        actions=plan.actions,
    )
