# C++ forge_robot

`cpp/forge_robot` provides C++ robot driver interfaces, safety clipping helpers,
Arrow validation, and an optional Dora C++ node runner for standard Forge robot
nodes.

## Driver Contract

Implement `forge_robot::RobotDriver` for hardware-specific drivers:

- `Connect()` establishes hardware communication and enables the robot.
- `Disconnect()` releases hardware resources and should be safe to call during
  shutdown.
- `GetState()` returns a `forge_msgs::JointState`.
- `SetCommand()` consumes a `forge_msgs::JointCommand`.
- `JointOrder()` may return a fixed joint order for runner-side validation.

Drivers that support planar base velocity commands can also inherit
`forge_robot::LocomotionRobotDriver` and implement `SetLocomotionCommand()`.

## Dora Semantics

The optional Dora runner mirrors the Python `forge_robot` node loop:

- input `tick` reads `driver.GetState()` and publishes output `state`.
- input `action` parses `JointCommand` and calls `driver.SetCommand(...)`.
- input `master_state` parses leader `JointState`, converts it to a position
  `JointCommand`, then calls `driver.SetCommand(...)`.
- input `locomotion_command` parses `LocomotionCommand` and calls
  `SetLocomotionCommand(...)` when the driver supports locomotion.
- `STOP`, all inputs closed, upstream failure, or Dora error exits the loop and
  ensures `Disconnect()` is called.

The driver interfaces, clipping helpers, and Arrow validation do not depend on
Dora headers. `RunDoraRobotNode()` is compiled only when
`FORGE_ROBOT_CPP_WITH_DORA=ON`. The Dora C++ API is generated from Dora
`v0.4.1` with CXX bridge sources, so the default build path is pinned to that
tag instead of Dora `main`.

## Build

Build the core library and tests:

```bash
cmake -S cpp/forge_robot -B cpp/forge_robot/build
cmake --build cpp/forge_robot/build
ctest --test-dir cpp/forge_robot/build --output-on-failure
```

Build and compile-link validate the Dora runner against Dora `v0.4.1`:

```bash
cmake -S cpp/forge_robot -B cpp/forge_robot/build-dora \
  -DFORGE_ROBOT_CPP_WITH_DORA=ON \
  -DFORGE_ROBOT_CPP_BUILD_TESTS=ON
cmake --build cpp/forge_robot/build-dora --target forge_robot_dora_runner_compile
```

The command above downloads Dora from GitHub at tag `v0.4.1` and builds
`dora-node-api-cxx` with Cargo. To avoid downloading during configure/build,
provide a local Dora `v0.4.1` checkout:

```bash
git clone --branch v0.4.1 https://github.com/dora-rs/dora.git /path/to/dora-v0.4.1
cmake -S cpp/forge_robot -B cpp/forge_robot/build-dora \
  -DFORGE_ROBOT_CPP_WITH_DORA=ON \
  -DDORA_ROOT_DIR=/path/to/dora-v0.4.1
cmake --build cpp/forge_robot/build-dora --target forge_robot_dora_runner_compile
```

If your environment already provides generated CXX artifacts, pass
`DORA_CXX_INCLUDE_DIR`, `DORA_CXX_LIBRARY`, and `DORA_CXX_BRIDGE_SOURCE`
directly. Dora's CXX API requires the generated bridge source to be compiled
with the C++ target.

## FetchContent

Downstream C++ packages can consume `forge_robot` directly from the Forge Git
repository:

```cmake
include(FetchContent)

FetchContent_Declare(
  forge_robot
  GIT_REPOSITORY https://gitlab.ex-ai.cn/meta-emt/framework/forge.git
  GIT_TAG dev
  SOURCE_SUBDIR cpp/forge_robot
)
FetchContent_MakeAvailable(forge_robot)

target_link_libraries(my_robot_node PRIVATE forge_robot::forge_robot)
```

Then include the umbrella header and implement the driver contract:

```cpp
#include <forge_robot/forge_robot.hpp>

class MyDriver : public forge_robot::RobotDriver {
 public:
  void Connect() override;
  void Disconnect() override;
  forge_msgs::JointState GetState() override;
  void SetCommand(const forge_msgs::JointCommand& command) override;
  std::vector<std::string> JointOrder() const override;
};
```

Keep `FORGE_ROBOT_CPP_WITH_DORA` off when a package only needs driver
interfaces, safety clipping, or Arrow validation. This avoids pulling in
Rust/Cargo and the Dora C++ API build.

When enabling the Dora runner from a consumer project, pass
`FORGE_ROBOT_CPP_WITH_DORA=ON`. The default path builds against Dora `v0.4.1`;
pass `DORA_ROOT_DIR=/path/to/dora-v0.4.1` to use an existing local checkout.

```bash
cmake -S . -B build \
  -DFORGE_ROBOT_CPP_WITH_DORA=ON \
  -DDORA_ROOT_DIR=/path/to/dora-v0.4.1
```
