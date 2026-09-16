from app.api.schemas import ContextBuildResult


def serialize_context_for_secretary(context: ContextBuildResult) -> str:
    lines: list[str] = []
    for index, item in enumerate(context.items):
        lines.append(
            f"[{index}] object_id={item.object_id} kind={item.kind} title={item.title!r} "
            f"origin={item.origin} state={item.state} confidence={item.confidence} "
            f"representation_kind={item.representation_kind} relation_type={item.relation_type} "
            f"relation_origin={item.relation_origin} relation_state={item.relation_state} "
            f"relation_confidence={item.relation_confidence} "
            f"canonical_uri={item.canonical_uri} why_included={item.why_included!r} "
            f"content={item.content!r}"
        )
    return "\n".join(lines)
