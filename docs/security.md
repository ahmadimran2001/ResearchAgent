# Security policy

## Supported use

ResearchAgent is intended for local research assistance. It must not be used to
fabricate citations or results, bypass access controls, scrape sources contrary to
their terms, or make consequential clinical, legal, employment, or public-policy
decisions without qualified human review.

## Local attack surface

- The web server binds to loopback by default.
- Desktop API requests require a random per-launch bearer token injected into the
  Tauri webview; the token is not persisted.
- Uploaded data is size-limited, copied into an application-controlled directory,
  and addressed by generated identifiers rather than user-supplied paths.
- Scholarly content is untrusted and is delimited as evidence in prompts.
- Secrets come from environment variables. `.env`, databases, uploads, and generated
  artifacts are excluded from version control.
- HTTP clients use explicit timeouts, bounded retries, provider rate limits, and a
  descriptive user agent.

## Experiment execution

The experiment runner does not evaluate generated code. It validates a declarative
specification and invokes an allow-listed implementation. Network access, shell
commands, package installation, arbitrary imports, and access outside the configured
data/artifact roots are not part of the interface. Runs have time, data-size, and
shape limits and record an input hash, seed, environment, logs, and status.

This is defense in depth, not a general-purpose hostile-code sandbox. Do not weaken
the allow list or pass model output to `eval`, `exec`, a shell, a notebook kernel, or
an unrestricted Python interpreter.

## Reporting vulnerabilities

Do not include credentials, private datasets, or personal information in a report.
Provide reproduction steps, impact, and the affected version to the project owner
through a private channel.
