from sqlalchemy.exc import IntegrityError


def is_external_object_unique_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    if orig is not None:
        sqlstate = getattr(orig, "sqlstate", None)
        diag = getattr(orig, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
        if sqlstate == "23505" and constraint_name in {
            "uq_objects_provider_kind_external_id",
            "uq_objects_user_provider_kind_external_id",
        }:
            return True
    return (
        "uq_objects_provider_kind_external_id" in str(exc)
        or "uq_objects_user_provider_kind_external_id" in str(exc)
    )
