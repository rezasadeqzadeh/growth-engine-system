"""Plan caps per workspace per month (videos processed, AI calls)."""

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select

from .. import db
from ..errors import AppError
from ..models import UsageCounter, Workspace

PLANS_FILE = Path(__file__).resolve().parent.parent / "data" / "plans.json"


@lru_cache
def plans() -> dict[str, dict]:
    data = json.loads(PLANS_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def current_month() -> str:
    return db.utcnow().strftime("%Y-%m")


def limit_for(plan: str, metric: str) -> int:
    return int(plans().get(plan, plans()["free"])[metric])


def used(workspace_id: str, metric: str) -> int:
    with db.session_scope() as s:
        row = s.scalar(select(UsageCounter).where(
            UsageCounter.workspace_id == workspace_id, UsageCounter.month == current_month(),
            UsageCounter.metric == metric))
        return row.value if row else 0


def consume(workspace_id: str, metric: str, amount: int = 1) -> None:
    """Count one unit, or refuse with `plan_limit_reached` when the cap is hit."""
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace_id)
        if ws is None:
            raise AppError("workspace_not_found", "Workspace not found", 404)
        row = s.scalar(select(UsageCounter).where(
            UsageCounter.workspace_id == workspace_id, UsageCounter.month == current_month(),
            UsageCounter.metric == metric).with_for_update())
        if row is None:
            row = UsageCounter(workspace_id=workspace_id, month=current_month(), metric=metric, value=0)
            s.add(row)
        if row.value + amount > limit_for(ws.plan, metric):
            raise AppError("plan_limit_reached", f"Monthly {metric} limit of the plan is reached", 402)
        row.value += amount
