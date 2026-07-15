#include "forge_robot/forge_robot.hpp"

#include <algorithm>
#include <map>
#include <utility>

namespace forge_robot {
namespace {

double ClipSymmetric(double value, bool has_limit, double limit) {
  if (!has_limit) {
    return value;
  }
  return std::max(std::min(value, limit), -limit);
}

std::map<std::string, double> FieldByName(
    const std::vector<std::string>& names,
    const std::vector<double>& values) {
  std::map<std::string, double> out;
  if (values.empty()) {
    return out;
  }
  auto count = std::min(names.size(), values.size());
  for (std::size_t i = 0; i < count; ++i) {
    out[names[i]] = values[i];
  }
  return out;
}

std::vector<double> OrderedField(
    const std::vector<std::string>& names,
    const std::map<std::string, double>& values_by_name) {
  if (values_by_name.empty()) {
    return {};
  }
  std::vector<double> out;
  out.reserve(names.size());
  for (const auto& name : names) {
    auto it = values_by_name.find(name);
    if (it != values_by_name.end()) {
      out.push_back(it->second);
    }
  }
  return out;
}

}  // namespace

RobotError::RobotError(const std::string& message) : std::runtime_error(message) {}

RobotArrowSchemaError::RobotArrowSchemaError(const std::string& message) : RobotError(message) {}

std::vector<std::string> RobotDriver::JointOrder() const { return {}; }

ActuatorSpec MakeActuatorSpec(std::string name, ActuatorKind kind) {
  ActuatorSpec spec;
  spec.name = std::move(name);
  spec.kind = kind;

  switch (kind) {
    case ActuatorKind::Revolute:
    case ActuatorKind::Continuous:
      spec.position_unit = "radians";
      spec.velocity_unit = "radians/s";
      spec.acceleration_unit = "radians/s^2";
      spec.effort_unit = "Nm";
      break;
    case ActuatorKind::Prismatic:
      spec.position_unit = "meters";
      spec.velocity_unit = "meters/s";
      spec.acceleration_unit = "meters/s^2";
      spec.effort_unit = "unitless";
      break;
    case ActuatorKind::Other:
      spec.position_unit = "unitless";
      spec.velocity_unit = "unitless";
      spec.acceleration_unit = "unitless";
      spec.effort_unit = "unitless";
      break;
  }

  return spec;
}

std::vector<std::string> JointOrder(const std::vector<ActuatorSpec>& specs) {
  std::vector<std::string> order;
  order.reserve(specs.size());
  for (const auto& spec : specs) {
    order.push_back(spec.name);
  }
  return order;
}

std::map<std::string, ActuatorSpec> SpecsByName(const std::vector<ActuatorSpec>& specs) {
  std::map<std::string, ActuatorSpec> out;
  for (const auto& spec : specs) {
    out.emplace(spec.name, spec);
  }
  return out;
}

arrow::Result<forge_msgs::JointCommand> ClipAndValidateCommand(
    const forge_msgs::JointCommand& command,
    const std::map<std::string, ActuatorSpec>& specs) {
  ARROW_RETURN_NOT_OK(command.Validate());

  std::vector<std::string> names;
  auto position = FieldByName(command.name, command.position);
  auto velocity = FieldByName(command.name, command.velocity);
  auto effort = FieldByName(command.name, command.effort);
  auto kp = FieldByName(command.name, command.kp);
  auto kd = FieldByName(command.name, command.kd);

  for (const auto& name : command.name) {
    auto it = specs.find(name);
    if (it == specs.end()) {
      return arrow::Status::Invalid("missing actuator spec for joint: ", name);
    }
    const auto& spec = it->second;
    names.push_back(name);

    auto pos_it = position.find(name);
    if (pos_it != position.end() && spec.kind != ActuatorKind::Continuous) {
      if (spec.has_min_position) {
        pos_it->second = std::max(pos_it->second, spec.min_position);
      }
      if (spec.has_max_position) {
        pos_it->second = std::min(pos_it->second, spec.max_position);
      }
    }

    auto vel_it = velocity.find(name);
    if (vel_it != velocity.end()) {
      vel_it->second = ClipSymmetric(vel_it->second, spec.has_max_velocity, spec.max_velocity);
    }

    auto effort_it = effort.find(name);
    if (effort_it != effort.end()) {
      effort_it->second = ClipSymmetric(effort_it->second, spec.has_max_effort, spec.max_effort);
    }
  }

  forge_msgs::JointCommand clipped{
      names,
      command.mode,
      OrderedField(names, position),
      OrderedField(names, velocity),
      OrderedField(names, effort),
      OrderedField(names, kp),
      OrderedField(names, kd),
  };
  ARROW_RETURN_NOT_OK(clipped.Validate());
  return clipped;
}

arrow::Result<forge_msgs::JointCommand> ClipAndValidatePositionCommand(
    const forge_msgs::JointCommand& command,
    const std::map<std::string, ActuatorSpec>& specs) {
  return ClipAndValidateCommand(command, specs);
}

}  // namespace forge_robot
