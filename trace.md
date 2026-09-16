# Build trace

This file records material actions performed while building ResearchAgent. It does
not contain credentials, private prompts, chain-of-thought, or generated datasets.

## 2026-09-15

- Created `D:\Projects\ResearchAgent` as a separate Git repository.
- Built and verified the initial FastAPI research backend, scholarly-source adapters,
  evidence-ledger drafting, bounded experiment runner, consent-aware training
  scaffolding, SQLite persistence, and local web interface.
- Installed the project runtime/development dependencies in `.venv`.
- Verified live scholarly retrieval from OpenAlex, Crossref, and Semantic Scholar;
  arXiv returned a handled rate-limit response.
- Diagnosed that the 14B `phi4` Ollama image cannot allocate its required 5.75 GB
  CPU repack buffer on this 8 GB machine.
- Installed `phi4-mini` without deleting `phi4`; verified structured generation and
  configured `phi4-mini` as the default local runtime.
- Ran the integrated suite successfully: 19 Python tests and Ruff checks passed
  before the desktop/from-scratch-model requirements replaced the earlier UI plan.
- Confirmed Node.js 24 and npm 11 are installed. Rust and Cargo are not yet installed.
- An optional ML dependency installation was interrupted by a file lock from the
  running Python application; it will be retried after stopping that process.
- Revised the product direction to a Tauri 2 desktop chat app with persistent local
  history, Phi-4 Mini versus from-scratch model comparison, retained evidence-first
  research tools, and explicit-consent offline beta learning.
- Started parallel implementation of:
  - the custom byte-level BPE, tiny causal transformer, data pipeline, training,
    checkpoint/resume, and inference stack;
  - the React/TypeScript chat interface and Tauri Python-sidecar shell.
- Implemented the token-authenticated Python chat sidecar with additive SQLite
  migrations, persistent branching/history, sequential model comparison, durable
  NDJSON streaming/cancellation, shared evidence packets, allow-listed research
  routing, model/checkpoint registry, and PyInstaller entry point; 9 focused backend
  tests, Ruff checks, and Python compilation passed.
- Replaced the obsolete pretrained query-expansion training path with local-only,
  explicit-consent corrected-chat learning: append-only redacted events and tombstones,
  immutable conversation-grouped CLM/SFT datasets, an isolated cancellable scratch-model
  worker, multi-part evaluation gates, atomic promotion, and rollback. The focused
  training/chat suite passed 19 tests; Ruff and Python compilation passed.

## Operating constraints

- Commands and safe development-tool installations may run within this repository.
- Do not install harmful, untrusted, pirated, or unnecessary software.
- Do not publish, upload private data, delete user data, or expose credentials.
- Record subsequent material installs, migrations, training runs, test results, and
  publication actions below.

## 2026-09-16 final integration

- Installed PyInstaller 6.22.3 in `.venv`, Vitest 5.0.1 and its local test dependencies,
  plus rustup with stable Rust/Cargo 1.98.1. The patched npm graph audits with zero
  vulnerabilities.
- Confirmed the installed Visual Studio Community instance lacks the MSVC C++ tools and
  Windows SDK libraries. `cargo fmt --check` passes; `cargo check` remains blocked by
  missing `link.exe`/Windows import libraries. A system-wide Build Tools installation
  was not completed.
- Trained the deterministic smoke demonstrator from random initialization for 12 steps on
  the CC0 fixture corpus. Training loss moved from 5.7159 to 5.0993; validation loss moved
  from 5.4251 at step 4 to 5.1694 at step 12. Retained the ignored active checkpoint at
  `data/checkpoints/active.pt`.
- Live end-to-end verification passed for Phi-4 Mini streaming, scratch streaming,
  sequential two-lane comparison, shared scholarly evidence (six verified citations),
  and SQLite restoration (five messages).
- Full verification passed: 43 Python tests, Ruff, Python compileall, one UI contract
  test, TypeScript typecheck, Vite production build, npm high-severity audit, and Rust
  formatting.
- PyInstaller initially produced a 235,093,703-byte one-file Windows sidecar. Its
  readiness smoke exposed packaging faults that were resolved in the continuation below.
