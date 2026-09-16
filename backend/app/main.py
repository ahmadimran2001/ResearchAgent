"""FastAPI entry point for the local Research Agent UI and API."""

from __future__ import annotations

import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from backend.app.chat import ChatService, ResearchToolRouter
from backend.app.config import get_settings
from backend.app.experiments import CsvInput, ExperimentSpec, InputLimits, run_experiment
from backend.app.llm import ModelRegistry, OllamaClient
from backend.app.research.drafting import (
    DraftDocument,
    export_bibtex,
    export_docx,
    export_markdown,
)
from backend.app.research.stages import HANDLERS
from backend.app.research.workflow import STAGES, WorkflowEngine
from backend.app.storage import ChatRepository, Database, ResearchRepository

settings = get_settings()
templates = Jinja2Templates(directory=str(settings.frontend_dir / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = Database(settings.resolved_database_path)
    database.initialize()
    repository = ResearchRepository(database)
    for path in (
        settings.resolved_upload_path,
        settings.resolved_experiment_artifact_path,
        settings.resolved_export_path,
        settings.resolved_training_path,
    ):
        path.mkdir(parents=True, exist_ok=True)
    app.state.repository = repository
    ollama = OllamaClient(settings)
    engine = WorkflowEngine(repository, ollama)
    for stage, handler in HANDLERS.items():
        engine.register(stage, handler)
    app.state.workflow = engine
    chat_repository = ChatRepository(database)
    app.state.chat_repository = chat_repository
    registry = ModelRegistry(settings, ollama=ollama)
    app.state.chat = ChatService(
        chat_repository,
        registry,
        ResearchToolRouter(settings),
    )
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",
        "http://tauri.localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["x-run-id"],
)
app.mount("/static", StaticFiles(directory=str(settings.frontend_dir / "static")), name="static")


@app.middleware("http")
async def authenticate_loopback(request: Request, call_next):
    """Require the random desktop token whenever the sidecar was launched with one."""
    expected = os.environ.get("RESEARCH_AGENT_IPC_TOKEN")
    if expected and request.method != "OPTIONS" and request.url.path.startswith("/api/"):
        supplied = request.headers.get("authorization", "")
        prefix = "Bearer "
        if not supplied.startswith(prefix) or not secrets.compare_digest(
            supplied[len(prefix) :], expected
        ):
            return JSONResponse({"detail": "Invalid sidecar token"}, status_code=401)
    return await call_next(request)


class ProjectCreate(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    question: str = Field(default="", max_length=2000)
    document_type: Literal["proposal", "literature_review", "imrad"] = "proposal"


class FeedbackCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)
    project_id: int | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class ExperimentRunCreate(BaseModel):
    dataset_artifact_id: int
    experiment_id: str
    approved_by_user: bool
    operation: dict[str, Any]
    limits: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    random_seed: int = Field(default=17, ge=0, le=2_147_483_647)


class ConversationCreate(BaseModel):
    model_id: str = Field(default="phi4-mini", min_length=1, max_length=80)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConsentUpdate(BaseModel):
    consent_training: bool | None = None
    consent_clone_phi: bool | None = None


class ChatStreamCreate(BaseModel):
    conversation_id: str
    content: str = Field(default="", max_length=50_000)
    model_id: str = Field(min_length=1, max_length=80)
    compare_model_id: str | None = Field(default=None, max_length=80)
    parent_message_id: str | None = None
    regenerate_message_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)


class ChatFeedbackCreate(BaseModel):
    message_id: str
    rating: Literal["up", "down"]
    correction: str | None = Field(default=None, max_length=20_000)
    consent_training: bool = False


def repository(request: Request) -> ResearchRepository:
    return request.app.state.repository


def workflow(request: Request) -> WorkflowEngine:
    return request.app.state.workflow


def chat_repository(request: Request) -> ChatRepository:
    return request.app.state.chat_repository


def chat_service(request: Request) -> ChatService:
    return request.app.state.chat


def decode_artifacts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        try:
            item["data"] = json.loads(item["content"])
        except (json.JSONDecodeError, TypeError):
            item["data"] = {"summary": item["content"]}
    return items


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"projects": repository(request).list_projects(), "stages": STAGES},
    )


