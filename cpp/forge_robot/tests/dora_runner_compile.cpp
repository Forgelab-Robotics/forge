#include "forge_robot/forge_robot.hpp"

namespace {

class CompileOnlyDriver : public forge_robot::RobotDriver {
 public:
  void Connect() override {}
  void Disconnect() override {}
  forge_msgs::JointState GetState() override {
    return forge_msgs::JointState{{"joint_0"}, {0.0}, {}, {}};
  }
  void SetCommand(const forge_msgs::JointCommand& /*command*/) override {}
  std::vector<std::string> JointOrder() const override { return {"joint_0"}; }
};

}  // namespace

int main() {
  CompileOnlyDriver driver;
  forge_robot::RobotNodeOptions options;
  options.joint_order = driver.JointOrder();

  auto* runner = &forge_robot::RunDoraRobotNode;
  (void)runner;
  (void)driver;
  (void)options;
  return 0;
}
