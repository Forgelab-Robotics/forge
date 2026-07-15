# forge_common C++

Lightweight C++ shared utilities for Forge packages.

The C++ package currently provides standard-library-only logging helpers. It
does not depend on `spdlog` or other third-party logging libraries.

## Usage

```cpp
#include <forge_common/forge_common.hpp>

int main() {
  forge_common::ConfigureFromEnv();
  auto logger = forge_common::GetLogger("my-node");
  logger.Info("Forge component started");
}
```

For Rust-style one-time initialization:

```cpp
forge_common::InitLogging("my-node");
```

## Environment Variables

- `FORGE_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, or `OFF`
- `FORGE_LOG_FILE`: optional file path for log output
- `FORGE_LOG_CONSOLE`: whether console logging is enabled (`true` or `false`)
- `FORGE_LOG_STREAM`: console stream (`stdout` or `stderr`)

## CMake

```cmake
add_subdirectory(path/to/forge/cpp/forge_common)
target_link_libraries(my_app PRIVATE forge_common::forge_common)
```

Or use `FetchContent` with the Forge git repository and
`SOURCE_SUBDIR cpp/forge_common`.
