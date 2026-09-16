# Contributing

Use Python 3.10+, Node.js 20+, and the setup command in `README.md`. Keep generated data,
chats, credentials, model downloads, and build outputs out of commits.

Before submitting a change, run the Python tests, Ruff, compileall, UI tests, typecheck,
production build, and npm audit listed in the README. Changes to the desktop shell also
require `cargo fmt --check` and `cargo check`.

New research sources must define rate limits, timeouts, attribution, terms, and failure
behavior. New experiments must be declarative and allow-listed. Never add
publication/upload behavior without an explicit design and privacy review.

Report behavioral limitations and negative test results honestly. Do not claim novelty,
citation validity, or privacy guarantees beyond measured evidence.
