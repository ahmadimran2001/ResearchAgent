"""Input validation and immutable CSV snapshot creation."""

from __future__ import annotations

import csv
import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .schemas import CsvInput, InputLimits


class InputRejected(ValueError):
    """Raised when an input violates the bounded execution policy."""


@dataclass(frozen=True)
class ValidatedInput:
    snapshot_path: Path
    sha256: str
    size_bytes: int
    rows: int
    columns: int
    headers: tuple[str, ...]


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def resolve_csv_path(path: Path, allowed_roots: Iterable[Path]) -> Path:
    if not path.is_absolute():
        raise InputRejected("CSV input path must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputRejected("CSV input does not exist or cannot be resolved") from exc
    roots = tuple(root.resolve(strict=True) for root in allowed_roots)
    if not roots:
        raise InputRejected("At least one allowed input root is required")
    if not any(_is_within(resolved, root) for root in roots):
        raise InputRejected("CSV input is outside the allowed roots")
    if resolved.suffix.lower() != ".csv" or not resolved.is_file():
        raise InputRejected("Only regular .csv files are accepted")
    return resolved


def snapshot_and_validate_csv(
    csv_input: CsvInput,
    limits: InputLimits,
    allowed_roots: Iterable[Path],
    snapshot_path: Path,
) -> ValidatedInput:
    """Copy, hash, and validate a CSV before execution.

    Templates consume only this private snapshot, preventing a source file
    replacement between validation and execution.
    """

    source = resolve_csv_path(csv_input.path, allowed_roots)
    try:
        initial_size = source.stat().st_size
    except OSError as exc:
        raise InputRejected("Cannot inspect CSV input") from exc
    if initial_size > limits.max_file_bytes:
        raise InputRejected("CSV exceeds max_file_bytes")

    digest = hashlib.sha256()
    copied = 0
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as src, snapshot_path.open("xb") as dst:
            while chunk := src.read(1024 * 1024):
                copied += len(chunk)
                if copied > limits.max_file_bytes:
                    raise InputRejected("CSV grew beyond max_file_bytes while copying")
                digest.update(chunk)
                dst.write(chunk)
    except Exception:
        snapshot_path.unlink(missing_ok=True)
        raise
    if copied != initial_size:
        snapshot_path.unlink(missing_ok=True)
        raise InputRejected("CSV changed size while being copied")

    try:
        with snapshot_path.open("r", encoding=csv_input.encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=csv_input.delimiter, strict=True)
            headers = next(reader)
            if not headers:
                raise InputRejected("CSV header is empty")
            if len(headers) > limits.max_columns:
                raise InputRejected("CSV exceeds max_columns")
            if len(set(headers)) != len(headers) or any(not h.strip() for h in headers):
                raise InputRejected("CSV headers must be non-empty and unique")
            rows = 0
            for row in reader:
                rows += 1
                if rows > limits.max_rows:
                    raise InputRejected("CSV exceeds max_rows")
                if len(row) != len(headers):
                    raise InputRejected(f"CSV row {rows + 1} has the wrong column count")
                if any(len(cell) > limits.max_cell_chars for cell in row):
                    raise InputRejected(f"CSV row {rows + 1} contains an oversized cell")
    except (UnicodeError, csv.Error) as exc:
        raise InputRejected("CSV is malformed or has an invalid encoding") from exc
    if rows == 0:
        raise InputRejected("CSV contains no data rows")

    # Make accidental mutation by predefined templates fail where supported.
    try:
        snapshot_path.chmod(0o444)
    except OSError:
        pass
    return ValidatedInput(
        snapshot_path=snapshot_path,
        sha256=digest.hexdigest(),
        size_bytes=copied,
        rows=rows,
        columns=len(headers),
        headers=tuple(headers),
    )
