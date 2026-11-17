"""ML model endpoints #79-85 (Table 7.10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query

from app.api.deps import DB, Pagination, Principal, require_permission
from app.core.responses import ok, paginated
from app.models.ml_model import MLModel, Prediction
from app.repositories.ml_repository import MLModelRepository, PredictionRepository
from app.schemas.ml import ModelDeploy, ModelOut, ModelRegister, PredictRequest
from app.services.ml_service import MLService
from app.workers.dispatch import dispatch

router = APIRouter(prefix="/ml", tags=["Machine Learning"])


@router.get("/models", dependencies=[require_permission("ml:read")], summary="#79 List deployed models")
async def list_models(db: DB, name: str | None = None, stage: str | None = None) -> dict:
    f = []
    if name:
        f.append(MLModel.name == name)
    if stage:
        f.append(MLModel.stage == stage)
    return ok([ModelOut.model_validate(m) for m in await MLModelRepository(db).all(*f)])


@router.post("/models/register", status_code=201, summary="#80 Register model version")
async def register(body: ModelRegister, db: DB, principal: Principal = require_permission("ml:register")) -> dict:
    return ok(ModelOut.model_validate(await MLService(db).register(body, principal)))


@router.post("/models/train", status_code=202, summary="Trigger retraining (Celery ML worker / Airflow)")
async def train(name: str = Query(...), principal: Principal = require_permission("ml:register")) -> dict:
    return ok({"task_id": await dispatch("retrain", name), "model": name, "requested_by": principal.name})


@router.post("/models/{model_id}/deploy", summary="#81 Deploy model version",
             description="Stage transition. Promotion to `production` enforces the two-person rule: the approver "
                         "must be different from the user who registered/trained the model.")
async def deploy(model_id: uuid.UUID, body: ModelDeploy, db: DB,
                 principal: Principal = require_permission("ml:deploy")) -> dict:
    return ok(ModelOut.model_validate(await MLService(db).deploy(model_id, body.stage, principal, body.note)))


@router.post("/models/{model_id}/predict", summary="#82 Run inference")
async def predict(model_id: uuid.UUID, body: PredictRequest, db: DB,
                  principal: Principal = require_permission("ml:predict")) -> dict:
    return ok(await MLService(db).predict(model_id, body, principal))


@router.get("/models/{model_id}/performance", dependencies=[require_permission("ml:performance")],
            summary="#83 Get model metrics")
async def performance(model_id: uuid.UUID, db: DB) -> dict:
    return ok(await MLService(db).performance(model_id))


@router.get("/predictions", dependencies=[require_permission("ml:read")], summary="#84 Query prediction history")
async def predictions(db: DB, p: Pagination, model_id: uuid.UUID | None = None, asset_id: uuid.UUID | None = None,
                      days: int = Query(7, ge=1, le=90), include_shadow: bool = False) -> dict:
    f = [Prediction.time >= datetime.now(UTC) - timedelta(days=days)]
    if model_id:
        f.append(Prediction.model_id == model_id)
    if asset_id:
        f.append(Prediction.asset_id == asset_id)
    if not include_shadow:
        f.append(Prediction.is_shadow.is_(False))
    items, total = await PredictionRepository(db).list(*f, page=p.page, per_page=p.per_page)
    rows = [{"time": r.time.isoformat(), "id": str(r.id), "model_id": str(r.model_id),
             "asset_id": str(r.asset_id) if r.asset_id else None, "value": r.value, "label": r.label,
             "confidence": r.confidence, "horizon": r.horizon, "is_shadow": r.is_shadow, "explanation": r.explanation}
            for r in items]
    return paginated(rows, p.page, p.per_page, total)


@router.get("/drift/report", dependencies=[require_permission("ml:performance")], summary="#85 Get drift detection report")
async def drift(db: DB, model: str | None = None) -> dict:
    return ok(await MLService(db).drift(model))
