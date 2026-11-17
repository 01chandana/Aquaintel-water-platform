"""Generic async repository (Ch. 9.5): composable filter, sort and pagination utilities."""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import NotFoundError
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]
    default_order: Sequence[Any] = ()
    sortable: dict[str, Any] = {}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: uuid.UUID | str) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def get_or_404(self, id_: uuid.UUID | str, label: str | None = None) -> ModelT:
        obj = await self.get(id_)
        if obj is None:
            raise NotFoundError(f"{label or self.model.__name__} {id_} not found")
        return obj

    def _apply_sort(self, stmt: Select[Any], sort: str | None) -> Select[Any]:
        if sort:
            desc = sort.startswith("-")
            col = self.sortable.get(sort.lstrip("-"))
            if col is not None:
                return stmt.order_by(col.desc() if desc else col.asc())
        return stmt.order_by(*self.default_order) if self.default_order else stmt

    async def paginate(
        self,
        stmt: Select[Any],
        page: int = 1,
        per_page: int = 50,
        sort: str | None = None,
    ) -> tuple[list[Any], int]:
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = self._apply_sort(stmt, sort).offset((page - 1) * per_page).limit(per_page)
        rows = (await self.session.execute(stmt)).unique().scalars().all()
        return list(rows), total

    async def list(
        self,
        *filters: ColumnElement[bool],
        page: int = 1,
        per_page: int = 50,
        sort: str | None = None,
    ) -> tuple[list[ModelT], int]:
        return await self.paginate(select(self.model).where(*filters), page, per_page, sort)

    async def all(self, *filters: ColumnElement[bool]) -> builtins.list[ModelT]:
        stmt = self._apply_sort(select(self.model).where(*filters), None)
        return list((await self.session.execute(stmt)).unique().scalars().all())

    async def create(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    async def count(self, *filters: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(self.model).where(*filters)
        return int((await self.session.execute(stmt)).scalar_one())
