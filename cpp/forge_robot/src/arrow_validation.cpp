#include "forge_robot/forge_robot.hpp"

#include <set>

namespace forge_robot {
namespace {

bool IsActionInput(const std::string& input_id) {
  constexpr char kActionPrefix[] = "action/";
  constexpr std::size_t kActionPrefixLength = sizeof(kActionPrefix) - 1;
  return input_id == "action" ||
         (input_id.size() > kActionPrefixLength &&
          input_id.compare(0, kActionPrefixLength, kActionPrefix) == 0);
}

bool HasColumn(const arrow::RecordBatch& batch, const std::string& name) {
  return batch.schema()->GetFieldIndex(name) >= 0;
}

arrow::Status RequireColumns(
    const arrow::RecordBatch& batch,
    const std::vector<std::string>& required) {
  for (const auto& name : required) {
    if (!HasColumn(batch, name)) {
      return arrow::Status::Invalid("missing required column: ", name);
    }
  }
  return arrow::Status::OK();
}

arrow::Status RequireJointOrder(
    const std::vector<std::string>& names,
    const std::vector<std::string>& joint_order,
    bool strict_extra_columns) {
  std::set<std::string> available(names.begin(), names.end());
  for (const auto& name : joint_order) {
    if (available.find(name) == available.end()) {
      return arrow::Status::Invalid("missing required joint: ", name);
    }
  }

  if (strict_extra_columns) {
    std::set<std::string> expected(joint_order.begin(), joint_order.end());
    for (const auto& name : names) {
      if (expected.find(name) == expected.end()) {
        return arrow::Status::Invalid("unexpected joint: ", name);
      }
    }
  }

  return arrow::Status::OK();
}

}  // namespace

arrow::Result<std::shared_ptr<arrow::RecordBatch>> ValidateRobotControlRecordBatch(
    const arrow::RecordBatch& batch,
    const std::vector<std::string>& joint_order,
    bool strict_extra_columns) {
  if (joint_order.empty()) {
    return arrow::Status::Invalid("joint_order must not be empty");
  }
  if (batch.num_rows() == 0) {
    return arrow::Status::Invalid("RecordBatch must not be empty");
  }

  ARROW_RETURN_NOT_OK(RequireColumns(
      batch, {"name", "position", "velocity", "effort", "kp", "kd"}));
  ARROW_ASSIGN_OR_RAISE(auto command, forge_msgs::JointCommand::FromRecordBatch(batch));
  if (strict_extra_columns) {
    std::set<std::string> expected(joint_order.begin(), joint_order.end());
    for (const auto& name : command.name) {
      if (expected.find(name) == expected.end()) {
        return arrow::Status::Invalid("unexpected joint: ", name);
      }
    }
  }
  return batch.Slice(0, batch.num_rows());
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> ValidateRobotStateRecordBatch(
    const arrow::RecordBatch& batch,
    const std::vector<std::string>& joint_order,
    bool strict_extra_columns) {
  if (batch.num_rows() == 0) {
    return arrow::Status::Invalid("RecordBatch must not be empty");
  }

  ARROW_RETURN_NOT_OK(RequireColumns(batch, {"name", "position", "velocity", "effort"}));
  ARROW_ASSIGN_OR_RAISE(auto state, forge_msgs::JointState::FromRecordBatch(batch));
  ARROW_RETURN_NOT_OK(RequireJointOrder(state.name, joint_order, strict_extra_columns));
  return batch.Slice(0, batch.num_rows());
}

forge_msgs::JointCommand JointStateToCommand(const forge_msgs::JointState& master_state) {
  return forge_msgs::JointCommand{
      master_state.name,
      "position",
      master_state.position,
      {},
      {},
      {},
      {},
  };
}

void HandleRobotInput(
    const std::string& input_id,
    const arrow::RecordBatch& batch,
    RobotDriver& driver,
    const RobotNodeOptions& options) {
  auto logger = forge_common::GetLogger("forge_robot");

  if (!options.is_follower) {
    return;
  }

  if (IsActionInput(input_id)) {
    if (options.joint_order.empty()) {
      logger.Error("ignored action: joint_order must not be empty");
      return;
    }
    if (options.validate_control_arrow) {
      auto validation = ValidateRobotControlRecordBatch(
          batch, options.joint_order, options.strict_extra_arrow_columns);
      if (!validation.ok()) {
        logger.Error("ignored invalid action Arrow schema: " + validation.status().ToString());
        return;
      }
    }
    auto command = forge_msgs::JointCommand::FromRecordBatch(batch);
    if (!command.ok()) {
      logger.Error("ignored invalid action payload: " + command.status().ToString());
      return;
    }
    driver.SetCommand(*command);
    return;
  }

  if (input_id == "master_state") {
    if (options.joint_order.empty()) {
      logger.Error("ignored master_state: joint_order must not be empty");
      return;
    }
    auto state = forge_msgs::JointState::FromRecordBatch(batch);
    if (!state.ok()) {
      logger.Error("ignored invalid master_state payload: " + state.status().ToString());
      return;
    }
    driver.SetCommand(JointStateToCommand(*state));
    return;
  }

  if (input_id == "locomotion_command") {
    auto* locomotion_driver = dynamic_cast<LocomotionRobotDriver*>(&driver);
    if (locomotion_driver == nullptr) {
      logger.Warning("ignored locomotion_command: driver does not support locomotion");
      return;
    }
    auto command = forge_msgs::LocomotionCommand::FromRecordBatch(batch);
    if (!command.ok()) {
      logger.Error("ignored invalid locomotion_command payload: " + command.status().ToString());
      return;
    }
    locomotion_driver->SetLocomotionCommand(*command);
  }
}

}  // namespace forge_robot
