"""Private subprocess worker containing the complete executable allow-list."""

from __future__ import annotations

import csv
import importlib.metadata
import json
import math
import platform
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _deny_external_actions(event: str, args: tuple[Any, ...]) -> None:
    """Defense in depth: templates may not open networks or child processes."""

    denied = (
        "socket.connect",
        "socket.connect_ex",
        "socket.bind",
        "socket.getaddrinfo",
        "socket.gethostby",
        "socket.sendto",
        "socket.sendmsg",
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "os.startfile",
    )
    if event.startswith(denied):
        raise PermissionError(f"Worker policy denied audit event: {event}")


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _read_rows(job: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    with Path(job["csv_path"]).open(
        "r", encoding=job["encoding"], newline=""
    ) as handle:
        reader = csv.DictReader(handle, delimiter=job["delimiter"], strict=True)
        return list(reader.fieldnames or ()), list(reader)


def _numeric(values: list[str], column: str) -> list[float]:
    result: list[float] = []
    for index, raw in enumerate(values, start=2):
        if raw.strip() == "":
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{column!r} has non-numeric data at row {index}") from exc
        if not math.isfinite(value):
            raise ValueError(f"{column!r} has a non-finite value at row {index}")
        result.append(value)
    return result


def _descriptive(
    headers: list[str], rows: list[dict[str, str]], operation: dict[str, Any]
) -> dict[str, Any]:
    selected = operation.get("columns") or headers
    missing = sorted(set(selected) - set(headers))
    if missing:
        raise ValueError(f"Unknown columns: {missing}")
    metrics: dict[str, Any] = {"dataset.row_count": len(rows), "dataset.column_count": len(headers)}
    for column in selected:
        values = [row[column] for row in rows]
        present = [value for value in values if value.strip()]
        metrics[f"{column}.count"] = len(present)
        metrics[f"{column}.missing"] = len(values) - len(present)
        try:
            numbers = _numeric(values, column)
            if numbers:
                metrics[f"{column}.mean"] = statistics.fmean(numbers)
                metrics[f"{column}.min"] = min(numbers)
                metrics[f"{column}.max"] = max(numbers)
                metrics[f"{column}.stddev"] = (
                    statistics.stdev(numbers) if len(numbers) > 1 else 0.0
                )
                metrics[f"{column}.median"] = statistics.median(numbers)
                continue
        except ValueError:
            pass
        if operation["include_categorical"]:
            counts = Counter(present)
            metrics[f"{column}.unique"] = len(counts)
            if counts:
                mode, count = counts.most_common(1)[0]
                metrics[f"{column}.mode"] = mode[:512]
                metrics[f"{column}.mode_count"] = count
    return metrics


def _statistical(
    headers: list[str], rows: list[dict[str, str]], operation: dict[str, Any]
) -> dict[str, Any]:
    try:
        from scipy import stats
    except ImportError as exc:
        raise RuntimeError("scipy is required for statistical_test") from exc

    test = operation["test"]
    alpha = operation["alpha"]
    value_column = operation.get("value_column")
    second = operation.get("second_value_column")
    group_column = operation.get("group_column")
    required = {name for name in (value_column, second, group_column) if name}
    if not required.issubset(headers):
        raise ValueError(f"Unknown columns: {sorted(required - set(headers))}")

    if test == "chi_square":
        if not value_column or not group_column:
            raise ValueError("chi_square requires value_column and group_column")
        left_values = sorted({row[group_column] for row in rows})
        right_values = sorted({row[value_column] for row in rows})
        if len(left_values) < 2 or len(right_values) < 2:
            raise ValueError("chi_square requires at least two categories per variable")
        table = [
            [
                sum(
                    row[group_column] == left and row[value_column] == right
                    for row in rows
                )
                for right in right_values
            ]
            for left in left_values
        ]
        statistic, pvalue, dof, _ = stats.chi2_contingency(table)
        sample_size = len(rows)
        effect = math.sqrt(float(statistic) / (sample_size * min(len(left_values) - 1, len(right_values) - 1)))
        name = "chi_square"
        extra = {"degrees_of_freedom": int(dof), "cramers_v": effect}
    elif test == "paired_t_test":
        if not value_column or not second:
            raise ValueError("paired_t_test requires value_column and second_value_column")
        pairs = [
            (a, b)
            for row in rows
            if (a := row[value_column].strip()) and (b := row[second].strip())
        ]
        first = _numeric([a for a, _ in pairs], value_column)
        other = _numeric([b for _, b in pairs], second)
        if len(first) < 2:
            raise ValueError("paired_t_test requires at least two complete pairs")
        result = stats.ttest_rel(first, other)
        statistic, pvalue, sample_size = result.statistic, result.pvalue, len(first)
        name, extra = "paired_t_test", {"mean_difference": statistics.fmean(a - b for a, b in zip(first, other))}
    else:
        if not value_column or not group_column or operation.get("group_a") is None or operation.get("group_b") is None:
            raise ValueError(f"{test} requires value_column, group_column, group_a, and group_b")
        group_a = operation["group_a"]
        group_b = operation["group_b"]
        if group_a == group_b:
            raise ValueError("group_a and group_b must differ")
        first = _numeric(
            [row[value_column] for row in rows if row[group_column] == group_a],
            value_column,
        )
        other = _numeric(
            [row[value_column] for row in rows if row[group_column] == group_b],
            value_column,
        )
        if len(first) < 2 or len(other) < 2:
            raise ValueError("Each selected group requires at least two numeric values")
        if test == "independent_t_test":
            result = stats.ttest_ind(first, other, equal_var=False)
            pooled = math.sqrt((statistics.variance(first) + statistics.variance(other)) / 2)
            extra = {"cohens_d": (statistics.fmean(first) - statistics.fmean(other)) / pooled if pooled else 0.0}
        elif test == "mann_whitney_u":
            result = stats.mannwhitneyu(first, other, alternative="two-sided")
            extra = {"rank_biserial": 1.0 - (2.0 * float(result.statistic)) / (len(first) * len(other))}
        else:
            raise ValueError("Unsupported statistical test")
        statistic, pvalue = result.statistic, result.pvalue
        sample_size = len(first) + len(other)
        name = test
        extra.update({"group_a_n": len(first), "group_b_n": len(other)})

    return {
        "test.name": name,
        "test.statistic": float(statistic),
        "test.p_value": float(pvalue),
        "test.alpha": alpha,
        "test.reject_null": bool(pvalue < alpha),
        "test.sample_size": sample_size,
        **{f"test.{key}": value for key, value in extra.items()},
    }


def _benchmark(
    headers: list[str], rows: list[dict[str, str]], operation: dict[str, Any], seed: int
) -> dict[str, Any]:
    try:
        import numpy as np
        import pandas as pd
        import sklearn
        from sklearn.compose import ColumnTransformer
        from sklearn.dummy import DummyClassifier, DummyRegressor
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score
        from sklearn.model_selection import cross_val_score, train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
    except ImportError as exc:
        raise RuntimeError("pandas, numpy, and scikit-learn are required for sklearn_benchmark") from exc

    features = operation["feature_columns"]
    target = operation["target_column"]
    requested = set(features) | {target}
    if not requested.issubset(headers):
        raise ValueError(f"Unknown columns: {sorted(requested - set(headers))}")
    if target in features:
        raise ValueError("target_column cannot also be a feature")
    frame = pd.DataFrame(rows)[features + [target]].replace("", np.nan).dropna(subset=[target])
    if len(frame) < 20:
        raise ValueError("sklearn_benchmark requires at least 20 rows with a target")
    X, y = frame[features], frame[target]
    numeric_columns: list[str] = []
    categorical_columns: list[str] = []
    for column in features:
        converted = pd.to_numeric(X[column], errors="coerce")
        if converted.notna().sum() == X[column].notna().sum():
            X[column] = converted
            numeric_columns.append(column)
        else:
            categorical_columns.append(column)
    transformers: list[tuple[str, Any, list[str]]] = []
    if numeric_columns:
        transformers.append(("numeric", SimpleImputer(strategy="median"), numeric_columns))
    if categorical_columns:
        categorical = Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore", max_categories=50)),
        ])
        transformers.append(("categorical", categorical, categorical_columns))
    preprocess = ColumnTransformer(transformers)
    if operation["task"] == "classification":
        if y.nunique() < 2 or y.nunique() > 100:
            raise ValueError("Classification target must have between 2 and 100 classes")
        stratify = y if y.value_counts().min() >= 2 else None
        baseline, candidate = DummyClassifier(strategy="most_frequent"), RandomForestClassifier(
            n_estimators=50, max_depth=8, random_state=seed, n_jobs=1
        )
        scoring = "accuracy"
    else:
        y = pd.to_numeric(y, errors="raise")
        stratify = None
        baseline, candidate = DummyRegressor(strategy="mean"), RandomForestRegressor(
            n_estimators=50, max_depth=8, random_state=seed, n_jobs=1
        )
        scoring = "r2"
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=operation["test_fraction"], random_state=seed, stratify=stratify
    )
    metrics: dict[str, Any] = {
        "benchmark.train_rows": len(X_train),
        "benchmark.test_rows": len(X_test),
        "benchmark.feature_count": len(features),
    }
    for name, estimator in (("baseline", baseline), ("random_forest", candidate)):
        pipeline = Pipeline([("preprocess", preprocess), ("model", estimator)])
        scores = cross_val_score(
            pipeline, X_train, y_train, cv=operation["folds"], scoring=scoring, n_jobs=1
        )
        pipeline.fit(X_train, y_train)
        prediction = pipeline.predict(X_test)
        metrics[f"{name}.cv_{scoring}_mean"] = float(scores.mean())
        metrics[f"{name}.cv_{scoring}_std"] = float(scores.std())
        if operation["task"] == "classification":
            metrics[f"{name}.test_accuracy"] = float(accuracy_score(y_test, prediction))
            metrics[f"{name}.test_f1_macro"] = float(f1_score(y_test, prediction, average="macro"))
        else:
            metrics[f"{name}.test_r2"] = float(r2_score(y_test, prediction))
            metrics[f"{name}.test_mae"] = float(mean_absolute_error(y_test, prediction))
    metrics["environment.scikit_learn"] = sklearn.__version__
    return metrics


