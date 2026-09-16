from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main


def configure_paths(tmp_path: Path) -> None:
    main.settings.database_path = tmp_path / "research.sqlite3"
    main.settings.upload_path = tmp_path / "uploads"
    main.settings.experiment_artifact_path = tmp_path / "experiments"
    main.settings.export_path = tmp_path / "exports"
    main.settings.literature_cache_path = tmp_path / "cache"
    main.settings.training_records_path = tmp_path / "training" / "feedback.jsonl"
    main.settings.feedback_source_salt = "test-only-private-salt"


def test_project_dataset_and_approved_experiment_api(tmp_path: Path) -> None:
    configure_paths(tmp_path)
    with TestClient(main.app) as client:
        created = client.post(
            "/api/projects",
            json={"topic": "Reproducible models", "question": "What is measurable?"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        upload = client.post(
            f"/api/projects/{project_id}/datasets",
            files={"dataset": ("observations.csv", b"group,value\nA,1\nB,2\n", "text/csv")},
        )
        assert upload.status_code == 201
        dataset_id = upload.json()["artifact_id"]

        refused = client.post(
            f"/api/projects/{project_id}/experiments/run",
            json={
                "dataset_artifact_id": dataset_id,
                "experiment_id": "summary",
                "approved_by_user": False,
                "operation": {"template": "descriptive_statistics"},
            },
        )
        assert refused.status_code == 409

        executed = client.post(
            f"/api/projects/{project_id}/experiments/run",
            json={
                "dataset_artifact_id": dataset_id,
                "experiment_id": "summary",
                "approved_by_user": True,
                "operation": {
                    "template": "descriptive_statistics",
                    "columns": None,
                    "include_categorical": True,
                },
            },
        )
        assert executed.status_code == 201, executed.text
        assert executed.json()["state"] == "succeeded"
        assert executed.json()["metrics"]["dataset.row_count"] == 2


def test_upload_rejects_non_csv(tmp_path: Path) -> None:
    configure_paths(tmp_path)
    with TestClient(main.app) as client:
        project_id = client.post(
            "/api/projects", json={"topic": "Safe uploads", "question": ""}
        ).json()["id"]
        response = client.post(
            f"/api/projects/{project_id}/datasets",
            files={"dataset": ("payload.py", b"print('unsafe')", "text/x-python")},
        )
        assert response.status_code == 415