@app.post("/research")
async def create_research_form(
    request: Request,
    topic: Annotated[str, Form(min_length=2, max_length=300)],
    question: Annotated[str, Form(max_length=2000)] = "",
    document_type: Annotated[
        Literal["proposal", "literature_review", "imrad"], Form()
    ] = "proposal",
):
    project = repository(request).create_project(topic, question, document_type)
    return RedirectResponse(f"/research/{project['id']}", status_code=303)


@app.get("/research", response_class=HTMLResponse)
@app.get("/sources", response_class=HTMLResponse)
@app.get("/novelty", response_class=HTMLResponse)
@app.get("/drafting", response_class=HTMLResponse)
@app.get("/experiments", response_class=HTMLResponse)
@app.get("/exports", response_class=HTMLResponse)
async def stage_overview(request: Request):
    stage = request.url.path.strip("/")
    return templates.TemplateResponse(
        request,
        "stage.html",
        {
            "stage": stage,
            "stages": STAGES,
            "projects": repository(request).list_projects(),
            "project": None,
            "artifacts": [],
            "datasets": [],
        },
    )


@app.get("/research/{project_id}", response_class=HTMLResponse)
@app.get("/sources/{project_id}", response_class=HTMLResponse)
@app.get("/novelty/{project_id}", response_class=HTMLResponse)
@app.get("/drafting/{project_id}", response_class=HTMLResponse)
@app.get("/experiments/{project_id}", response_class=HTMLResponse)
@app.get("/exports/{project_id}", response_class=HTMLResponse)
async def stage_project(request: Request, project_id: int):
    stage = request.url.path.strip("/").split("/", 1)[0]
    repo = repository(request)
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request,
        "stage.html",
        {
            "stage": stage,
            "stages": STAGES,
            "projects": repo.list_projects(),
            "project": project,
            "artifacts": decode_artifacts(repo.list_artifacts(project_id, stage)),
            "datasets": decode_artifacts(repo.list_artifacts(project_id, "dataset")),
        },
    )


@app.get("/feedback", response_class=HTMLResponse)
async def feedback_form(request: Request):
    return templates.TemplateResponse(
        request,
        "feedback.html",
        {
            "projects": repository(request).list_projects(),
            "stages": STAGES,
            "sent": False,
            "training_sent": False,
        },
    )


@app.post("/feedback", response_class=HTMLResponse)
async def feedback_form_submit(
    request: Request,
    comment: Annotated[str, Form(min_length=1, max_length=5000)],
    project_id: Annotated[int | None, Form()] = None,
    rating: Annotated[int | None, Form(ge=1, le=5)] = None,
):
    repository(request).add_feedback(comment, project_id, rating)
    return templates.TemplateResponse(
        request,
        "feedback.html",
        {
            "projects": repository(request).list_projects(),
            "stages": STAGES,
            "sent": True,
            "training_sent": False,
        },
    )


@app.get("/api/health")
async def health(request: Request):
    # Process readiness must not depend on an optional model provider; model status
    # is reported independently by /api/chat/models.
    return {"status": "ok"}


@app.get("/api/chat/conversations")
async def list_chat_conversations(
    request: Request,
    query: str = "",
    limit: int = 100,
    offset: int = 0,
):
    return chat_repository(request).list_conversations(
        query=query, limit=max(1, min(limit, 200)), offset=max(0, offset)
    )


