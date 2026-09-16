import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.schemas import ObjectCreate
from app.db.models import Object, ViewItem
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.view_service import ViewService
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _task(title: str) -> ObjectCreate:
    return ObjectCreate(kind="task", title=title, origin="system")


def test_object_in_two_views_with_different_coordinates(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    views = ViewService(db_session, BOOTSTRAP_USER_ID)

    obj = graph.create_object(_task("Shared task"))

    view_a = views.create_view("Map A", "freeform")
    view_b = views.create_view("Map B", "tree")

    item_a = views.create_view_item(view_a.id, object_id=obj.id, x=10.0, y=20.0)
    item_b = views.create_view_item(view_b.id, object_id=obj.id, x=100.0, y=200.0)

    assert item_a.x == 10.0
    assert item_b.x == 100.0


def test_changing_coordinates_in_one_view_does_not_affect_other(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    views = ViewService(db_session, BOOTSTRAP_USER_ID)

    obj = graph.create_object(_task("Shared task"))

    view_a = views.create_view("Map A", "freeform")
    view_b = views.create_view("Map B", "freeform")

    item_a = views.create_view_item(view_a.id, object_id=obj.id, x=1.0, y=2.0)
    item_b = views.create_view_item(view_b.id, object_id=obj.id, x=50.0, y=60.0)

    views.update_item_position(item_a.id, x=99.0, y=88.0)
    db_session.refresh(item_b)

    assert item_a.x == 99.0
    assert item_a.y == 88.0
    assert item_b.x == 50.0
    assert item_b.y == 60.0


def test_deleting_view_deletes_view_items(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    views = ViewService(db_session, BOOTSTRAP_USER_ID)

    obj = graph.create_object(ObjectCreate(kind="note", title="Note", origin="system"))

    view = views.create_view("Temporary", "context")
    item = views.create_view_item(view.id, object_id=obj.id, x=5.0, y=6.0)
    item_id = item.id

    views.delete_view(view.id)

    remaining = db_session.get(ViewItem, item_id)
    assert remaining is None


def test_visual_only_item_without_object(db_session) -> None:
    views = ViewService(db_session, BOOTSTRAP_USER_ID)
    view = views.create_view("Annotations", "freeform")
    visual_id = uuid.uuid4()

    item = views.create_view_item(view.id, visual_id=visual_id, x=3.0, y=4.0)

    assert item.object_id is None
    assert item.visual_id == visual_id


def test_invalid_view_item_without_object_or_visual_rejected(db_session) -> None:
    views = ViewService(db_session, BOOTSTRAP_USER_ID)
    view = views.create_view("Empty items", "freeform")

    with pytest.raises(ValidationError):
        views.create_view_item(view.id)

    with pytest.raises(IntegrityError):
        db_session.add(
            ViewItem(
                view_id=view.id,
                object_id=None,
                visual_id=None,
                collapsed=False,
            )
        )
        db_session.flush()


def test_view_item_cannot_have_both_object_and_visual(db_session) -> None:
    views = ViewService(db_session, BOOTSTRAP_USER_ID)
    view = views.create_view("Both ids", "freeform")
    object_id = uuid.uuid4()
    visual_id = uuid.uuid4()

    with pytest.raises(ValidationError):
        views.create_view_item(view.id, object_id=object_id, visual_id=visual_id)

    with pytest.raises(IntegrityError):
        db_session.add(
            ViewItem(
                view_id=view.id,
                object_id=object_id,
                visual_id=visual_id,
                collapsed=False,
            )
        )
        db_session.flush()


def test_object_deletion_not_blocked_by_view_placement(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    views = ViewService(db_session, BOOTSTRAP_USER_ID)

    obj = graph.create_object(_task("Placed task"))
    view = views.create_view("Board", "freeform")
    item = views.create_view_item(view.id, object_id=obj.id, x=1.0, y=2.0)
    item_id = item.id

    graph.delete_object(obj.id)

    assert db_session.get(Object, obj.id) is None
    assert db_session.get(ViewItem, item_id) is None

    count = db_session.scalar(select(func.count()).select_from(ViewItem))
    assert count == 0