- Added Windows setup/training/sidecar/package/runtime-verification scripts, GitHub CI,
  root documentation and policies, model/dataset/license/third-party notices, persistent
  desktop data paths, bootstrap-checkpoint packaging, and generated-artifact ignores.
- No GitHub, Hugging Face, installer, checkpoint, chat, or dataset upload/publication was
  performed.

## 2026-09-16 blocker resolution

- Verified PID 20244 by executable path and old test-port command line before terminating
  only that stale ResearchAgent sidecar process.
- Diagnosed packaged readiness failures: C: had insufficient room for one-file extraction;
  the PowerShell build script did not propagate PyInstaller's native exit code and copied
  stale output; a windowed executable exposed null standard streams to Uvicorn logging;
  and the first onedir copy lacked its frozen runtime. Added strict build failure checks,
  a complete onedir runtime, D:/application-data temp paths, windowed-safe streams,
  direct app import, lazy scratch loading, packaged training-worker dispatch, and opt-in
  frozen startup diagnostics.
- Rebuilt the final PyInstaller bundle successfully: 38,012,100-byte executable plus
  648,105,868 bytes across 5,058 runtime files. Authenticated packaged verification passed:
  health `ok`, unauthenticated health `401`, scratch and Phi-4 Mini NDJSON completion
  events, and four restored SQLite messages.
- Phi-4 Mini briefly failed its 1.30 GB CPU-repack allocation while memory was pressured;
  the same direct Ollama request and packaged stream passed after pressure subsided.
  Scratch state is now released before Phi inference on the 8 GB target.
- Inspected storage before native installation (initially C: 1.25 GB free, D: 113.56 GB).
  Started the official, hash-verified Microsoft Visual Studio Build Tools 2022 package
  with install/cache/temp paths on D:, but its elevation handoff remained noninteractive
  for 16 minutes and created no installation instance. Stopped only the verified stalled
  winget process tree. C: subsequently had only 0.25 GB free; no files or existing tools
  were removed.
- Added an elevation-aware `scripts/install-build-tools.ps1` using only Microsoft's winget
  package, MSVC workload, and Windows 11 SDK component. Build Tools remain uninstalled.
  Rust formatting passes; `cargo check --locked` reaches compilation from a D: target and
  is blocked specifically by missing `link.exe`.
- Final affected checks: 43 Python tests passed with two upstream deprecation warnings;
  Ruff and compileall passed; one Vitest test, TypeScript typecheck, Vite production build,
  and npm audit (zero vulnerabilities) passed. PowerShell and Tauri JSON syntax passed.
  No Tauri installer artifact was produced because the native linker is unavailable.
- No publication, upload, or user-data deletion occurred.

## 2026-09-16 Ollama storage verification

- Found that Ollama had already been relocated before this continuation:
  the persistent user and active process `OLLAMA_MODELS` values were both
  `D:\OllamaModels`, and `C:\Users\Admin\.ollama\models` did not exist.
  Therefore no C: model blobs, manifests, or personal content were deleted.
- Inventoried `D:\OllamaModels`: 10.752 GiB (11,544,993,648 bytes), eight blobs,
  and two manifests (`phi4:latest` and `phi4-mini:latest`). Recomputed SHA-256
  for every blob; all eight matched their digest filenames. Verified every
  manifest digest resolves to a present blob.
- Confirmed `ollama list` still reports Phi-4 (9.1 GB) and Phi-4 Mini (2.5 GB).
  Phi-4 Mini generated `READY`, and the packaged-sidecar verification again
  passed authenticated health, unauthenticated `401`, scratch streaming,
  Phi-4 Mini streaming, and four restored messages.
- C: initially had 0.574 GiB free. With no ResearchAgent sidecar or Cargo process
  running, removed only two verified orphaned ResearchAgent PyInstaller
  extraction directories (`_MEI00001b142`, 0.665 GiB; `_MEI000049602`,
  0.604 GiB) and this session's verified Cargo sandbox target
  (`0f4ce22b739ea55b14bbb502b9e9cac6`, 0.730 GiB). These were generated build
  outputs, not user documents or unrelated caches.
