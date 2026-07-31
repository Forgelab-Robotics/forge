#include <cassert>
#include <cmath>
#include <iostream>
#include <vector>

#include "forge_robot/forge_robot.hpp"

namespace {

class FakeDriver : public forge_robot::RobotDriver {
 public:
  void Connect() override { connected = true; }
  void Disconnect() override { connected = false; }
  forge_msgs::JointState GetState() override {
    return forge_msgs::JointState{{"shoulder", "elbow"}, {1.0, 2.0}, {0.1, 0.2}, {}};
  }
  void SetCommand(const forge_msgs::JointCommand& command) override {
    ++command_count;
    last_command = command;
  }
  std::vector<std::string> JointOrder() const override { return {"shoulder", "elbow"}; }

  bool connected = false;
  int command_count = 0;
  forge_msgs::JointCommand last_command;
};

class FakeLocomotionDriver : public FakeDriver, public forge_robot::LocomotionRobotDriver {
 public:
  void SetLocomotionCommand(const forge_msgs::LocomotionCommand& command) override {
    ++locomotion_count;
    last_locomotion = command;
  }

  int locomotion_count = 0;
  forge_msgs::LocomotionCommand last_locomotion;
};

bool Near(double lhs, double rhs) {
  return std::fabs(lhs - rhs) < 1e-9;
}

void TestActuatorDefaultsAndClipping() {
  auto shoulder = forge_robot::MakeActuatorSpec("shoulder", forge_robot::ActuatorKind::Revolute);
  assert(shoulder.position_unit == "radians");
  shoulder.has_min_position = true;
  shoulder.min_position = -1.0;
  shoulder.has_max_position = true;
  shoulder.max_position = 1.0;
  shoulder.has_max_velocity = true;
  shoulder.max_velocity = 2.0;
  shoulder.has_max_effort = true;
  shoulder.max_effort = 3.0;

  auto wheel = forge_robot::MakeActuatorSpec("wheel", forge_robot::ActuatorKind::Continuous);
  wheel.has_min_position = true;
  wheel.min_position = -0.5;
  wheel.has_max_position = true;
  wheel.max_position = 0.5;

  auto specs = forge_robot::SpecsByName({shoulder, wheel});
  forge_msgs::JointCommand command{
      {"shoulder", "wheel"},
      "hybrid",
      {5.0, 42.0},
      {5.0, -5.0},
      {5.0, -5.0},
      {10.0, 20.0},
      {1.0, 2.0},
  };

  auto clipped = forge_robot::ClipAndValidateCommand(command, specs);
  assert(clipped.ok());
  assert((*clipped).name == std::vector<std::string>({"shoulder", "wheel"}));
  assert(Near((*clipped).position[0], 1.0));
  assert(Near((*clipped).position[1], 42.0));
  assert(Near((*clipped).velocity[0], 2.0));
  assert(Near((*clipped).effort[0], 3.0));
}

void TestLocomotionClipping() {
  forge_robot::LocomotionSpec spec;
  spec.has_max_vx = true;
  spec.max_vx = 1.0;
  spec.has_max_vy = true;
  spec.max_vy = 0.5;
  spec.has_max_wz = true;
  spec.max_wz = 2.0;
  spec.allow_lateral = false;

  auto clipped = forge_robot::ClipAndValidateLocomotionCommand({2.0, 1.0, -3.0}, spec);
  assert(clipped.ok());
  assert(Near((*clipped).vx, 1.0));
  assert(Near((*clipped).vy, 0.0));
  assert(Near((*clipped).wz, -2.0));
}

void TestArrowValidationAndConversion() {
  forge_msgs::JointCommand command{
      {"shoulder", "elbow"},
      "position",
      {1.0, 2.0},
      {},
      {},
      {},
      {},
  };
  auto batch = command.ToRecordBatch();
  assert(batch.ok());
  auto valid = forge_robot::ValidateRobotControlRecordBatch(**batch, {"shoulder", "elbow"});
  assert(valid.ok());
  forge_msgs::JointCommand sparse_command{
      {"shoulder"}, "position", {1.0}, {}, {}, {}, {}};
  auto sparse_batch = sparse_command.ToRecordBatch();
  assert(sparse_batch.ok());
  auto sparse = forge_robot::ValidateRobotControlRecordBatch(
      **sparse_batch, {"shoulder", "elbow"}, true);
  assert(sparse.ok());
  auto unexpected = forge_robot::ValidateRobotControlRecordBatch(
      **batch, {"shoulder", "wrist"}, true);
  assert(!unexpected.ok());

  forge_msgs::JointState state{{"shoulder", "elbow"}, {3.0, 4.0}, {}, {}};
  auto mirror = forge_robot::JointStateToCommand(state);
  assert(mirror.mode == "position");
  assert(mirror.name == state.name);
  assert(mirror.position == state.position);
  assert(mirror.velocity.empty());
}

void TestHandleRobotInput() {
  forge_robot::RobotNodeOptions options;
  options.joint_order = {"shoulder", "elbow", "gripper"};
  options.strict_extra_arrow_columns = true;

  FakeDriver driver;
  forge_msgs::JointCommand command{
      {"shoulder", "elbow"},
      "position",
      {1.0, 2.0},
      {},
      {},
      {},
      {},
  };
  auto command_batch = command.ToRecordBatch();
  assert(command_batch.ok());
  forge_robot::HandleRobotInput("action", **command_batch, driver, options);
  assert(driver.command_count == 1);
  assert(driver.last_command.position == std::vector<double>({1.0, 2.0}));
  forge_msgs::JointCommand arm_command{
      {"shoulder", "elbow"}, "position", {1.5, 2.5}, {}, {}, {}, {}};
  auto arm_batch = arm_command.ToRecordBatch();
  assert(arm_batch.ok());
  assert((*arm_batch)->schema()->GetFieldIndex("goal_id") == -1);
  assert((*arm_batch)->schema()->GetFieldIndex("goal_status") == -1);
  forge_robot::HandleRobotInput("action/arm", **arm_batch, driver, options);
  assert(driver.command_count == 2);
  assert(driver.last_command.name == std::vector<std::string>({"shoulder", "elbow"}));
  assert(driver.last_command.position == std::vector<double>({1.5, 2.5}));
  assert(driver.last_command.effort.empty());

  forge_msgs::JointCommand gripper_command{
      {"gripper"}, "effort", {}, {}, {4.0}, {}, {}};
  auto gripper_batch = gripper_command.ToRecordBatch();
  assert(gripper_batch.ok());
  assert((*gripper_batch)->schema()->GetFieldIndex("goal_id") == -1);
  assert((*gripper_batch)->schema()->GetFieldIndex("goal_status") == -1);
  forge_robot::HandleRobotInput("action/gripper", **gripper_batch, driver, options);
  assert(driver.command_count == 3);
  assert(driver.last_command.name == std::vector<std::string>({"gripper"}));
  assert(driver.last_command.position.empty());
  assert(driver.last_command.effort == std::vector<double>({4.0}));

  forge_robot::HandleRobotInput("action/", **gripper_batch, driver, options);
  forge_robot::HandleRobotInput("actions/gripper", **gripper_batch, driver, options);
  assert(driver.command_count == 3);

  forge_msgs::JointState state{{"shoulder", "elbow"}, {3.0, 4.0}, {}, {}};
  auto state_batch = state.ToRecordBatch();
  assert(state_batch.ok());
  forge_robot::HandleRobotInput("master_state", **state_batch, driver, options);
  assert(driver.command_count == 4);
  assert(driver.last_command.mode == "position");
  assert(driver.last_command.position == std::vector<double>({3.0, 4.0}));

  FakeLocomotionDriver locomotion_driver;
  auto locomotion_batch = forge_msgs::LocomotionCommand{0.1, 0.2, 0.3}.ToRecordBatch();
  assert(locomotion_batch.ok());
  forge_robot::HandleRobotInput("locomotion_command", **locomotion_batch, locomotion_driver, options);
  assert(locomotion_driver.locomotion_count == 1);
  assert(Near(locomotion_driver.last_locomotion.vy, 0.2));
}

}  // namespace

int main() {
  TestActuatorDefaultsAndClipping();
  TestLocomotionClipping();
  TestArrowValidationAndConversion();
  TestHandleRobotInput();
  std::cout << "forge_robot C++ tests passed\n";
  return 0;
}
