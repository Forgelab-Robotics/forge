# forge-common

Shared Python utilities for Forge packages.

The package is intentionally lightweight and dependency-free so Forge packages
can share common infrastructure without pulling in robotics-specific
dependencies. It currently provides logging helpers; future releases may add
other cross-package utilities.

## Logging Usage

```python
from forge_common import configure_from_env, get_logger

configure_from_env()
logger = get_logger(__name__)
logger.info("Forge component started")
```

## Environment Variables

- `FORGE_LOG_LEVEL`: log level, such as `DEBUG`, `INFO`, `WARNING`, `ERROR`, or
  `CRITICAL`
- `FORGE_LOG_FILE`: optional file path for log output
- `FORGE_LOG_CONSOLE`: whether console logging is enabled (`true` or `false`)
- `FORGE_LOG_STREAM`: console stream (`stdout` or `stderr`)

Use `configure_from_env()` in applications or node entry points, then call
`get_logger(__name__)` inside individual modules.
