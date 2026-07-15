# Contributing to Forge

Thank you for your interest in contributing to Forge. This project is in an
alpha stage, so clear issues, focused pull requests, and tests are especially
valuable.

## Development Setup

Install the Python workspace:

```bash
uv sync --dev
```

Build the Rust workspace:

```bash
cargo build --workspace
```

## Checks

Before opening a pull request, run:

```bash
uv run ruff check .
uv run python scripts/check_forge_msgs_schema.py
uv run pytest packages/msgs/tests packages/policy/tests packages/robot/tests
cargo test --workspace
```

If you change the Python workspace dependencies, update `uv.lock`:

```bash
uv lock
```

If you change Rust dependencies, update the root `Cargo.lock`:

```bash
cargo update
```

## Message Schema Changes

`interfaces/forge_msgs/forge_msgs.v1.yaml` is the manifest for the canonical
Forge message schemas. Message definitions live in the versioned domain files
referenced by that manifest. When changing message fields or semantics:

1. Update the appropriate domain schema and `interfaces/forge_msgs/SCHEMA.md`.
2. Update both Python and Rust implementations when applicable.
3. Add or update round-trip tests.
4. Run `uv run python scripts/check_forge_msgs_schema.py`.
5. Document compatibility implications in the pull request.

If a message is intentionally unavailable in one language, declare its current
`implementations` in the domain schema rather than implying cross-language
support.

## Pull Request Guidelines

- Keep pull requests focused on one behavior or package area.
- Include tests for behavior changes and bug fixes.
- Avoid committing generated build outputs, virtual environments, or local
  machine configuration.
- Do not include secrets, private tokens, private URLs, or hardware credentials.
- For robot hardware integrations, keep vendor SDKs and large binary artifacts
  out of this core repository unless explicitly discussed.

## Reporting Bugs

When filing an issue, include:

- The package or crate involved.
- Python, Rust, uv, and Dora versions where relevant.
- A minimal reproduction or failing test when possible.
- Expected behavior and actual behavior.

## License

By contributing, you agree that your contributions are licensed under the Apache
License, Version 2.0.
