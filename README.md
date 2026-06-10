# Forge

Forge is a small robotics framework core for Dora dataflows. It provides shared
message schemas, Python and Rust message implementations, and reusable node
runner helpers for robot drivers and policy nodes.

This repository intentionally focuses on the framework layer:

- `interfaces/forge_msgs/` contains the canonical message schema.
- `packages/msgs` provides Python message models and Arrow serialization.
- `crates/forge_msgs` provides the Rust message implementation.
- `packages/robot` provides robot driver protocols, safety clipping helpers, and
  a standard Dora robot node loop.
- `packages/policy` provides policy adapter protocols and a standard Dora policy
  node loop.
- `packages/common` and `crates/forge_common` provide shared utilities,
  currently including logging and tracing helpers.

Robot-specific drivers and hardware SDK integrations should live in downstream
packages, for example a separate `forge_robots` repository.

## Status

Forge is currently alpha software. Public APIs, message schemas, and runner
semantics may change before a stable release.

## Repository Layout

```text
forge/
├── interfaces/forge_msgs/      # Canonical cross-language message schema
├── packages/common/            # Python shared utilities
├── packages/msgs/              # Python message models and Arrow conversion
├── packages/policy/            # Python policy node protocols and Dora runner
├── packages/robot/             # Python robot driver protocols and Dora runner
├── crates/forge_common/        # Rust shared utilities
├── crates/forge_msgs/          # Rust message types and Arrow conversion
├── pyproject.toml              # Python uv workspace
└── Cargo.toml                  # Rust cargo workspace
```

## Requirements

- Python 3.12 or newer for the workspace
- Rust toolchain with edition 2024 support
- [`uv`](https://docs.astral.sh/uv/) for Python dependency management
- Dora runtime when running real nodes (`dora-rs==0.4.1` is used by the Python
  node packages)

## Installation

Clone the repository and install the Python workspace:

```bash
uv sync --dev
```

Build the Rust workspace:

```bash
cargo build --workspace
```

## Testing

Run the Python tests:

```bash
uv run pytest packages/msgs/tests packages/policy/tests packages/robot/tests
```

Run the Rust tests:

```bash
cargo test --workspace
```

Run Ruff checks:

```bash
uv run ruff check .
```

## Message Schema

The canonical cross-language contract lives in
`interfaces/forge_msgs/forge_msgs.v1.yaml`. Python, Rust, and future language
implementations should conform to that schema. See
`interfaces/forge_msgs/SCHEMA.md` and `packages/msgs/README.md` for message
semantics and Arrow encoding details.

Core messages include:

- `JointState` for robot or simulator joint observations
- `JointCommand` for low-level joint commands
- `LocomotionCommand` for planar body-frame velocity commands
- `Image` and `CompressedImage` for camera payloads
- `Pose`, `PolicyCommand`, and policy status/control messages

## Dora Node Semantics

`forge-robot` uses fixed input and output names for standard robot nodes:

- input `tick` publishes output `state`
- input `action` accepts a low-level `JointCommand`
- input `master_state` mirrors a leader `JointState` to a position command
- input `locomotion_command` accepts a `LocomotionCommand` when the driver
  supports locomotion

`forge-policy` provides a similar runner pattern for policy adapters. The runner
handles ticks, proprioceptive state, image caching, and policy lifecycle
commands so algorithm code can focus on inference and command generation.

## Configuration

Logging can be configured with environment variables:

- `FORGE_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`
- `FORGE_LOG_FILE`: optional path for file logging
- `FORGE_LOG_CONSOLE`: `true` or `false`
- `FORGE_LOG_STREAM`: `stdout` or `stderr`

See `.env.example` for a non-secret example.

## Contributing

See `CONTRIBUTING.md` for development setup and contribution guidelines. Please
report security issues using the process in `SECURITY.md`.

## License

Forge is licensed under the Apache License, Version 2.0. See `LICENSE` for
details.
