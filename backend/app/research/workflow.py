"""Workflow orchestration and extension points for independently built stages."""

from __future__ import annotations

import importlib
import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from backend.app.llm import OllamaClient
from backend.app.storage import ResearchRepository

STAGES = ("research", "sources", "novelty", "drafting", "experiments", "exports")


class StageResult(BaseModel):
    title: str
    summary: str
    items: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class WorkflowContext:
    project: dict[str, Any]
    stage: str
    repository: ResearchRepository
    llm: OllamaClient
    artifacts: list[dict[str, Any]] = field(default_factory=list)


StageHandler = Callable[[WorkflowContext], Awaitable[StageResult | dict[str, Any] | str]]


class WorkflowEngine:
    """Runs stages and records durable job transitions.

    Stage modules can expose ``run(context)`` or ``run_stage(context)`` in
    ``backend.app.research.<stage>``. Imports happen only when a stage runs, so
    optional integrations do not prevent application startup.
    """

    def __init__(self, repository: ResearchRepository, llm: OllamaClient):
        self.repository = repository
        self.llm = llm
        self._handlers: dict[str, StageHandler] = {}

    def register(self, stage: str, handler: StageHandler) -> None:
        if stage not in STAGES:
            raise ValueError(f"Unknown workflow stage: {stage}")
        self._handlers[stage] = handler

    def enqueue(self, project_id: int, stage: str) -> str:
        if stage not in STAGES:
            raise ValueError(f"Unknown workflow stage: {stage}")
        if not self.repository.get_project(project_id):
            raise LookupError(f"Project {project_id} does not exist")
        job_id = uuid.uuid4().hex
        self.repository.create_job(job_id, project_id, stage)
        return job_id

    def _lazy_handler(self, stage: str) -> StageHandler | None:
        if stage in self._handlers:
            return self._handlers[stage]
        try:
            module = importlib.import_module(f"backend.app.research.{stage}")
        except ModuleNotFoundError as exc:
            expected = f"backend.app.research.{stage}"
            if exc.name != expected:
                raise
            return None
        handler = getattr(module, "run_stage", None) or getattr(module, "run", None)
        if handler is None:
            return None

        async def invoke(context: WorkflowContext) -> Any:
            value = handler(context)
            return await value if inspect.isawaitable(value) else value

        self._handlers[stage] = invoke
        return invoke

    async def _default_stage(self, context: WorkflowContext) -> StageResult:
        prior = "\n\n".join(
            f"[{item['kind']}] {item['content'][:3000]}" for item in context.artifacts[:8]
        )
        prompt = (
            f"Project topic: {context.project['topic']}\n"
            f"Research question: {context.project['question']}\n"
            f"Workflow stage: {context.stage}\n"
            f"Existing artifacts:\n{prior or '(none)'}\n\n"
            "Produce a concise, evidence-conscious result. Clearly mark claims that need verification."
        )
        result = await self.llm.chat(
            [
                {
                    "role": "system",
                    "content": "You are a rigorous local research assistant. Never invent citations.",
                },
                {"role": "user", "content": prompt},
            ],
            schema=StageResult,
        )
        assert isinstance(result, StageResult)
        return result

    async def run_job(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            return
        project_id = int(job["project_id"])
        stage = str(job["stage"])
        self.repository.update_job(job_id, status="running", progress=10, message="Starting")
        self.repository.set_project_status(project_id, f"{stage}:running")
        try:
            project = self.repository.get_project(project_id)
            if project is None:
                raise LookupError(f"Project {project_id} no longer exists")
            context = WorkflowContext(
                project=project,
                stage=stage,
                repository=self.repository,
                llm=self.llm,
                artifacts=self.repository.list_artifacts(project_id),
            )
            handler = self._lazy_handler(stage)
            raw = await (handler(context) if handler else self._default_stage(context))
            if isinstance(raw, StageResult):
                result = raw.model_dump()
            elif isinstance(raw, str):
                result = {"title": stage.title(), "summary": raw, "items": []}
            else:
                result = dict(raw)
            self.repository.add_artifact(
                project_id,
                stage,
                result,
                title=str(result.get("title", stage.title())),
                metadata={"job_id": job_id},
            )
            self.repository.update_job(
                job_id, status="completed", progress=100, message="Completed"
            )
            self.repository.set_project_status(project_id, f"{stage}:completed")
        except Exception as exc:  # noqa: BLE001 - job boundary records all stage failures
            self.repository.update_job(
                job_id, status="failed", progress=100, message="Failed", error=str(exc)
            )
            self.repository.set_project_status(project_id, f"{stage}:failed")