@app.post("/api/chat/conversations", status_code=201)
async def create_chat_conversation(request: Request, payload: ConversationCreate):
    try:
        return chat_repository(request).create_conversation(payload.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/chat/conversations/{conversation_id}")
async def update_chat_conversation(
    request: Request, conversation_id: str, payload: ConversationUpdate
):
    item = chat_repository(request).update_conversation(
        conversation_id, title=payload.title.strip()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return item


@app.delete("/api/chat/conversations/{conversation_id}", status_code=204)
async def delete_chat_conversation(request: Request, conversation_id: str):
    if chat_repository(request).get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not chat_repository(request).delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@app.get("/api/chat/conversations/{conversation_id}/messages")
async def list_chat_messages(
    request: Request, conversation_id: str, limit: int = 500, offset: int = 0
):
    repo = chat_repository(request)
    if repo.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return repo.list_messages(
        conversation_id, limit=max(1, min(limit, 1000)), offset=max(0, offset)
    )


@app.patch("/api/chat/conversations/{conversation_id}/consent", status_code=204)
async def update_chat_consent(
    request: Request, conversation_id: str, payload: ConsentUpdate
):
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No consent fields provided")
    if chat_repository(request).update_conversation(conversation_id, **changes) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")


@app.get("/api/chat/models")
async def chat_models(request: Request):
    return await chat_service(request).registry.models()


@app.post("/api/chat/feedback", status_code=204)
async def create_chat_feedback(request: Request, payload: ChatFeedbackCreate):
    repo = chat_repository(request)
    message = repo.get_message(payload.message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    conversation = repo.get_conversation(message["conversation_id"])
    effective_consent = bool(
        payload.consent_training and conversation and conversation["consent_training"]
    )
    repo.add_feedback(
        payload.message_id, payload.rating, payload.correction, effective_consent
    )


@app.post("/api/chat/runs/{run_id}/cancel", status_code=204)
async def cancel_chat_run(request: Request, run_id: str):
    if not chat_service(request).cancel(run_id):
        raise HTTPException(status_code=404, detail="Active run not found")


@app.post("/api/chat/conversations/{conversation_id}/attachments", status_code=201)
async def upload_chat_attachment(
    request: Request,
    conversation_id: str,
    file: Annotated[UploadFile, File(description="PDF, image, DOCX, or text-like file")],
):
    from backend.app.chat.ingest import MAX_ATTACHMENTS, MAX_FILE_BYTES, IngestError, extract

    repo = chat_repository(request)
    if repo.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if len(repo.list_attachments(conversation_id)) >= MAX_ATTACHMENTS:
        raise HTTPException(status_code=409, detail=f"At most {MAX_ATTACHMENTS} files per conversation")
    payload = await file.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_BYTES} bytes")
    filename = Path(file.filename or "upload.bin").name
    try:
        extracted = extract(payload, filename=filename, media_type=file.content_type)
    except IngestError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    stored = settings.resolved_upload_path / f"{conversation_id}-{secrets.token_hex(12)}{Path(filename).suffix}"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(payload)
    record = repo.add_attachment(
        conversation_id,
        filename=extracted["filename"],
        stored_path=str(stored.resolve()),
        media_type=file.content_type,
        extracted_text=extracted["text"],
        kind=extracted["kind"],
    )
    return {
        "id": record["id"],
        "filename": record["filename"],
        "kind": record["kind"],
        "bytes": extracted["bytes"],
        "preview": extracted["text"][:400],
    }


@app.post("/api/chat/stream")
async def stream_chat(request: Request, payload: ChatStreamCreate):
    service = chat_service(request)
    run = service.new_run()
    return StreamingResponse(
        service.stream(run, payload),
        media_type="application/x-ndjson",
        headers={"x-run-id": run.id, "Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/projects")
async def list_projects(request: Request):
    return repository(request).list_projects()


@app.post("/api/projects", status_code=201)
async def create_project(request: Request, payload: ProjectCreate):
    return repository(request).create_project(
        payload.topic, payload.question, payload.document_type
    )


@app.get("/api/projects/{project_id}")
async def get_project(request: Request, project_id: int):
    repo = repository(request)
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["artifacts"] = decode_artifacts(repo.list_artifacts(project_id))
    return project


@app.post("/api/projects/{project_id}/stages/{stage}", status_code=202)
async def run_stage(
    request: Request, project_id: int, stage: str, background_tasks: BackgroundTasks
):
    try:
        job_id = workflow(request).enqueue(project_id, stage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(workflow(request).run_job, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    job = repository(request).get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/projects/{project_id}/artifacts")
async def artifacts(request: Request, project_id: int, kind: str | None = None):
    if not repository(request).get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return decode_artifacts(repository(request).list_artifacts(project_id, kind))


@app.get("/api/projects/{project_id}/export", response_class=PlainTextResponse)
async def export_project(request: Request, project_id: int):
    repo = repository(request)
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sections = [f"# {project['topic']}", project["question"]]
    for artifact in reversed(repo.list_artifacts(project_id)):
        sections.extend([f"## {artifact['title'] or artifact['kind'].title()}", artifact["content"]])
    headers = {"Content-Disposition": f'attachment; filename="research-{project_id}.md"'}
    return PlainTextResponse("\n\n".join(filter(None, sections)), headers=headers)


def _latest_draft(repo: ResearchRepository, project_id: int) -> DraftDocument:
    artifacts = repo.list_artifacts(project_id, "drafting")
    if not artifacts:
        raise HTTPException(status_code=409, detail="Run Drafting before exporting")
    try:
        payload = json.loads(artifacts[0]["content"])
        return DraftDocument.model_validate(payload["document"])
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Stored draft is invalid") from exc


@app.get("/api/projects/{project_id}/export/{format_name}")
async def export_validated(request: Request, project_id: int, format_name: str):
    document = _latest_draft(repository(request), project_id)
    if format_name == "markdown":
        return Response(
            export_markdown(document),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="research-{project_id}.md"'},
        )
    if format_name == "bibtex":
        return Response(
            export_bibtex(document),
            media_type="application/x-bibtex; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="research-{project_id}.bib"'},
        )
    if format_name == "docx":
        return Response(
            export_docx(document),
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            headers={"Content-Disposition": f'attachment; filename="research-{project_id}.docx"'},
        )
    raise HTTPException(status_code=404, detail="Unknown export format")


@app.post("/api/projects/{project_id}/datasets", status_code=201)
async def upload_dataset(
    request: Request,
    project_id: int,
    dataset: Annotated[UploadFile, File(description="UTF-8 CSV dataset")],
):
    repo = repository(request)
    if not repo.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if not dataset.filename or not dataset.filename.casefold().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only CSV datasets are accepted")
    maximum = InputLimits().max_file_bytes
    content = await dataset.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(status_code=413, detail=f"Dataset exceeds {maximum} bytes")
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="Dataset must be UTF-8 CSV") from exc
    stored = settings.resolved_upload_path / f"{project_id}-{secrets.token_hex(12)}.csv"
    stored.write_bytes(content)
    artifact_id = repo.add_artifact(
        project_id,
        "dataset",
        {"filename": dataset.filename, "size_bytes": len(content)},
        title=dataset.filename,
        metadata={"stored_path": str(stored.resolve())},
    )
    return {"artifact_id": artifact_id, "filename": dataset.filename, "size_bytes": len(content)}


@app.post("/api/projects/{project_id}/experiments/run", status_code=201)
async def execute_experiment(
    request: Request, project_id: int, payload: ExperimentRunCreate
):
    repo = repository(request)
    if not repo.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.approved_by_user is not True:
        raise HTTPException(status_code=409, detail="Explicit user approval is required")
    dataset = repo.get_artifact(payload.dataset_artifact_id)
    if (
        dataset is None
        or int(dataset["project_id"]) != project_id
        or dataset["kind"] != "dataset"
    ):
        raise HTTPException(status_code=404, detail="Dataset artifact not found")
    try:
        spec = ExperimentSpec(
            experiment_id=payload.experiment_id,
            approved_by_user=True,
            input=CsvInput(path=Path(dataset["metadata"]["stored_path"])),
            operation=payload.operation,
            limits=payload.limits,
            timeout_seconds=payload.timeout_seconds,
            random_seed=payload.random_seed,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = await run_in_threadpool(
        run_experiment,
        spec,
        allowed_input_roots=[settings.resolved_upload_path],
        artifact_root=settings.resolved_experiment_artifact_path,
    )
    dumped = result.model_dump(mode="json")
    repo.add_artifact(
        project_id,
        "experiments",
        {"title": payload.experiment_id, "summary": result.state.value, "items": [dumped]},
        title=payload.experiment_id,
        metadata={"input_sha256": result.input_sha256},
    )
    return dumped


@app.post("/api/feedback", status_code=201)
async def create_feedback(request: Request, payload: FeedbackCreate):
    if payload.project_id is not None and not repository(request).get_project(payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    feedback_id = repository(request).add_feedback(
        payload.comment, payload.project_id, payload.rating
    )
    return {"id": feedback_id, "status": "received"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
