# ResearchAgent conversation context

## Goal

Build and publish a local, research-focused AI project that demonstrates two distinct
models:

1. **Phi-4 Mini** — an existing Microsoft model run locally through Ollama. This is
   the capable model used for practical conversations and research assistance.
2. **Scratch Research** — a tiny Transformer built entirely in this repository,
   including its tokenizer, dataset pipeline, architecture, training loop,
   checkpoints, evaluation, and inference.

The project is intended for GitHub and includes a Tauri/React desktop-style chat
application with local history, model switching, side-by-side comparison, research
tools, and opt-in beta learning.

## Machine constraints

- Windows
- Intel Core i7-8650U, 4 cores / 8 threads
- 8 GB RAM
- Intel UHD 620 graphics; no CUDA GPU
- Use drive D: for installations, caches, models, temporary files, and builds where
  supported

The 14B `phi4` Ollama model is installed but cannot generate on this machine because
it needs an additional 5.75 GB CPU repack buffer. `phi4-mini` is installed, verified,
and selected as the practical model. Ollama models were verified on
`D:\OllamaModels`.

## Important product decisions

- Use a Tauri 2 Windows desktop shell with React, TypeScript, and Vite.
- Use a bundled Python sidecar to reuse PyTorch, SQLite, Ollama, and research code.
- Keep scholarly retrieval, bounded novelty analysis, evidence-ledger drafting,
  citation validation, and approved computational experiments behind the chat.
- Persist conversations locally in SQLite; no account, subscription, or usage limits.
- Support a model selector and side-by-side Phi-4 Mini versus Scratch Research mode.
- Run comparison responses sequentially because the machine has only 8 GB RAM.
- Never claim that a topic has definitely never been researched. Report only that no
  close work was found in named sources using recorded queries as of a stated date.
- Never fabricate citations, datasets, experiments, or research results.
- Never train automatically on all prompts.

## Implemented system

### Desktop chat

- Conversation sidebar with create, search, rename, and delete
- Persistent messages and restored history
- Markdown and code rendering
- Streaming responses and cancellation
- Regeneration/edit branches
- Model selection
- Sequential comparison view
- Citations drawer
- Feedback, consent, settings, and checkpoint status
- Tauri-managed authenticated loopback sidecar lifecycle

### Research capabilities

- OpenAlex, Crossref, Semantic Scholar, and arXiv adapters
- Provider pacing, retry/backoff, caching, provenance, and deduplication
- Explainable nearest-work and bounded novelty ranking
- Section-by-section literature review, proposal, and IMRaD drafting
- Evidence ledger and strict unknown-citation rejection
- Markdown, DOCX, and BibTeX exports
- User-approved, allow-listed CSV experiments
- Statistical summaries/tests and small scikit-learn benchmarks
- No model-authored shell or arbitrary experiment code

### Scratch model

- Custom deterministic byte-level BPE tokenizer
- Licensed/user-provided corpus ingestion with provenance
- Train/validation/test sharding
- Causal Transformer implemented with PyTorch tensor primitives
- Token/position embeddings, multi-head causal attention, feed-forward blocks,
  residuals, layer normalization, tied language-model head, and cross-entropy
- Explicit CPU training loop with AdamW, scheduling, gradient accumulation/clipping,
  checkpoints, resume, metrics, evaluation, and streaming inference
- CLI for tokenizer training, dataset preparation, training, evaluation, and chat
- Demonstrator checkpoint trained from random initialization on the fixture corpus

The demonstrator ran for only 12 steps. Its validation loss improved from about
5.4251 to 5.1694, proving the complete pipeline works. It is **not a useful language
model yet**, so its current output is mostly meaningless. The UI screenshot showing
text such as `artationuae...` came from selecting **Scratch Research**, not Phi-4
Mini.

### Beta learning

- Disabled by default
- Explicit per-conversation consent
- Secret/PII redaction
- Append-only feedback records and revocation/deletion tombstones
- Accepts positive selections or corrected ideal responses, not raw prompts alone
- Immutable, conversation-grouped datasets without split leakage
- Offline low-priority cancellable training
- Held-out loss, fixed research, citation, memorization, and regression gates
- Atomic checkpoint promotion and one-click rollback

The learning sequence is:

1. Pretrain from scratch on a sufficiently large, licensed text corpus using
   next-token prediction.
2. Continue training on licensed research-oriented material.
3. Supervise on high-quality research conversations and corrected responses.
4. Collect explicitly consented beta feedback.
5. Train a candidate checkpoint offline.
6. Promote it only when it beats the active checkpoint and passes safety/regression
   gates.

Raw beta prompts alone cannot teach correct answers and may contain private,
incorrect, or malicious content.

## Verification completed

- Full Python suite: 43 tests passed
- Python Ruff and compile checks passed
- React UI tests, typecheck, and production build passed
- npm production audit: zero known vulnerabilities
- Scratch tokenizer → data → random-init training → checkpoint → evaluation →
  generation pipeline passed
- Packaged Python sidecar built successfully
- Packaged health and token authentication passed
- Unauthenticated requests correctly returned HTTP 401
- Scratch and Phi streaming passed
- Sequential compare lanes passed
- Chat persistence and restoration passed
- Live research flow returned verified citations
- Rust formatting passed

Material actions, installations, disk changes, and test results are recorded in
`trace.md`.

## Remaining blocker

The app works in browser-development mode, but the native Windows Tauri installer has
not been produced. Microsoft C++ Build Tools and the Windows SDK require an elevated
installation and additional unavoidable free space on C:. Tools, Rust/Cargo homes,
caches, models, targets, virtual environment, and project files were moved/configured
on D: where supported. C: still needs roughly 1.13 GB more free space before the
guarded official installer can proceed.

After freeing space, run from elevated PowerShell:

```powershell
cd D:\Projects\ResearchAgent
.\scripts\install-build-tools.ps1
.\scripts\verify-native-tools.ps1
.\scripts\package-windows.ps1
```

## Run the application now

Keep Ollama running. Open two PowerShell terminals.

Terminal 1:

```powershell
cd D:\Projects\ResearchAgent
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd D:\Projects\ResearchAgent
npm run dev
```

Open `http://127.0.0.1:1420`.

Select **Phi-4 Mini** for useful responses. Select **Scratch Research** only to inspect
the educational model until it has received substantial licensed pretraining.

## Recommended next work

1. Change the UI default to Phi-4 Mini and label Scratch Research clearly as an
   experimental, minimally trained demonstrator.
2. Choose and document a legally compatible pretraining corpus.
3. Train the tokenizer on that corpus.
4. Run a longer CPU pretraining experiment, recognizing that useful quality may take
   days or weeks and will remain limited by this hardware/model size.
5. Evaluate before enabling the checkpoint for users.
6. Gather only explicit, corrected, consented beta examples.
7. Free enough C: space, install the official Microsoft build tools, and create the
   Windows installer.
8. Review licenses, model/dataset cards, screenshots, and security documentation
   before publishing the GitHub repository.

