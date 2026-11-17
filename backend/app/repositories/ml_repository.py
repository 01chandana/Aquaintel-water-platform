from __future__ import annotations

from sqlalchemy import select

from app.models.ml_model import MLModel, Prediction
from app.repositories.base import BaseRepository


class MLModelRepository(BaseRepository[MLModel]):
    model = MLModel
    default_order = (MLModel.name.asc(), MLModel.created_at.desc())

    async def in_stage(self, name: str, stage: str) -> MLModel | None:
        stmt = select(MLModel).where(MLModel.name == name, MLModel.stage == stage).order_by(MLModel.created_at.desc())
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()


class PredictionRepository(BaseRepository[Prediction]):
    model = Prediction
    default_order = (Prediction.time.desc(),)
