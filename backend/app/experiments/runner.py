"""Bounded orchestration for predefined experiment templates."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .schemas import (
    Artifact,
    ExperimentResult,
    ExperimentSpec,
    ExperimentState,
    StateTransition,
)
from .security import InputRejected, snapshot_and_validate_csv

_MAX_CAPTURED_LOG_BYTES = 64 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, media_type: str) -> Artifact:
    return Artifact(
        name=path.name,
        media_type=media_type,
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        path=path,
    )


def _read_bounded(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        data = handle.read(_MAX_CAPTURED_LOG_BYTES + 1)
    suffix = b"\n[log truncated]" if len(data) > _MAX_CAPTURED_LOG_BYTES else b""
    return (data[:_MAX_CAPTURED_LOG_BYTES] + suffix).decode("utf-8", errors="replace")


def _worker_environment(temp_dir: Path, seed: int) -> dict[str, str]:
    # Keep only variables needed to start Python on Windows/POSIX. Proxy,
    # credential, Python injection, and package-manager variables are omitted.
    keep = ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "LD_LIBRARY_PATH")
    environment = {name: os.environ[name] for name in keep if name in os.environ}
    environment.update(
        {
            "HOME": str(temp_dir),
            "USERPROFILE": str(temp_dir),
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "PYTHONHASHSEED": str(seed),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    return environment


def run_experiment(
    spec: ExperimentSpec,
    *,
    allowed_input_roots: Iterable[Path],
    artifact_root: Path,
) -> ExperimentResult:
    """Validate and synchronously execute one approved bounded experiment.

    ``spec`` must already be parsed as :class:`ExperimentSpec`; accepting no
    source-code field is part of the execution boundary.
    """

    started_at = _now()
    monotonic_start = time.monotonic()
    transitions = [StateTransition(state=ExperimentState.PENDING, at=started_at)]
    logs: list[str] = []
    artifacts: list[Artifact] = []
    input_hash: str | None = None
    environment: dict[str, str] = {}
    metrics: dict[str, float | int | str | bool | None] = {}
    error: str | None = None
    final_state = ExperimentState.FAILED

    root = artifact_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_directory = root / f"{spec.experiment_id}-{uuid.uuid4().hex}"
    run_directory.mkdir(mode=0o700)
    snapshot_path = run_directory / "input.csv"
    job_path = run_directory / "job.json"
    output_path = run_directory / "result.json"
    process_log_path = run_directory / "process.log"

    try:
        transitions.append(StateTransition(state=ExperimentState.VALIDATING, at=_now()))
        validated = snapshot_and_validate_csv(
            spec.input,
            spec.limits,
            allowed_input_roots,
            snapshot_path,
        )
        input_hash = validated.sha256
        logs.append(
            f"Validated immutable input sha256={input_hash}; "
            f"rows={validated.rows}; columns={validated.columns}; bytes={validated.size_bytes}"
        )
        job = {
            "csv_path": str(snapshot_path),
            "delimiter": spec.input.delimiter,
            "encoding": spec.input.encoding,
            "random_seed": spec.random_seed,
            "operation": spec.operation.model_dump(mode="json"),
        }
        job_path.write_text(json.dumps(job, sort_keys=True), encoding="utf-8")
        transitions.append(StateTransition(state=ExperimentState.RUNNING, at=_now()))

        worker_path = Path(__file__).with_name("worker.py").resolve()
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with process_log_path.open("wb") as process_log:
            process = subprocess.Popen(
                [sys.executable, "-I", str(worker_path), str(job_path), str(output_path)],
                stdin=subprocess.DEVNULL,
                stdout=process_log,
                stderr=subprocess.STDOUT,
                cwd=run_directory,
                env=_worker_environment(run_directory, spec.random_seed),
                shell=False,
                close_fds=True,
                creationflags=creation_flags,
            )
            try:
                process.wait(timeout=spec.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                final_state = ExperimentState.TIMED_OUT
                error = f"Experiment exceeded {spec.timeout_seconds} second timeout"

        captured = _read_bounded(process_log_path)
        if captured:
            logs.append(captured)
        if final_state != ExperimentState.TIMED_OUT:
            if not output_path.exists():
                raise RuntimeError(f"Worker exited {process.returncode} without a result")
            if output_path.stat().st_size > 2_000_000:
                raise RuntimeError("Worker result exceeded the bounded output size")
            worker_result = json.loads(output_path.read_text(encoding="utf-8"))
            environment = {
                str(key)[:128]: str(value)[:512]
                for key, value in worker_result.get("environment", {}).items()
            }
            logs.extend(str(item)[:2048] for item in worker_result.get("logs", ())[:100])
            if worker_result.get("ok") is True and process.returncode == 0:
                raw_metrics = worker_result.get("metrics", {})
                if not isinstance(raw_metrics, dict) or len(raw_metrics) > 1000:
                    raise RuntimeError("Worker returned an invalid metric set")
                metrics = {str(key)[:256]: value for key, value in raw_metrics.items()}
                final_state = ExperimentState.SUCCEEDED
            else:
                final_state = ExperimentState.FAILED
                error = str(worker_result.get("error", "Worker failed"))[:4096]
    except InputRejected as exc:
        final_state = ExperimentState.REJECTED
        error = str(exc)
        logs.append("Input rejected by bounded execution policy")
    except Exception as exc:  # noqa: BLE001 - convert worker failures into durable state
        final_state = ExperimentState.FAILED
        error = f"{type(exc).__name__}: {exc}"[:4096]
        logs.append("Experiment orchestration failed")

    finished_at = _now()
    transitions.append(StateTransition(state=final_state, at=finished_at))
    evidence = {
        "experiment_id": spec.experiment_id,
        "state": final_state.value,
        "input_sha256": input_hash,
        "approved_by_user": spec.approved_by_user,
        "operation": spec.operation.model_dump(mode="json"),
        "random_seed": spec.random_seed,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "state_history": [
            {"state": transition.state.value, "at": transition.at.isoformat()}
            for transition in transitions
        ],
        "metrics": metrics,
        "environment": environment,
        "logs": logs,
        "error": error,
    }
    evidence_path = run_directory / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, allow_nan=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for path, media_type in (
        (snapshot_path, "text/csv"),
        (evidence_path, "application/json"),
        (process_log_path, "text/plain"),
    ):
        if path.exists():
            artifacts.append(_artifact(path, media_type))
    return ExperimentResult(
        experiment_id=spec.experiment_id,
        state=final_state,
        input_sha256=input_hash,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=time.monotonic() - monotonic_start,
        metrics=metrics,
        environment=environment,
        logs=tuple(logs),
        artifacts=tuple(artifacts),
        state_history=tuple(transitions),
        error=error,
    )
