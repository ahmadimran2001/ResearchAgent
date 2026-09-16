# ResearchAgent architecture

The React UI runs inside Tauri 2. Tauri reserves an ephemeral loopback port, generates a
random 256-bit token, starts the PyInstaller Python sidecar, injects only the base URL and
token into the desktop webview, waits for authenticated health readiness, and terminates
the child on application exit. Development mode can run Vite and Uvicorn separately.

The FastAPI sidecar owns SQLite chat/research persistence, Ollama model routing, and
allow-listed research tools. SQLite migrations are additive and preserve the earlier
research workflow tables.

## Models and streaming

`ModelRegistry` lists models installed in Ollama and streams through the Ollama chat API.
Phi-4 Mini is the default configured tag. Weights stay with Ollama. The chat system prompt
is the research contract in `backend/app/chat/policy.py`. Frozen research-behavior tests
live in `backend/app/chat/phi_eval.py`.

Compare runs are sequential on the 8 GB target and link both assistant messages to one
immutable evidence packet. NDJSON events persist started, delta, citation, completion,
cancellation, and error state so history survives restart and partial output is auditable.

When a research tool runs, the sidecar always injects a structured evidence block:
query, retrieval timestamp, providers, listed citation IDs, and either source abstracts
or an explicit “no close work in named sources as of this date” clause.

## Evidence and trust boundaries

Scholarly records, uploaded content, and model output are untrusted data. Retrieval is
bounded and records provider/query/date provenance. Novelty is a comparison against that
retrieved set, never universal proof. Draft export accepts only citation identifiers in
the evidence ledger. Experiments validate declarative specs and invoke built-in operations
only after explicit user approval; no model-authored code is executed.

Generated databases, uploads, model downloads, sidecar executables, and installers are
local ignored artifacts.
