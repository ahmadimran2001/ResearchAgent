"""Strict public schemas for bounded, user-approved experiments."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ExperimentState(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class InputLimits(StrictModel):
    max_file_bytes: PositiveInt = Field(default=10_000_000, le=100_000_000)
    max_rows: PositiveInt = Field(default=100_000, le=1_000_000)
    max_columns: PositiveInt = Field(default=200, le=2_000)
    max_cell_chars: PositiveInt = Field(default=32_768, le=1_000_000)


class CsvInput(StrictModel):
    path: Path
    delimiter: Literal[",", ";", "\t", "|"] = ","
    encoding: Literal["utf-8", "utf-8-sig"] = "utf-8"


class DescriptiveStatistics(StrictModel):
    template: Literal["descriptive_statistics"]
    columns: tuple[str, ...] | None = None
    include_categorical: bool = True


class StatisticalTest(StrictModel):
    template: Literal["statistical_test"]
    test: Literal["independent_t_test", "paired_t_test", "mann_whitney_u", "chi_square"]
    value_column: str | None = None
    group_column: str | None = None
    group_a: str | None = None
    group_b: str | None = None
    second_value_column: str | None = None
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def require_test_fields(self) -> StatisticalTest:
        if self.test == "chi_square":
            required = (self.value_column, self.group_column)
        elif self.test == "paired_t_test":
            required = (self.value_column, self.second_value_column)
        else:
            required = (
                self.value_column,
                self.group_column,
                self.group_a,
                self.group_b,
            )
        if any(value is None for value in required):
            raise ValueError(f"Missing required fields for {self.test}")
        if self.group_a is not None and self.group_a == self.group_b:
            raise ValueError("group_a and group_b must differ")
        return self


class SklearnBenchmark(StrictModel):
    template: Literal["sklearn_benchmark"]
    task: Literal["classification", "regression"]
    target_column: str
    feature_columns: tuple[str, ...]
    test_fraction: float = Field(default=0.2, ge=0.1, le=0.4)
    folds: int = Field(default=3, ge=2, le=5)

    @field_validator("feature_columns")
    @classmethod
    def bounded_features(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > 50:
            raise ValueError("feature_columns must contain between 1 and 50 names")
        if len(set(value)) != len(value):
            raise ValueError("feature_columns must be unique")
        return value


TemplateSpec = Annotated[
    DescriptiveStatistics | StatisticalTest | SklearnBenchmark,
    Field(discriminator="template"),
]


class ExperimentSpec(StrictModel):
    """An experiment is executable only after explicit user approval."""

    experiment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    approved_by_user: Literal[True]
    input: CsvInput
    operation: TemplateSpec
    limits: InputLimits = Field(default_factory=InputLimits)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    random_seed: int = Field(default=17, ge=0, le=2_147_483_647)


MetricValue = float | int | str | bool | None


class Artifact(StrictModel):
    name: str
    media_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    path: Path


class StateTransition(StrictModel):
    state: ExperimentState
    at: datetime


class ExperimentResult(StrictModel):
    experiment_id: str
    state: ExperimentState
    input_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(ge=0)
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    logs: tuple[str, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    state_history: tuple[StateTransition, ...]
    error: str | None = None
