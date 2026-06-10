# Security Policy

## Supported Versions

Forge is currently pre-1.0 alpha software. Security fixes are made on the main
development branch until a stable release policy is published.

## Reporting a Vulnerability

Please do not report security vulnerabilities through public issues.

Until a dedicated security contact is published, report vulnerabilities through
the private contact channel listed on the public repository profile or by
contacting the maintainers directly. Include as much detail as possible:

- A description of the vulnerability and affected package or crate.
- Reproduction steps or proof-of-concept code, if available.
- Potential impact.
- Suggested mitigations, if known.

Maintainers should acknowledge reports as soon as possible, investigate the
issue, and coordinate disclosure timing with the reporter.

## Scope

Security-sensitive areas include:

- Message parsing and Arrow serialization.
- Dora node input handling.
- Robot command validation and actuator limit enforcement.
- Device CLI JSON envelopes.
- Dependency and supply-chain configuration.

Do not include private hardware credentials, API tokens, SSH keys, or internal
infrastructure URLs in issues, pull requests, logs, or examples.
