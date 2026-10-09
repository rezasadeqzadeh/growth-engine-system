from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..db import get_session
from ..services import instagram_stats

router = APIRouter(tags=["instagram"])


@router.get("/workspaces/{workspace_id}/instagram/stats")
async def stats(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    """Latest numbers of the connected Instagram account (members only)."""
    return await instagram_stats.latest(s, a.workspace)
