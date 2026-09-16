from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from .runner import run_experiment
from .schemas import ExperimentSpec, ExperimentState
from .security import InputRejected, resolve_csv_path


def _spec(csv_path: Path) -> ExperimentSpec:
    return ExperimentSpec.model_validate_json(
        json.dumps(
            {
                "experiment_id": "bounded-test",
                "approved_by_user": True,
                "input": {"path": str(csv_path)},
                "operation": {
                    "template": "descriptive_statistics",
                    "columns": ["value", "category"],
                    "include_categorical": True,
                },
                "timeout_seconds": 20,
                "random_seed": 123,
            }
        )
    )


def test_descriptive_experiment_returns_hashed_evidence(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_text("value,category\n1,a\n2,a\n3,b\n", encoding="utf-8")

    result = run_experiment(
        _spec(source), allowed_input_roots=[tmp_path], artifact_root=tmp_path / "artifacts"
    )

    assert result.state is ExperimentState.SUCCEEDED
    assert result.metrics["value.mean"] == 2.0
    assert result.metrics["category.mode"] == "a"
    assert result.input_sha256
    assert [transition.state for transition in result.state_history] == [
        ExperimentState.PENDING,
        ExperimentState.VALIDATING,
        ExperimentState.RUNNING,
        ExperimentState.SUCCEEDED,
    ]
    assert {artifact.name for artifact in result.artifacts} >= {
        "input.csv",
        "evidence.json",
        "process.log",
    }


def test_unapproved_and_unknown_templates_are_schema_errors(tmp_path: Path) -> None:
    data = _spec(tmp_path / "input.csv").model_dump(mode="python")
    data["approved_by_user"] = False
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(data)
    data["approved_by_user"] = True
    data["operation"] = {"template": "python", "code": "print('no')"}
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(data)


def test_path_outside_allowed_root_is_rejected(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(InputRejected):
        resolve_csv_path(outside, [allowed])
