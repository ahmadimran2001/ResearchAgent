# Research Agent

Research Agent is a local-first Windows desktop research chat. It uses **Ollama**
models (Phi-4 Mini by default, plus any other models you have installed) together
with evidence-first literature search, bounded novelty analysis, citation-validated
drafting, approved CSV experiments, PDF/image/document attachments, and persistent
chat history.

Language models are downloaded and served by Ollama. This repository does not ship
or train a custom Transformer.

## Windows quick start

Prerequisites: Windows 10/11, Python 3.10+, Node.js 20+, Ollama, and about 6 GB free
disk space. The desktop build additionally needs Rust stable and the Visual Studio 2022
**Desktop development with C++** workload (MSVC and Windows SDK).

Install the official native prerequisites from an elevated PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/configure-native-tools.ps1
powershell -ExecutionPolicy Bypass -File scripts/install-build-tools.ps1
powershell -ExecutionPolicy Bypass -File scripts/verify-native-tools.ps1
```

These scripts place Rustup/Cargo under `D:\DevTools`, build and package caches under
`D:\Caches`, and request D: locations for Build Tools, its download cache, shared tools,
and temporary files. Microsoft documents that its installer and some Windows SDK/shared
components can still require system-drive space.

```powershell
git clone <repository-url>
cd ResearchAgent
powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1
Copy-Item .env.example .env
ollama pull phi4-mini
```

Run the browser-development UI in two terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
npm run dev
```

Open <http://127.0.0.1:1420>. For the native desktop:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1
powershell -ExecutionPolicy Bypass -File scripts/verify-packaged-sidecar.ps1
npm run desktop:dev
```

Build signed-or-unsigned local MSI/NSIS artifacts (nothing is uploaded):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package-windows.ps1
```

## Chat, comparison, and research behavior

The Tauri shell starts a PyInstaller sidecar on an ephemeral loopback port, injects a
random bearer token into the webview, waits for readiness, and kills the sidecar on exit.
SQLite persists conversations, branches, partial/cancelled streams, compare linkage, and
citations. Compare mode runs installed Ollama models sequentially to avoid memory
contention and supplies both with one stored evidence packet.

Research tools use an allow-list. Retrieved text is untrusted data, novelty claims are
bounded by searched providers/date, unknown citation IDs are rejected before validated
export, and experiments run only declared built-in operations after explicit approval.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m compileall -q backend tests
npm test
npm run typecheck
npm run build
npm audit --audit-level=high
cargo fmt --manifest-path src-tauri\Cargo.toml -- --check
cargo check --manifest-path src-tauri\Cargo.toml
```

See `docs/architecture.md`, `docs/security.md`, `docs/qa-strategy.md`,
and `THIRD_PARTY_NOTICES.md`.

## Privacy, limitations, and hardware

Chats, uploads, databases, sidecar builds, and secrets stay in ignored local paths.
Research Agent does not provide a hostile-code sandbox and must not be used for
autonomous medical, legal, safety-critical, or publication decisions. Source APIs can
be incomplete or rate-limited. Ollama models can hallucinate. The target machine has
8 GB RAM and no CUDA requirement; do not run two large models concurrently.

## License

Repository code is MIT licensed; see `LICENSE`. Phi-4 Mini, Ollama, source APIs,
libraries, and user-provided datasets retain their own terms.
