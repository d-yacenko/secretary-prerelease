from datetime import datetime
from typing import Protocol

from app.api.schemas import ContextBuildResult
from app.llm.secretary_models import SecretaryAnalysis


class SecretaryAnalysisError(Exception):
    pass


class SecretaryConfigurationError(SecretaryAnalysisError):
    pass


class SecretaryProvider(Protocol):
    def analyze(
        self,
        trigger: str,
        context: ContextBuildResult,
        reference_datetime: datetime,
        timezone: str,
        instructions: str,
    ) -> SecretaryAnalysis: ...
