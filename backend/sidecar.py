"""PyInstaller-compatible command-line entry point for the Tauri sidecar."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

import uvicorn


def _startup_marker(message: str) -> None:
    path = os.environ.get("RESEARCH_AGENT_STARTUP_LOG")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def main() -> None:
    _startup_marker("sidecar-main")
    parser = argparse.ArgumentParser(description="Research Agent desktop sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("The desktop sidecar may only bind to loopback")
    if os.environ.get("RESEARCH_AGENT_DESKTOP") == "1" and not os.environ.get(
        "RESEARCH_AGENT_IPC_TOKEN"
    ):
        parser.error("RESEARCH_AGENT_IPC_TOKEN is required in desktop mode")
    _startup_marker("import-app")
    from backend.app.main import app

    _startup_marker("import-app-complete")
    _startup_marker("uvicorn-run")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_config=None,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
