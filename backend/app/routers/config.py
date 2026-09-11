"""Runtime configuration endpoints.

Latency, fee rates and Kelly parameters are the knobs that decide whether a
given edge is real, so they are editable while the engine runs: change the
assumed latency and the opportunity table re-prices on the next scan.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas import ConfigUpdate
from backend.app.services.engine_runner import get_runner

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def read_config() -> dict:
    return get_runner().config_dict()


@router.patch("")
async def update_config(update: ConfigUpdate) -> dict:
    runner = get_runner()
    applied = runner.apply_settings(update.model_dump(exclude_none=True))
    return {"applied": applied, "config": runner.config_dict()}