- C: free space increased to 2.610 GiB; D: remained at 111.973 GiB free. The
  required 10 GiB threshold was not reached without deleting unrelated data or
  existing Visual Studio package content, so the guarded Microsoft Build Tools
  installer was not rerun. MSVC/Windows SDK, `cargo check`, and Tauri installer
  generation remain blocked on additional user-approved C: cleanup.
- No publication, upload, model deletion, or unrelated-data deletion occurred.

## 2026-09-16 D-drive native toolchain configuration

- Before migration, C: had 4.964 GiB free and D: had 111.973 GiB free. The
  session-created Rust homes were `C:\Users\Admin\.rustup` (65,908 files,
  1,370,670,178 bytes) and `C:\Users\Admin\.cargo` (13,929 files,
  570,497,494 bytes), both created when this session installed rustup. The
  pre-existing npm cache dated 2024 (1,019,400,754 bytes) was left untouched.
  No persistent pip cache existed.
- Verified that the repository venv (1,167,849,000 bytes), node_modules
  (142,808,618 bytes), and Ollama store (11,544,993,648 bytes) were already on D:.
- Added `scripts/native-env.ps1` and `scripts/configure-native-tools.ps1`.
  Copied the complete Rust homes to `D:\DevTools\Rust`, verified source and
  destination file counts/byte totals, and successfully ran Rust 1.98.1 and
  Cargo 1.98.1 from the D: proxies. Only after verification, removed the two
  session-created C: Rust directories.
- Persisted user settings: `RUSTUP_HOME=D:\DevTools\Rust\rustup`,
  `CARGO_HOME=D:\DevTools\Rust\cargo`,
  `CARGO_TARGET_DIR=D:\Caches\ResearchAgent\cargo-target`,
  `PIP_CACHE_DIR=D:\Caches\pip`, `npm_config_cache=D:\Caches\npm`, and
  `TEMP`/`TMP=D:\Caches\Temp`; updated the user PATH to the D: Cargo bin.
  Repository setup, sidecar-build, and packaging scripts now load this
  environment explicitly.
- Updated the official Microsoft installer script to request
  `D:\DevTools\Microsoft\VisualStudio\2022\BuildTools`, D: shared tools, a
  D: download cache and temp directory, and `--nocache`. Some installer,
  prerequisite, and Windows SDK components remain Windows-managed on C:.
- Immediately after migration, C: had 6.879 GiB free and D: had 109.941 GiB
  free. The
  guarded Build Tools attempt exited immediately with the exact diagnostic
  `Run this script from an elevated PowerShell window (Run as administrator).`
  The Cursor process is not elevated, so no UAC wait or partial install occurred.
  Microsoft documents 850 MB as the minimum system-drive requirement, with
  actual workload requirements dependent on components.
- Verified D:-resolved `rustc` and `cargo`. Rust formatting passed; `cargo check
  --locked` compiled dependencies from the D: target and stopped only because
  `link.exe` is unavailable. No Windows SDK or MSVC component was discovered,
  so Tauri compilation/installer generation could not safely proceed.
- Final affected checks passed: 43 Python tests (two upstream deprecation
  warnings), Ruff, compileall, one Vitest test, TypeScript typecheck, Vite build,
  npm audit with zero vulnerabilities, PowerShell parsing, and packaged sidecar
  authenticated health/scratch/Phi streaming with four restored messages.
- The final packaged-model check loaded Phi-4 Mini (3.7 GB). Windows
  automatically expanded the Windows-managed `C:\pagefile.sys` to 9,578 MB
  under memory pressure. `ollama stop phi4-mini` released the loaded model
  without deleting it; free physical memory rose to 3.61 GiB, and the pagefile
  settled at 9,026 MB allocated/1,245 MB used. It was not manually moved or
  altered. Final measured free space was C: 2.852 GiB and D: 109.921 GiB. The
  repository's conservative installer guard therefore requires another
  1.148 GiB free on C: (or a Windows-managed pagefile shrink after reboot)
  before installation, in addition to an elevated shell.
- No pre-existing application, Windows-managed component, personal content,
  publication, or upload was modified or removed.
