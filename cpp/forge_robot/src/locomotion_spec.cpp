#include "forge_robot/forge_robot.hpp"

#include <algorithm>
#include <cmath>

namespace forge_robot {
namespace {

double ClipSymmetric(double value, bool has_limit, double limit) {
  if (!has_limit) {
    return value;
  }
  return std::max(std::min(value, limit), -limit);
}

}  // namespace

arrow::Status ValidateLocomotionSpec(const LocomotionSpec& spec) {
  if (spec.has_max_vx && spec.max_vx < 0.0) {
    return arrow::Status::Invalid("max_vx must be non-negative");
  }
  if (spec.has_max_vy && spec.max_vy < 0.0) {
    return arrow::Status::Invalid("max_vy must be non-negative");
  }
  if (spec.has_max_wz && spec.max_wz < 0.0) {
    return arrow::Status::Invalid("max_wz must be non-negative");
  }
  return arrow::Status::OK();
}

arrow::Result<forge_msgs::LocomotionCommand> ClipAndValidateLocomotionCommand(
    const forge_msgs::LocomotionCommand& command,
    const LocomotionSpec& spec) {
  ARROW_RETURN_NOT_OK(ValidateLocomotionSpec(spec));

  forge_msgs::LocomotionCommand clipped{
      ClipSymmetric(command.vx, spec.has_max_vx, spec.max_vx),
      spec.allow_lateral ? ClipSymmetric(command.vy, spec.has_max_vy, spec.max_vy) : 0.0,
      ClipSymmetric(command.wz, spec.has_max_wz, spec.max_wz),
  };
  ARROW_RETURN_NOT_OK(clipped.Validate());
  return clipped;
}

}  // namespace forge_robot
