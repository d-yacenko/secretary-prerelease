from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.api.schemas import ContextBuildResult
from app.llm.secretary_models import SecretaryAnalysis, SecretaryProposal


class FakeSecretaryProvider:
    """Deterministic Secretary analysis for offline tests."""

    def analyze(
        self,
        trigger: str,
        context: ContextBuildResult,
        reference_datetime: datetime,
        timezone: str,
        instructions: str,
    ) -> SecretaryAnalysis:
        combined = " ".join(item.content for item in context.items).lower()
        trigger_lower = trigger.lower()
        if "meet tomorrow" not in combined and "meet tomorrow" not in trigger_lower:
            return SecretaryAnalysis(
                summary="No actionable email evidence found.",
                importance=0.1,
                urgency=0.1,
                proposals=[],
                next_action=None,
            )

        meeting_index = _find_evidence_index(context, "13:30")
        forecast_index = _find_evidence_index(context, "forecast")
        tz = ZoneInfo(timezone)
        ref = reference_datetime.astimezone(tz)
        tomorrow = ref + timedelta(days=1)
        meeting_start = datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            13,
            30,
            tzinfo=tz,
        )

        proposals = [
            SecretaryProposal(
                type="meeting",
                title="Meeting tomorrow",
                description="Possible meeting requested in source email.",
                start_at=meeting_start,
                confidence=0.84,
                evidence_item_indices=[meeting_index],
            ),
            SecretaryProposal(
                type="task",
                title="Send updated forecast",
                description="Send the updated forecast before the meeting.",
                due_at=meeting_start,
                confidence=0.79,
                evidence_item_indices=[forecast_index],
            ),
        ]
        return SecretaryAnalysis(
            importance=0.82,
            urgency=0.76,
            summary="Source email suggests a meeting tomorrow and a forecast deadline.",
            proposals=proposals,
            next_action="Review meeting and forecast proposals.",
        )


def _find_evidence_index(context: ContextBuildResult, needle: str) -> int:
    needle_lower = needle.lower()
    for index, item in enumerate(context.items):
        if needle_lower in item.content.lower():
            return index
    return 0
