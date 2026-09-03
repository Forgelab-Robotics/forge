# Security Policy

## Supported Versions

Forge supports the latest release in each package-family line. Security
fixes are prepared on the development branch and released under protected
family tags such as `forge-msgs-v2.0.0`. Historical generic repository-era tags
are not part of these support lines.

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
