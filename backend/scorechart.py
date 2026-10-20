from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Evaluation, async_session
from auth import verify_token, User
from fastapi import Depends

router = APIRouter(prefix="/chart", tags=["chart"])


@router.get("/{system_id}")
async def get_score_chart(
    system_id: str,
    user: User = Depends(verify_token),
    limit: int = 100,
) -> dict:
    """Time-series data for the ScoreChart component."""
    async with async_session() as session:
        rows = (await session.scalars(
            select(Evaluation)
            .where(Evaluation.system_id == system_id)
            .order_by(Evaluation.timestamp.asc())
            .limit(limit)
        )).all()

        if not rows:
            raise HTTPException(404, "No evaluations for system")

        points = [
            {
                "timestamp": r.timestamp.isoformat(),
                "trust_score": r.trust_score,
                "risk_tier": r.risk_tier,
                "trusted": r.trusted,
                "uncertainty": r.uncertainty,
            }
            for r in rows
        ]

        # Summary stats for the chart header
        scores = [p["trust_score"] for p in points]
        summary = {
            "count": len(points),
            "avg": round(sum(scores) / len(scores), 2),
            "min": round(min(scores), 2),
            "max": round(max(scores), 2),
            "current": scores[-1],
            "trend": "up" if len(scores) >= 2 and scores[-1] > scores[0] else "down",
        }

        return {
            "system_id": system_id,
            "summary": summary,
            "points": points,
        }   