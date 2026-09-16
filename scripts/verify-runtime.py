"""Optional local end-to-end check against Ollama."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import main


def stream(client: TestClient, conversation_id: str, **payload: object) -> list[dict]:
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conversation_id, **payload},
    ) as response:
        response.raise_for_status()
        return [json.loads(line) for line in response.iter_lines() if line]


def main_cli() -> int:
    with tempfile.TemporaryDirectory(prefix="research-agent-verify-") as temporary:
        root = Path(temporary)
        main.settings.database_path = root / "history.sqlite3"
        main.settings.literature_cache_path = root / "cache"
        main.settings.literature_per_source = 1
        main.settings.literature_max_results = 3

        with TestClient(main.app) as client:
            phi = client.post(
                "/api/chat/conversations", json={"model_id": "phi4-mini"}
            ).json()
            phi_events = stream(
                client,
                phi["id"],
                content="Reply with the single word READY.",
                model_id="phi4-mini",
            )
            restored = client.get(
                f"/api/chat/conversations/{phi['id']}/messages"
            ).json()

        summary = {
            "phi_completed": any(e["type"] == "message.completed" for e in phi_events),
            "restored_messages": len(restored),
        }
        print(json.dumps(summary, indent=2))
        if not (summary["phi_completed"] and summary["restored_messages"] >= 2):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
