"""Opt-in frozen-startup diagnostics used only when an environment path is set."""

from __future__ import annotations

import faulthandler
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = os.environ.get("RESEARCH_AGENT_STARTUP_LOG")
if path:
    log = Path(path)
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = log.open("a", encoding="utf-8")
    stream.write(
        f"{datetime.now(timezone.utc).isoformat()} runtime-hook "
        f"frozen={getattr(sys, 'frozen', False)} meipass={getattr(sys, '_MEIPASS', None)}\n"
    )
    stream.flush()
    faulthandler.enable(stream)
    faulthandler.dump_traceback_later(60, repeat=True, file=stream)

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event == "import" and args:
            stream.write(f"import {args[0]}\n")
            stream.flush()

    sys.addaudithook(audit)
