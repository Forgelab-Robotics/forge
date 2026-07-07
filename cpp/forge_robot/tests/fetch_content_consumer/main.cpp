#include <cassert>

#include <forge_robot/forge_robot.hpp>

int main() {
  auto spec = forge_robot::MakeActuatorSpec("joint_0", forge_robot::ActuatorKind::Revolute);
  assert(spec.position_unit == "radians");
  return 0;
}
