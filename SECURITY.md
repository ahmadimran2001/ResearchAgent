# Security policy

Report vulnerabilities privately to the repository owner. Include affected version,
impact, and minimal reproduction steps; do not include credentials, personal data, or
private datasets. There is currently no guaranteed response SLA.

Only the latest repository revision is supported. Research Agent is a local research
tool, not a hostile-code sandbox. Keep the backend on loopback, protect local profile and
database files, review consented records before training, and never pass model output to
`eval`, `exec`, a shell, or unrestricted experiment runtime.

See `docs/security.md` for trust boundaries and mitigations.
