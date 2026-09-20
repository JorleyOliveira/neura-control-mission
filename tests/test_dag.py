import pytest

from neura_marketplace.marcelo_core import MarceloOrchestrator
from neura_marketplace.models import ExecutionPlan, PlanTask


def task(task_id: str, deps=None):
    return PlanTask(
        id=task_id,
        title=task_id,
        objective=task_id,
        capability_query=task_id,
        depends_on=deps or [],
        acceptance_criteria=["done"],
        required_tools=[],
    )


def test_valid_dag():
    MarceloOrchestrator._validate_dag(ExecutionPlan(tasks=[task("research"), task("code", ["research"])]))


def test_cycle_rejected():
    with pytest.raises(ValueError):
        MarceloOrchestrator._validate_dag(ExecutionPlan(tasks=[task("a", ["b"]), task("b", ["a"])]))
