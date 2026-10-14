"""Utilities shared by background job handlers."""
from ..models import UsageRecord

def _usage(db, repository_id, task, result):
    db.add(UsageRecord(repository_id=repository_id, task=task, model=result.get("model", "mock"), input_tokens=result.get("input_tokens", 0), output_tokens=result.get("output_tokens", 0), estimated_cost_usd=result.get("cost", 0)))
