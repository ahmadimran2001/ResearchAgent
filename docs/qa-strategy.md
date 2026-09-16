# Quality strategy

## Required invariants

1. Every displayed citation resolves to a canonical stored source.
2. Every experimental result resolves to a completed run and immutable input hash.
3. Novelty language identifies coverage and uncertainty; it never asserts universal
   proof that no prior work exists.
4. Source text cannot change system policy or invoke tools.
5. Compare responses share one evidence packet and execute sequentially.
6. Frozen Phi research-behavior tests reject invented citations and universal novelty.

## Test layers

- Unit tests cover normalization, deduplication, query fallbacks, claim validation,
  rate-limit handling, path validation, experiment schemas, and export escaping.
- Adapter tests use committed fixtures and mocked HTTP responses. Routine test runs
  never depend on provider availability.
- Integration tests exercise a complete research job with a fake language model and
  source adapters, plus Ollama availability separately when explicitly requested.
- Desktop contract tests cover bearer authentication, history restoration, linked
  compare runs, and persisted partial streams.
- Adversarial cases include fake DOIs, invented citation keys, prompt injection in
  abstracts, CSV formula payloads, path traversal, oversized datasets, fabricated
  results, and requests for unsupported experiments.

## Release gate

- The automated suite passes from a clean environment.
- No unknown citation reaches a draft or export.
- No unsupported claim is presented as an experiment result.
- The application remains responsive when Ollama or a scholarly provider is down.
- Python tests/lint/compilation, UI tests/typecheck/build/audit, PyInstaller analysis,
  and Rust formatting/checks pass in the packaging environment.
