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
- `SetCommand()` consumes a sparse `forge_msgs::JointCommand`: only joints listed in `name` are updated, and omitted joints retain their prior target.
- `JointOrder()` may return a fixed joint order for runner-side validation.

Drivers that support planar base velocity commands can also inherit
`forge_robot::LocomotionRobotDriver` and implement `SetLocomotionCommand()`.

## Dora Semantics

The optional Dora runner mirrors the Python `forge_robot` node loop:

- input `tick` reads `driver.GetState()` and publishes output `state`.
- input `action` or `action/<source>` parses a sparse `JointCommand` and calls `driver.SetCommand(...)`; namespaced inputs allow disjoint arm and gripper streams, while sources that can command the same joint still require explicit arbitration.
- input `master_state` parses leader `JointState`, converts it to a position
  `JointCommand`, then calls `driver.SetCommand(...)`.
- input `locomotion_command` parses `LocomotionCommand` and calls
  `SetLocomotionCommand(...)` when the driver supports locomotion.
- `STOP`, all inputs closed, upstream failure, or Dora error exits the loop and
  ensures `Disconnect()` is called.

The driver interfaces, clipping helpers, and Arrow validation do not depend on
Dora headers. `RunDoraRobotNode()` is compiled only when
`FORGE_ROBOT_CPP_WITH_DORA=ON`. The runner supports the Dora 1.x API line. For
reproducibility, the default build generates CXX bridge sources from the
SHA256-pinned Dora `v1.0.1` archive instead of Dora `main`.

## Build

Build the core library and tests:

```bash
cmake -S cpp/forge_robot -B cpp/forge_robot/build
cmake --build cpp/forge_robot/build
ctest --test-dir cpp/forge_robot/build --output-on-failure
```

Build and compile-link validate the Dora 1.x runner against the current pinned
baseline, Dora `v1.0.1`:

```bash
cmake -S cpp/forge_robot -B cpp/forge_robot/build-dora \
  -DFORGE_ROBOT_CPP_WITH_DORA=ON \
  -DFORGE_ROBOT_CPP_BUILD_TESTS=ON
cmake --build cpp/forge_robot/build-dora --target forge_robot_dora_runner_compile
```

The command above downloads the SHA256-pinned Dora `v1.0.1` source archive and
builds `dora-node-api-cxx` with Cargo. To avoid downloading during
configure/build, provide a compatible local Dora 1.x checkout:

```bash
git clone --branch v1.0.1 https://github.com/dora-rs/dora.git /path/to/dora-v1.0.1
cmake -S cpp/forge_robot -B cpp/forge_robot/build-dora \
  -DFORGE_ROBOT_CPP_WITH_DORA=ON \
  -DDORA_ROOT_DIR=/path/to/dora-v1.0.1
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
  GIT_REPOSITORY https://gitlab.ex-ai.cn/PhyAgentOS/framework/forge.git
  GIT_TAG forge-robot-v2.0.0
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
`FORGE_ROBOT_CPP_WITH_DORA=ON`. The default path builds against the pinned Dora
`v1.0.1` baseline; pass `DORA_ROOT_DIR` to use another compatible Dora 1.x
checkout.

```bash
cmake -S . -B build \
  -DFORGE_ROBOT_CPP_WITH_DORA=ON \
  -DDORA_ROOT_DIR=/path/to/dora-v1.0.1
```
