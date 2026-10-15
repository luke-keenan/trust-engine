from datetime import datetime, timezone
from uuid import uuid4

from models import Evaluation


def record(system_id: str, signals: dict, results: list[dict], tier: str,
           trust_score: float, uncertainty: float, trusted: bool) -> Evaluation:
    return Evaluation(
        id=str(uuid4()), system_id=system_id, timestamp=datetime.now(timezone.utc),
        signals_json=signals, policy_results_json=results, risk_tier=tier,
        trust_score=trust_score, uncertainty=uncertainty, trusted=trusted,
    )
