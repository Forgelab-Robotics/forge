#pragma once

#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <arrow/api.h>

#include <forge_common/forge_common.hpp>
#include <forge_msgs/forge_msgs.hpp>

namespace forge_robot {

class RobotError : public std::runtime_error {
 public:
  explicit RobotError(const std::string& message);
};

class RobotArrowSchemaError : public RobotError {
 public:
  explicit RobotArrowSchemaError(const std::string& message);
};

class RobotDriver {
 public:
  virtual ~RobotDriver() = default;

  virtual void Connect() = 0;
  virtual void Disconnect() = 0;
  virtual forge_msgs::JointState GetState() = 0;
  virtual void SetCommand(const forge_msgs::JointCommand& command) = 0;
  virtual std::vector<std::string> JointOrder() const;
};

class LocomotionRobotDriver {
 public:
  virtual ~LocomotionRobotDriver() = default;
  virtual void SetLocomotionCommand(const forge_msgs::LocomotionCommand& command) = 0;
};

enum class ActuatorKind {
  Revolute,
  Continuous,
  Prismatic,
  Other,
};

enum class ControlMode {
  Position,
  Velocity,
  Effort,
  Hybrid,
};

struct ActuatorSpec {
  std::string name;
  ActuatorKind kind = ActuatorKind::Other;
  ControlMode mode = ControlMode::Position;
  std::string position_unit;
  std::string velocity_unit;
  std::string acceleration_unit;
  std::string effort_unit;
  bool has_min_position = false;
  bool has_max_position = false;
  bool has_max_velocity = false;
  bool has_max_acceleration = false;
  bool has_max_effort = false;
  double min_position = 0.0;
  double max_position = 0.0;
  double max_velocity = 0.0;
  double max_acceleration = 0.0;
  double max_effort = 0.0;
};

ActuatorSpec MakeActuatorSpec(std::string name, ActuatorKind kind);
std::vector<std::string> JointOrder(const std::vector<ActuatorSpec>& specs);
std::map<std::string, ActuatorSpec> SpecsByName(const std::vector<ActuatorSpec>& specs);
arrow::Result<forge_msgs::JointCommand> ClipAndValidateCommand(
    const forge_msgs::JointCommand& command,
    const std::map<std::string, ActuatorSpec>& specs);
arrow::Result<forge_msgs::JointCommand> ClipAndValidatePositionCommand(
    const forge_msgs::JointCommand& command,
    const std::map<std::string, ActuatorSpec>& specs);

struct LocomotionSpec {
  bool has_max_vx = false;
  bool has_max_vy = false;
  bool has_max_wz = false;
  double max_vx = 0.0;
  double max_vy = 0.0;
  double max_wz = 0.0;
  bool allow_lateral = true;
};

arrow::Status ValidateLocomotionSpec(const LocomotionSpec& spec);
arrow::Result<forge_msgs::LocomotionCommand> ClipAndValidateLocomotionCommand(
    const forge_msgs::LocomotionCommand& command,
    const LocomotionSpec& spec);

arrow::Result<std::shared_ptr<arrow::RecordBatch>> ValidateRobotControlRecordBatch(
    const arrow::RecordBatch& batch,
    const std::vector<std::string>& joint_order,
    bool strict_extra_columns = false);
arrow::Result<std::shared_ptr<arrow::RecordBatch>> ValidateRobotStateRecordBatch(
    const arrow::RecordBatch& batch,
    const std::vector<std::string>& joint_order,
    bool strict_extra_columns = false);
forge_msgs::JointCommand JointStateToCommand(const forge_msgs::JointState& master_state);

struct RobotNodeOptions {
  std::vector<std::string> joint_order;
  bool is_follower = true;
  bool debug = false;
  bool validate_control_arrow = true;
  bool strict_extra_arrow_columns = false;
};

void HandleRobotInput(
    const std::string& input_id,
    const arrow::RecordBatch& batch,
    RobotDriver& driver,
    const RobotNodeOptions& options);

#if defined(FORGE_ROBOT_CPP_WITH_DORA)
int RunDoraRobotNode(RobotDriver& driver, const RobotNodeOptions& options = {});
#endif

}  // namespace forge_robot
