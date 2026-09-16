import json
import logging
from datetime import datetime

from openai import OpenAI

from app.api.schemas import ContextBuildResult
from app.llm.secretary_context import serialize_context_for_secretary
from app.llm.secretary_models import SecretaryAnalysis
from app.llm.secretary_provider import SecretaryAnalysisError

logger = logging.getLogger(__name__)


class OpenAISecretaryProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(
        self,
        trigger: str,
        context: ContextBuildResult,
        reference_datetime: datetime,
        timezone: str,
        instructions: str,
    ) -> SecretaryAnalysis:
        schema = SecretaryAnalysis.model_json_schema()
        user_input = (
            f"Trigger: {trigger}\n"
            f"Reference datetime: {reference_datetime.isoformat()}\n"
            f"Timezone: {timezone}\n\n"
            f"Context items:\n{serialize_context_for_secretary(context)}"
        )
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=user_input,
                store=False,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "secretary_analysis",
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
        except Exception as exc:
            logger.warning("secretary OpenAI call failed")
            raise SecretaryAnalysisError("secretary provider call failed") from exc

        if getattr(response, "status", None) == "incomplete":
            raise SecretaryAnalysisError("secretary provider returned incomplete response")

        output_text = _extract_output_text(response)
        if not output_text:
            raise SecretaryAnalysisError("secretary provider returned empty output")

        try:
            payload = json.loads(output_text)
            return SecretaryAnalysis.model_validate(payload)
        except Exception as exc:
            logger.warning("secretary structured output parse failed")
            raise SecretaryAnalysisError("secretary provider returned unusable structured output") from exc


def _extract_output_text(response: object) -> str | None:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    output = getattr(response, "output", None)
    if not output:
        return None
    chunks: list[str] = []
    for item in output:
        content = getattr(item, "content", None)
        if not content:
            continue
        for part in content:
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks) if chunks else None
