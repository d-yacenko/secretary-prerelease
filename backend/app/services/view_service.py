import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Object, View, ViewItem
from app.services.errors import NotFoundError, ValidationError


class ViewService:
    def __init__(self, session: Session, user_id: uuid.UUID) -> None:
        self._session = session
        self._user_id = user_id

    def create_view(
        self,
        name: str,
        view_type: str,
        root_object_id: uuid.UUID | None = None,
        settings: dict[str, Any] | None = None,
    ) -> View:
        if root_object_id is not None:
            self._require_owned_object(root_object_id)
        view = View(
            user_id=self._user_id,
            name=name,
            view_type=view_type,
            root_object_id=root_object_id,
            settings_=settings or {},
        )
        self._session.add(view)
        self._session.flush()
        return view

    def create_view_item(
        self,
        view_id: uuid.UUID,
        object_id: uuid.UUID | None = None,
        visual_id: uuid.UUID | None = None,
        x: float | None = None,
        y: float | None = None,
        width: float | None = None,
        height: float | None = None,
        collapsed: bool = False,
        settings: dict[str, Any] | None = None,
    ) -> ViewItem:
        if object_id is None and visual_id is None:
            raise ValidationError("view item requires object_id or visual_id")
        if object_id is not None and visual_id is not None:
            raise ValidationError("view item cannot have both object_id and visual_id")

        view = self._session.scalar(
            select(View).where(View.id == view_id, View.user_id == self._user_id)
        )
        if view is None:
            raise NotFoundError("view", view_id)
        if object_id is not None:
            self._require_owned_object(object_id)

        item = ViewItem(
            view_id=view_id,
            object_id=object_id,
            visual_id=visual_id,
            x=x,
            y=y,
            width=width,
            height=height,
            collapsed=collapsed,
            settings_=settings or {},
        )
        self._session.add(item)
        self._session.flush()
        return item

    def update_item_position(self, item_id: uuid.UUID, x: float, y: float) -> ViewItem:
        item = self._session.get(ViewItem, item_id)
        if item is None:
            raise NotFoundError("view_item", item_id)
        view = self._session.scalar(
            select(View).where(View.id == item.view_id, View.user_id == self._user_id)
        )
        if view is None:
            raise NotFoundError("view_item", item_id)
        item.x = x
        item.y = y
        self._session.flush()
        return item

    def delete_view(self, view_id: uuid.UUID) -> None:
        view = self._session.scalar(
            select(View).where(View.id == view_id, View.user_id == self._user_id)
        )
        if view is None:
            raise NotFoundError("view", view_id)
        self._session.delete(view)
        self._session.flush()
        self._session.expire_all()

    def list_view_items(self, view_id: uuid.UUID) -> list[ViewItem]:
        view = self._session.scalar(
            select(View).where(View.id == view_id, View.user_id == self._user_id)
        )
        if view is None:
            raise NotFoundError("view", view_id)
        return list(
            self._session.scalars(select(ViewItem).where(ViewItem.view_id == view_id)).all()
        )

    def _require_owned_object(self, object_id: uuid.UUID) -> None:
        owned = self._session.scalar(
            select(Object.id).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if owned is None:
            raise NotFoundError("object", object_id)