def main() -> int:
    job_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    random.seed(job["random_seed"])
    sys.addaudithook(_deny_external_actions)
    started = time.monotonic()
    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "pydantic": _version("pydantic"),
        "numpy": _version("numpy"),
        "pandas": _version("pandas"),
        "scipy": _version("scipy"),
        "scikit-learn": _version("scikit-learn"),
    }
    try:
        headers, rows = _read_rows(job)
        operation = job["operation"]
        dispatch = {
            "descriptive_statistics": lambda: _descriptive(headers, rows, operation),
            "statistical_test": lambda: _statistical(headers, rows, operation),
            "sklearn_benchmark": lambda: _benchmark(
                headers, rows, operation, job["random_seed"]
            ),
        }
        if operation["template"] not in dispatch:
            raise ValueError("Template is not allow-listed")
        metrics = dispatch[operation["template"]]()
        result = {
            "ok": True,
            "metrics": metrics,
            "environment": environment,
            "logs": [
                f"Loaded {len(rows)} rows and {len(headers)} columns",
                f"Executed predefined template {operation['template']}",
                f"Worker duration {time.monotonic() - started:.6f}s",
            ],
        }
    except Exception as exc:  # noqa: BLE001 - isolated worker must serialize every failure
        result = {
            "ok": False,
            "metrics": {},
            "environment": environment,
            "logs": [f"Worker failed: {type(exc).__name__}"],
            "error": f"{type(exc).__name__}: {exc}",
        }
    output_path.write_text(
        json.dumps(result, allow_nan=False, sort_keys=True), encoding="utf-8"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
