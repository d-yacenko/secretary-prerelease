import re
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.llm.assistant_models import AssistantHistoryMessage, AssistantProviderResult
from app.services.user_identity_context_service import UserIdentityRuntimeFacts
from app.tools.executor import ToolExecutionResult

_OBJECT_ID_PATTERN = re.compile(r"object_id=([0-9a-fA-F-]{36})")


class FakeAssistantProvider:
  """Deterministic assistant for tests without OpenAI."""

  def __init__(self, store_false: bool = True) -> None:
      self._store_false = store_false
      self._calls: list[tuple[str, dict]] = []
      self._last_instructions: str = ""

  @property
  def last_instructions(self) -> str:
      return self._last_instructions

  @property
  def calls(self) -> list[tuple[str, dict]]:
      return list(self._calls)

  def run(
      self,
      message: str,
      history: list[AssistantHistoryMessage],
      ui_context: str,
      reference_datetime: datetime,
      timezone: str,
      tool_runner: Callable[[str, dict], ToolExecutionResult],
      identity_facts: UserIdentityRuntimeFacts | None = None,
  ) -> AssistantProviderResult:
      self._last_instructions = (
          "You are the Personal Secretary assistant. "
          f"Reference datetime: {reference_datetime.isoformat()}\n"
          f"Timezone: {timezone}"
      )
      lowered = message.lower()
      candidate_ids: list[UUID] = []
      affected_ids: list[UUID] = []

      if "project alpha" in lowered:
          result = tool_runner(
              "retrieve",
              {"query": "Project Alpha", "limit": 5},
          )
          self._calls.append(("retrieve", {"query": "Project Alpha", "limit": 5}))
          if result.success and result.output:
              for hit in result.output.get("hits", []):
                  _append_uuid(candidate_ids, hit.get("object_id"))
          if candidate_ids:
              ctx = tool_runner(
                  "get_context",
                  {"object_id": str(candidate_ids[0]), "max_chars": 2000},
              )
              self._calls.append(
                  ("get_context", {"object_id": str(candidate_ids[0]), "max_chars": 2000})
              )
              if ctx.success and ctx.output:
                  for item in ctx.output.get("items", []):
                      _append_uuid(candidate_ids, item.get("object_id"))
          answer = "Pending items for Project Alpha are listed in the referenced objects."
      elif "норникел" in lowered:
          if "курс" in lowered:
              query = "норникель"
          elif "активност" in lowered:
              query = "активность по норникелю"
          else:
              query = "норникель"
          retrieve_args = {"query": query, "limit": 5}
          if "стар" in lowered or "письм" in lowered:
              retrieve_args["time_scope"] = "all"
          result = tool_runner("retrieve", retrieve_args)
          self._calls.append(("retrieve", retrieve_args))
          if result.success and result.output:
              for hit in result.output.get("hits", []):
                  _append_uuid(candidate_ids, hit.get("object_id"))
          if candidate_ids:
              ctx = tool_runner(
                  "get_context",
                  {"object_id": str(candidate_ids[0]), "max_chars": 2000},
              )
              self._calls.append(
                  ("get_context", {"object_id": str(candidate_ids[0]), "max_chars": 2000})
              )
              if ctx.success and ctx.output:
                  for item in ctx.output.get("items", []):
                      _append_uuid(candidate_ids, item.get("object_id"))
          if "создай" in lowered or "задач" in lowered:
              task_result = tool_runner(
                  "create_task",
                  {
                      "title": "Норникель follow-up",
                      "confidence": 0.75,
                  },
              )
              self._calls.append(
                  (
                      "create_task",
                      {"title": "Норникель follow-up", "confidence": 0.75},
                  )
              )
              if task_result.success and task_result.output:
                  obj = task_result.output.get("object")
                  if obj:
                      _append_uuid(affected_ids, obj.get("id"))
                      _append_uuid(candidate_ids, obj.get("id"))
          answer = "По Норникелю найдена релевантная активность."
      elif ui_context and ("what is this" in lowered or "related to" in lowered):
          object_id = _extract_object_id(ui_context)
          args: dict = {"max_chars": 2000}
          if object_id is not None:
              args["object_id"] = object_id
          result = tool_runner("get_context", args)
          self._calls.append(("get_context", args))
          if result.success and result.output:
              for item in result.output.get("items", []):
                  _append_uuid(candidate_ids, item.get("object_id"))
          answer = "Here is what I found about the attached context."
      elif "create a task" in lowered or "prepare the course outline" in lowered:
          result = tool_runner(
              "create_task",
              {
                  "title": "Prepare course outline",
                  "confidence": 0.8,
                  "body": "Outline draft",
              },
          )
          self._calls.append(
              (
                  "create_task",
                  {
                      "title": "Prepare course outline",
                      "confidence": 0.8,
                      "body": "Outline draft",
                  },
              )
          )
          if result.success and result.output:
              obj = result.output.get("object")
              if obj:
                  _append_uuid(affected_ids, obj.get("id"))
                  _append_uuid(candidate_ids, obj.get("id"))
          answer = "I created a proposed task to prepare the course outline."
      else:
          answer = "I can help search your Secretary objects and tasks."

      return AssistantProviderResult(
          answer=answer,
          candidate_object_ids=candidate_ids,
          affected_object_ids=affected_ids,
          store_false_used=self._store_false,
      )

  def run_text_only(
      self,
      message: str,
      context: str,
  ) -> AssistantProviderResult:
      return AssistantProviderResult(
          answer="Готово. Действие выполнено.",
          candidate_object_ids=[],
          affected_object_ids=[],
          store_false_used=self._store_false,
      )


def _append_uuid(target: list[UUID], value: object) -> None:
    if not value:
        return
    try:
        parsed = UUID(str(value))
    except ValueError:
        return
    if parsed not in target:
        target.append(parsed)


def _extract_object_id(ui_context: str) -> str | None:
    match = _OBJECT_ID_PATTERN.search(ui_context)
    if match is None:
        return None
    return match.group(1)
