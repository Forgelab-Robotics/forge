#include "detail.hpp"

#include <cmath>
#include <cstdint>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace forge_msgs {

using namespace detail;

namespace {

arrow::Status ValidateOptionalFinite(const std::string& name,
                                     const std::optional<double>& value) {
  if (value && !std::isfinite(*value)) {
    return arrow::Status::Invalid(name, " must be finite when specified");
  }
  return arrow::Status::OK();
}

arrow::Status ValidateFiniteValues(const std::string& name,
                                   const std::vector<double>& values) {
  for (double value : values) {
    if (!std::isfinite(value)) {
      return arrow::Status::Invalid(name, " values must be finite");
    }
  }
  return arrow::Status::OK();
}

arrow::Status ValidateScale(const std::string& name, double value) {
  if (!std::isfinite(value) || value <= 0.0 || value > 1.0) {
    return arrow::Status::Invalid(name, " must be finite and in (0, 1]");
  }
  return arrow::Status::OK();
}

arrow::Status ValidateOptionalNonNegative(const std::string& name,
                                          const std::optional<double>& value) {
  if (value && (!std::isfinite(*value) || *value < 0.0)) {
    return arrow::Status::Invalid(name, " must be finite and non-negative when specified");
  }
  return arrow::Status::OK();
}

arrow::Status ValidateOptionalDuration(const std::string& name,
                                       const std::optional<std::int64_t>& value) {
  if (value && *value < 0) {
    return arrow::Status::Invalid(name, " must be non-negative when specified");
  }
  return arrow::Status::OK();
}

arrow::Status ValidateJointNames(const std::vector<std::string>& names, bool allow_empty) {
  if (!allow_empty && names.empty()) {
    return arrow::Status::Invalid("joint_names must contain at least one joint");
  }
  for (const auto& name : names) {
    ARROW_RETURN_NOT_OK(ValidateRequired("joint_names item", name));
  }
  return ValidateUnique("joint_names", names);
}

std::vector<std::shared_ptr<arrow::Field>> JointToleranceFields() {
  return {arrow::field("joint_name", arrow::utf8(), false),
          arrow::field("position", arrow::float64(), true),
          arrow::field("velocity", arrow::float64(), true),
          arrow::field("acceleration", arrow::float64(), true)};
}

std::vector<std::shared_ptr<arrow::Field>> GripperCommandGoalFields() {
  return {arrow::field("position", arrow::float64(), false),
          arrow::field("max_velocity", arrow::float64(), true),
          arrow::field("max_effort", arrow::float64(), true)};
}

std::vector<std::shared_ptr<arrow::Field>> GripperCommandFeedbackFields() {
  return {arrow::field("elapsed_ns", arrow::int64(), false),
          arrow::field("position", arrow::float64(), false),
          arrow::field("velocity", arrow::float64(), true),
          arrow::field("effort", arrow::float64(), true),
          arrow::field("stalled", arrow::boolean(), false),
          arrow::field("reached_goal", arrow::boolean(), false)};
}

std::vector<std::shared_ptr<arrow::Field>> GripperCommandResultFields() {
  return {arrow::field("error_code", arrow::utf8(), false),
          arrow::field("message", arrow::utf8(), false),
          arrow::field("elapsed_ns", arrow::int64(), false),
          arrow::field("position", arrow::float64(), true),
          arrow::field("velocity", arrow::float64(), true),
          arrow::field("effort", arrow::float64(), true),
          arrow::field("stalled", arrow::boolean(), false),
          arrow::field("reached_goal", arrow::boolean(), false)};
}

arrow::Status RequireExactSchema(
    const arrow::RecordBatch& batch,
    const std::vector<std::shared_ptr<arrow::Field>>& expected_fields,
    const std::string& message_name) {
  const auto expected = arrow::schema(expected_fields);
  if (!batch.schema()->Equals(*expected, false)) {
    return arrow::Status::Invalid(message_name, " RecordBatch schema must exactly match ",
                                  expected->ToString(), "; got ",
                                  batch.schema()->ToString());
  }
  return arrow::Status::OK();
}

template <typename Message>
arrow::Result<std::shared_ptr<arrow::Array>> RequiredStruct(const Message& value) {
  ARROW_ASSIGN_OR_RAISE(auto batch, value.ToRecordBatch());
  return StructScalar(*batch);
}

template <typename Message>
arrow::Result<std::shared_ptr<arrow::Array>> MessageStructList(
    const std::vector<Message>& values,
    const std::vector<std::shared_ptr<arrow::Field>>& empty_fields) {
  std::vector<std::shared_ptr<arrow::RecordBatch>> batches;
  batches.reserve(values.size());
  for (const auto& value : values) {
    ARROW_ASSIGN_OR_RAISE(auto batch, value.ToRecordBatch());
    batches.push_back(std::move(batch));
  }
  const auto& fields = batches.empty() ? empty_fields : batches.front()->schema()->fields();
  return StructList(batches, fields);
}

arrow::Result<std::shared_ptr<arrow::Array>> OptionalPoseStruct(
    const std::optional<Pose>& value) {
  const Pose& stored = value ? *value : Pose{};
  ARROW_ASSIGN_OR_RAISE(auto batch, stored.ToRecordBatch());
  return StructScalar(*batch, value.has_value());
}

template <typename Message>
arrow::Result<Message> ReadRequiredMessage(const arrow::RecordBatch& batch,
                                           const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto nested, ReadStruct(batch, name));
  return Message::FromRecordBatch(*nested);
}

arrow::Result<std::optional<Pose>> ReadOptionalPose(const arrow::RecordBatch& batch,
                                                    const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto nested, ReadOptionalStruct(batch, name));
  if (!nested) return std::optional<Pose>{};
  ARROW_ASSIGN_OR_RAISE(auto pose, Pose::FromRecordBatch(**nested));
  return std::optional<Pose>{std::move(pose)};
}

arrow::Status ValidateToleranceList(const std::string& name,
                                    const std::vector<JointTolerance>& tolerances,
                                    const std::set<std::string>& trajectory_names) {
  std::set<std::string> seen;
  for (const auto& tolerance : tolerances) {
    ARROW_RETURN_NOT_OK(tolerance.Validate());
    if (!seen.insert(tolerance.joint_name).second) {
      return arrow::Status::Invalid(name, " joint names must be unique");
    }
    if (trajectory_names.find(tolerance.joint_name) == trajectory_names.end()) {
      return arrow::Status::Invalid(name, " joint names must belong to trajectory.joint_names");
    }
  }
  return arrow::Status::OK();
}

}  // namespace

std::string ToString(FollowJointTrajectoryErrorCode value) {
  switch (value) {
    case FollowJointTrajectoryErrorCode::Success: return "SUCCESS";
    case FollowJointTrajectoryErrorCode::InvalidGoal: return "INVALID_GOAL";
    case FollowJointTrajectoryErrorCode::InvalidJoints: return "INVALID_JOINTS";
    case FollowJointTrajectoryErrorCode::Busy: return "BUSY";
    case FollowJointTrajectoryErrorCode::NoFreshRobotState: return "NO_FRESH_ROBOT_STATE";
    case FollowJointTrajectoryErrorCode::StartStateMismatch: return "START_STATE_MISMATCH";
    case FollowJointTrajectoryErrorCode::PathToleranceViolated: return "PATH_TOLERANCE_VIOLATED";
    case FollowJointTrajectoryErrorCode::GoalToleranceViolated: return "GOAL_TOLERANCE_VIOLATED";
    case FollowJointTrajectoryErrorCode::FeedbackStale: return "FEEDBACK_STALE";
    case FollowJointTrajectoryErrorCode::ExecutionTimedOut: return "EXECUTION_TIMED_OUT";
    case FollowJointTrajectoryErrorCode::HardwareFault: return "HARDWARE_FAULT";
    case FollowJointTrajectoryErrorCode::Canceled: return "CANCELED";
    case FollowJointTrajectoryErrorCode::InternalError: return "INTERNAL_ERROR";
  }
  return {};
}

arrow::Result<FollowJointTrajectoryErrorCode> FollowJointTrajectoryErrorCodeFromString(
    const std::string& value) {
  if (value == "SUCCESS") return FollowJointTrajectoryErrorCode::Success;
  if (value == "INVALID_GOAL") return FollowJointTrajectoryErrorCode::InvalidGoal;
  if (value == "INVALID_JOINTS") return FollowJointTrajectoryErrorCode::InvalidJoints;
  if (value == "BUSY") return FollowJointTrajectoryErrorCode::Busy;
  if (value == "NO_FRESH_ROBOT_STATE") return FollowJointTrajectoryErrorCode::NoFreshRobotState;
  if (value == "START_STATE_MISMATCH") return FollowJointTrajectoryErrorCode::StartStateMismatch;
  if (value == "PATH_TOLERANCE_VIOLATED") {
    return FollowJointTrajectoryErrorCode::PathToleranceViolated;
  }
  if (value == "GOAL_TOLERANCE_VIOLATED") {
    return FollowJointTrajectoryErrorCode::GoalToleranceViolated;
  }
  if (value == "FEEDBACK_STALE") return FollowJointTrajectoryErrorCode::FeedbackStale;
  if (value == "EXECUTION_TIMED_OUT") return FollowJointTrajectoryErrorCode::ExecutionTimedOut;
  if (value == "HARDWARE_FAULT") return FollowJointTrajectoryErrorCode::HardwareFault;
  if (value == "CANCELED") return FollowJointTrajectoryErrorCode::Canceled;
  if (value == "INTERNAL_ERROR") return FollowJointTrajectoryErrorCode::InternalError;
  return arrow::Status::Invalid("unsupported FollowJointTrajectoryErrorCode: ", value);
}

std::string ToString(MotionPhase value) {
  switch (value) {
    case MotionPhase::Validating: return "VALIDATING";
    case MotionPhase::Planning: return "PLANNING";
    case MotionPhase::WaitingForController: return "WAITING_FOR_CONTROLLER";
    case MotionPhase::Executing: return "EXECUTING";
    case MotionPhase::Settling: return "SETTLING";
  }
  return {};
}

arrow::Result<MotionPhase> MotionPhaseFromString(const std::string& value) {
  if (value == "VALIDATING") return MotionPhase::Validating;
  if (value == "PLANNING") return MotionPhase::Planning;
  if (value == "WAITING_FOR_CONTROLLER") return MotionPhase::WaitingForController;
  if (value == "EXECUTING") return MotionPhase::Executing;
  if (value == "SETTLING") return MotionPhase::Settling;
  return arrow::Status::Invalid("unsupported MotionPhase: ", value);
}

std::string ToString(MotionErrorCode value) {
  switch (value) {
    case MotionErrorCode::Success: return "SUCCESS";
    case MotionErrorCode::InvalidGoal: return "INVALID_GOAL";
    case MotionErrorCode::Busy: return "BUSY";
    case MotionErrorCode::InvalidGroup: return "INVALID_GROUP";
    case MotionErrorCode::InvalidJoints: return "INVALID_JOINTS";
    case MotionErrorCode::InvalidFrame: return "INVALID_FRAME";
    case MotionErrorCode::NoFreshRobotState: return "NO_FRESH_ROBOT_STATE";
    case MotionErrorCode::IkFailed: return "IK_FAILED";
    case MotionErrorCode::IkTimedOut: return "IK_TIMED_OUT";
    case MotionErrorCode::JointLimitViolation: return "JOINT_LIMIT_VIOLATION";
    case MotionErrorCode::PlanningFailed: return "PLANNING_FAILED";
    case MotionErrorCode::TrajectoryGenerationFailed: return "TRAJECTORY_GENERATION_FAILED";
    case MotionErrorCode::TrajectoryRejected: return "TRAJECTORY_REJECTED";
    case MotionErrorCode::TrajectoryExecutionFailed: return "TRAJECTORY_EXECUTION_FAILED";
    case MotionErrorCode::FinalJointToleranceViolated: {
      return "FINAL_JOINT_TOLERANCE_VIOLATED";
    }
    case MotionErrorCode::FinalPoseToleranceViolated: return "FINAL_POSE_TOLERANCE_VIOLATED";
    case MotionErrorCode::Canceled: return "CANCELED";
    case MotionErrorCode::InternalError: return "INTERNAL_ERROR";
  }
  return {};
}

arrow::Result<MotionErrorCode> MotionErrorCodeFromString(const std::string& value) {
  if (value == "SUCCESS") return MotionErrorCode::Success;
  if (value == "INVALID_GOAL") return MotionErrorCode::InvalidGoal;
  if (value == "BUSY") return MotionErrorCode::Busy;
  if (value == "INVALID_GROUP") return MotionErrorCode::InvalidGroup;
  if (value == "INVALID_JOINTS") return MotionErrorCode::InvalidJoints;
  if (value == "INVALID_FRAME") return MotionErrorCode::InvalidFrame;
  if (value == "NO_FRESH_ROBOT_STATE") return MotionErrorCode::NoFreshRobotState;
  if (value == "IK_FAILED") return MotionErrorCode::IkFailed;
  if (value == "IK_TIMED_OUT") return MotionErrorCode::IkTimedOut;
  if (value == "JOINT_LIMIT_VIOLATION") return MotionErrorCode::JointLimitViolation;
  if (value == "PLANNING_FAILED") return MotionErrorCode::PlanningFailed;
  if (value == "TRAJECTORY_GENERATION_FAILED") {
    return MotionErrorCode::TrajectoryGenerationFailed;
  }
  if (value == "TRAJECTORY_REJECTED") return MotionErrorCode::TrajectoryRejected;
  if (value == "TRAJECTORY_EXECUTION_FAILED") return MotionErrorCode::TrajectoryExecutionFailed;
  if (value == "FINAL_JOINT_TOLERANCE_VIOLATED") {
    return MotionErrorCode::FinalJointToleranceViolated;
  }
  if (value == "FINAL_POSE_TOLERANCE_VIOLATED") {
    return MotionErrorCode::FinalPoseToleranceViolated;
  }
  if (value == "CANCELED") return MotionErrorCode::Canceled;
  if (value == "INTERNAL_ERROR") return MotionErrorCode::InternalError;
  return arrow::Status::Invalid("unsupported MotionErrorCode: ", value);
}

std::string ToString(GripperCommandErrorCode value) {
  switch (value) {
    case GripperCommandErrorCode::Success: return "SUCCESS";
    case GripperCommandErrorCode::InvalidGoal: return "INVALID_GOAL";
    case GripperCommandErrorCode::Busy: return "BUSY";
    case GripperCommandErrorCode::PositionLimitViolation: return "POSITION_LIMIT_VIOLATION";
    case GripperCommandErrorCode::UnsupportedVelocity: return "UNSUPPORTED_VELOCITY";
    case GripperCommandErrorCode::UnsupportedEffort: return "UNSUPPORTED_EFFORT";
    case GripperCommandErrorCode::NoFreshRobotState: return "NO_FRESH_ROBOT_STATE";
    case GripperCommandErrorCode::FeedbackStale: return "FEEDBACK_STALE";
    case GripperCommandErrorCode::Stalled: return "STALLED";
    case GripperCommandErrorCode::ExecutionTimedOut: return "EXECUTION_TIMED_OUT";
    case GripperCommandErrorCode::HardwareFault: return "HARDWARE_FAULT";
    case GripperCommandErrorCode::Canceled: return "CANCELED";
    case GripperCommandErrorCode::InternalError: return "INTERNAL_ERROR";
  }
  return {};
}

arrow::Result<GripperCommandErrorCode> GripperCommandErrorCodeFromString(
    const std::string& value) {
  if (value == "SUCCESS") return GripperCommandErrorCode::Success;
  if (value == "INVALID_GOAL") return GripperCommandErrorCode::InvalidGoal;
  if (value == "BUSY") return GripperCommandErrorCode::Busy;
  if (value == "POSITION_LIMIT_VIOLATION") {
    return GripperCommandErrorCode::PositionLimitViolation;
  }
  if (value == "UNSUPPORTED_VELOCITY") return GripperCommandErrorCode::UnsupportedVelocity;
  if (value == "UNSUPPORTED_EFFORT") return GripperCommandErrorCode::UnsupportedEffort;
  if (value == "NO_FRESH_ROBOT_STATE") return GripperCommandErrorCode::NoFreshRobotState;
  if (value == "FEEDBACK_STALE") return GripperCommandErrorCode::FeedbackStale;
  if (value == "STALLED") return GripperCommandErrorCode::Stalled;
  if (value == "EXECUTION_TIMED_OUT") return GripperCommandErrorCode::ExecutionTimedOut;
  if (value == "HARDWARE_FAULT") return GripperCommandErrorCode::HardwareFault;
  if (value == "CANCELED") return GripperCommandErrorCode::Canceled;
  if (value == "INTERNAL_ERROR") return GripperCommandErrorCode::InternalError;
  return arrow::Status::Invalid("unsupported GripperCommandErrorCode: ", value);
}

arrow::Status FollowJointTrajectoryGoal::Validate() const {
  ARROW_RETURN_NOT_OK(trajectory.Validate());
  const std::set<std::string> names(trajectory.joint_names.begin(), trajectory.joint_names.end());
  ARROW_RETURN_NOT_OK(ValidateToleranceList("path_tolerance", path_tolerance, names));
  ARROW_RETURN_NOT_OK(ValidateToleranceList("goal_tolerance", goal_tolerance, names));
  return ValidateOptionalDuration("goal_time_tolerance_ns", goal_time_tolerance_ns);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>>
FollowJointTrajectoryGoal::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto trajectory_array, RequiredStruct(trajectory));
  const auto tolerance_fields = JointToleranceFields();
  ARROW_ASSIGN_OR_RAISE(auto path_array,
                        MessageStructList(path_tolerance, tolerance_fields));
  ARROW_ASSIGN_OR_RAISE(auto goal_array,
                        MessageStructList(goal_tolerance, tolerance_fields));
  ARROW_ASSIGN_OR_RAISE(auto time_array, OptionalI64(goal_time_tolerance_ns));

  auto trajectory_type = std::static_pointer_cast<arrow::StructArray>(trajectory_array)->type();
  auto tolerance_type = arrow::struct_(tolerance_fields);
  return MakeBatch({arrow::field("trajectory", trajectory_type, false),
                    arrow::field("path_tolerance", ListType(tolerance_type), false),
                    arrow::field("goal_tolerance", ListType(tolerance_type), false),
                    arrow::field("goal_time_tolerance_ns", arrow::int64(), true)},
                   {trajectory_array, path_array, goal_array, time_array});
}

arrow::Result<FollowJointTrajectoryGoal> FollowJointTrajectoryGoal::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  FollowJointTrajectoryGoal value;
  ARROW_ASSIGN_OR_RAISE(value.trajectory,
                        ReadRequiredMessage<JointTrajectory>(batch, "trajectory"));
  ARROW_ASSIGN_OR_RAISE(auto path_batches, ReadStructList(batch, "path_tolerance"));
  for (const auto& nested : path_batches) {
    ARROW_ASSIGN_OR_RAISE(auto tolerance, JointTolerance::FromRecordBatch(*nested));
    value.path_tolerance.push_back(std::move(tolerance));
  }
  ARROW_ASSIGN_OR_RAISE(auto goal_batches, ReadStructList(batch, "goal_tolerance"));
  for (const auto& nested : goal_batches) {
    ARROW_ASSIGN_OR_RAISE(auto tolerance, JointTolerance::FromRecordBatch(*nested));
    value.goal_tolerance.push_back(std::move(tolerance));
  }
  ARROW_ASSIGN_OR_RAISE(value.goal_time_tolerance_ns,
                        ReadOptionalI64(batch, "goal_time_tolerance_ns"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status FollowJointTrajectoryFeedback::Validate() const {
  if (elapsed_ns < 0 || duration_ns < 0) {
    return arrow::Status::Invalid("elapsed_ns and duration_ns must be non-negative");
  }
  ARROW_RETURN_NOT_OK(desired.Validate());
  ARROW_RETURN_NOT_OK(actual.Validate());
  ARROW_RETURN_NOT_OK(error.Validate());
  if (desired.positions.size() != actual.positions.size() ||
      desired.positions.size() != error.positions.size()) {
    return arrow::Status::Invalid("desired, actual, and error positions lengths must match");
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>>
FollowJointTrajectoryFeedback::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto sequence_array, ScalarU64(sequence));
  ARROW_ASSIGN_OR_RAISE(auto point_index_array, ScalarU32(point_index));
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto duration_array, ScalarI64(duration_ns));
  ARROW_ASSIGN_OR_RAISE(auto desired_array, RequiredStruct(desired));
  ARROW_ASSIGN_OR_RAISE(auto actual_array, RequiredStruct(actual));
  ARROW_ASSIGN_OR_RAISE(auto error_array, RequiredStruct(error));
  auto point_type = std::static_pointer_cast<arrow::StructArray>(desired_array)->type();
  return MakeBatch({arrow::field("sequence", arrow::uint64(), false),
                    arrow::field("point_index", arrow::uint32(), false),
                    arrow::field("elapsed_ns", arrow::int64(), false),
                    arrow::field("duration_ns", arrow::int64(), false),
                    arrow::field("desired", point_type, false),
                    arrow::field("actual", point_type, false),
                    arrow::field("error", point_type, false)},
                   {sequence_array, point_index_array, elapsed_array, duration_array,
                    desired_array, actual_array, error_array});
}

arrow::Result<FollowJointTrajectoryFeedback>
FollowJointTrajectoryFeedback::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  FollowJointTrajectoryFeedback value;
  ARROW_ASSIGN_OR_RAISE(value.sequence, ReadU64(batch, "sequence"));
  ARROW_ASSIGN_OR_RAISE(value.point_index, ReadU32(batch, "point_index"));
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.duration_ns, ReadI64(batch, "duration_ns"));
  ARROW_ASSIGN_OR_RAISE(value.desired,
                        ReadRequiredMessage<JointTrajectoryPoint>(batch, "desired"));
  ARROW_ASSIGN_OR_RAISE(value.actual,
                        ReadRequiredMessage<JointTrajectoryPoint>(batch, "actual"));
  ARROW_ASSIGN_OR_RAISE(value.error,
                        ReadRequiredMessage<JointTrajectoryPoint>(batch, "error"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status FollowJointTrajectoryResult::Validate() const {
  if (ToString(error_code).empty()) {
    return arrow::Status::Invalid("error_code is invalid");
  }
  if (elapsed_ns < 0) return arrow::Status::Invalid("elapsed_ns must be non-negative");
  ARROW_RETURN_NOT_OK(ValidateJointNames(joint_names, true));
  ARROW_RETURN_NOT_OK(
      ValidateLen("final_position_error", final_position_error, joint_names.size(), true));
  return ValidateLen("final_velocity_error", final_velocity_error, joint_names.size(), true);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>>
FollowJointTrajectoryResult::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto error_code_array, ScalarString(ToString(error_code)));
  ARROW_ASSIGN_OR_RAISE(auto message_array, ScalarString(message));
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto joint_names_array, StringList(joint_names));
  ARROW_ASSIGN_OR_RAISE(auto position_error_array, F64List(final_position_error));
  ARROW_ASSIGN_OR_RAISE(auto velocity_error_array, F64List(final_velocity_error));
  auto f64_list = ListType(arrow::float64());
  return MakeBatch({arrow::field("error_code", arrow::utf8(), false),
                    arrow::field("message", arrow::utf8(), false),
                    arrow::field("elapsed_ns", arrow::int64(), false),
                    arrow::field("joint_names", ListType(arrow::utf8()), false),
                    arrow::field("final_position_error", f64_list, false),
                    arrow::field("final_velocity_error", f64_list, false)},
                   {error_code_array, message_array, elapsed_array, joint_names_array,
                    position_error_array, velocity_error_array});
}

arrow::Result<FollowJointTrajectoryResult>
FollowJointTrajectoryResult::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  FollowJointTrajectoryResult value;
  ARROW_ASSIGN_OR_RAISE(auto error_code, ReadString(batch, "error_code"));
  ARROW_ASSIGN_OR_RAISE(value.error_code,
                        FollowJointTrajectoryErrorCodeFromString(error_code));
  ARROW_ASSIGN_OR_RAISE(value.message, ReadString(batch, "message"));
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.joint_names, ReadStringList(batch, "joint_names"));
  ARROW_ASSIGN_OR_RAISE(value.final_position_error,
                        ReadF64List(batch, "final_position_error"));
  ARROW_ASSIGN_OR_RAISE(value.final_velocity_error,
                        ReadF64List(batch, "final_velocity_error"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status GripperCommandGoal::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateFinite("position", position));
  ARROW_RETURN_NOT_OK(ValidateOptionalNonNegative("max_velocity", max_velocity));
  return ValidateOptionalNonNegative("max_effort", max_effort);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>>
GripperCommandGoal::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto position_array, ScalarF64(position));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, OptionalF64(max_velocity));
  ARROW_ASSIGN_OR_RAISE(auto effort_array, OptionalF64(max_effort));
  return MakeBatch(GripperCommandGoalFields(),
                   {position_array, velocity_array, effort_array});
}

arrow::Result<GripperCommandGoal> GripperCommandGoal::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  ARROW_RETURN_NOT_OK(
      RequireExactSchema(batch, GripperCommandGoalFields(), "GripperCommandGoal"));
  GripperCommandGoal value;
  ARROW_ASSIGN_OR_RAISE(value.position, ReadF64(batch, "position"));
  ARROW_ASSIGN_OR_RAISE(value.max_velocity, ReadOptionalF64(batch, "max_velocity"));
  ARROW_ASSIGN_OR_RAISE(value.max_effort, ReadOptionalF64(batch, "max_effort"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status GripperCommandFeedback::Validate() const {
  if (elapsed_ns < 0) return arrow::Status::Invalid("elapsed_ns must be non-negative");
  ARROW_RETURN_NOT_OK(ValidateFinite("position", position));
  ARROW_RETURN_NOT_OK(ValidateOptionalFinite("velocity", velocity));
  return ValidateOptionalFinite("effort", effort);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>>
GripperCommandFeedback::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto position_array, ScalarF64(position));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, OptionalF64(velocity));
  ARROW_ASSIGN_OR_RAISE(auto effort_array, OptionalF64(effort));
  ARROW_ASSIGN_OR_RAISE(auto stalled_array, ScalarBool(stalled));
  ARROW_ASSIGN_OR_RAISE(auto reached_array, ScalarBool(reached_goal));
  return MakeBatch(GripperCommandFeedbackFields(),
                   {elapsed_array, position_array, velocity_array, effort_array,
                    stalled_array, reached_array});
}

arrow::Result<GripperCommandFeedback> GripperCommandFeedback::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  ARROW_RETURN_NOT_OK(
      RequireExactSchema(batch, GripperCommandFeedbackFields(), "GripperCommandFeedback"));
  GripperCommandFeedback value;
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.position, ReadF64(batch, "position"));
  ARROW_ASSIGN_OR_RAISE(value.velocity, ReadOptionalF64(batch, "velocity"));
  ARROW_ASSIGN_OR_RAISE(value.effort, ReadOptionalF64(batch, "effort"));
  ARROW_ASSIGN_OR_RAISE(value.stalled, ReadBool(batch, "stalled"));
  ARROW_ASSIGN_OR_RAISE(value.reached_goal, ReadBool(batch, "reached_goal"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status GripperCommandResult::Validate() const {
  if (ToString(error_code).empty()) return arrow::Status::Invalid("error_code is invalid");
  if (elapsed_ns < 0) return arrow::Status::Invalid("elapsed_ns must be non-negative");
  ARROW_RETURN_NOT_OK(ValidateOptionalFinite("position", position));
  ARROW_RETURN_NOT_OK(ValidateOptionalFinite("velocity", velocity));
  ARROW_RETURN_NOT_OK(ValidateOptionalFinite("effort", effort));
  if (stalled && reached_goal) {
    return arrow::Status::Invalid("stalled and reached_goal cannot both be true");
  }
  if (error_code == GripperCommandErrorCode::Success && !stalled && !reached_goal) {
    return arrow::Status::Invalid(
        "SUCCESS requires exactly one of stalled/reached_goal true");
  }
  if (error_code == GripperCommandErrorCode::Stalled && (!stalled || reached_goal)) {
    return arrow::Status::Invalid(
        "STALLED requires stalled=true and reached_goal=false");
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>>
GripperCommandResult::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto error_array, ScalarString(ToString(error_code)));
  ARROW_ASSIGN_OR_RAISE(auto message_array, ScalarString(message));
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto position_array, OptionalF64(position));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, OptionalF64(velocity));
  ARROW_ASSIGN_OR_RAISE(auto effort_array, OptionalF64(effort));
  ARROW_ASSIGN_OR_RAISE(auto stalled_array, ScalarBool(stalled));
  ARROW_ASSIGN_OR_RAISE(auto reached_array, ScalarBool(reached_goal));
  return MakeBatch(GripperCommandResultFields(),
                   {error_array, message_array, elapsed_array, position_array,
                    velocity_array, effort_array, stalled_array, reached_array});
}

arrow::Result<GripperCommandResult> GripperCommandResult::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  ARROW_RETURN_NOT_OK(
      RequireExactSchema(batch, GripperCommandResultFields(), "GripperCommandResult"));
  GripperCommandResult value;
  ARROW_ASSIGN_OR_RAISE(auto error_code, ReadString(batch, "error_code"));
  ARROW_ASSIGN_OR_RAISE(value.error_code, GripperCommandErrorCodeFromString(error_code));
  ARROW_ASSIGN_OR_RAISE(value.message, ReadString(batch, "message"));
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.position, ReadOptionalF64(batch, "position"));
  ARROW_ASSIGN_OR_RAISE(value.velocity, ReadOptionalF64(batch, "velocity"));
  ARROW_ASSIGN_OR_RAISE(value.effort, ReadOptionalF64(batch, "effort"));
  ARROW_ASSIGN_OR_RAISE(value.stalled, ReadBool(batch, "stalled"));
  ARROW_ASSIGN_OR_RAISE(value.reached_goal, ReadBool(batch, "reached_goal"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status MoveJointsGoal::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateRequired("group_name", group_name));
  ARROW_RETURN_NOT_OK(ValidateJointNames(joint_names, false));
  ARROW_RETURN_NOT_OK(ValidateLen("positions", positions, joint_names.size()));
  ARROW_RETURN_NOT_OK(ValidateFiniteValues("positions", positions));
  ARROW_RETURN_NOT_OK(ValidateScale("velocity_scale", velocity_scale));
  ARROW_RETURN_NOT_OK(ValidateScale("acceleration_scale", acceleration_scale));
  return ValidateOptionalDuration("requested_duration_ns", requested_duration_ns);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> MoveJointsGoal::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto group_array, ScalarString(group_name));
  ARROW_ASSIGN_OR_RAISE(auto names_array, StringList(joint_names));
  ARROW_ASSIGN_OR_RAISE(auto positions_array, F64List(positions));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, ScalarF64(velocity_scale));
  ARROW_ASSIGN_OR_RAISE(auto acceleration_array, ScalarF64(acceleration_scale));
  ARROW_ASSIGN_OR_RAISE(auto duration_array, OptionalI64(requested_duration_ns));
  return MakeBatch({arrow::field("group_name", arrow::utf8(), false),
                    arrow::field("joint_names", ListType(arrow::utf8()), false),
                    arrow::field("positions", ListType(arrow::float64()), false),
                    arrow::field("velocity_scale", arrow::float64(), false),
                    arrow::field("acceleration_scale", arrow::float64(), false),
                    arrow::field("requested_duration_ns", arrow::int64(), true)},
                   {group_array, names_array, positions_array, velocity_array,
                    acceleration_array, duration_array});
}

arrow::Result<MoveJointsGoal> MoveJointsGoal::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  MoveJointsGoal value;
  ARROW_ASSIGN_OR_RAISE(value.group_name, ReadString(batch, "group_name"));
  ARROW_ASSIGN_OR_RAISE(value.joint_names, ReadStringList(batch, "joint_names"));
  ARROW_ASSIGN_OR_RAISE(value.positions, ReadF64List(batch, "positions"));
  ARROW_ASSIGN_OR_RAISE(value.velocity_scale, ReadF64(batch, "velocity_scale"));
  ARROW_ASSIGN_OR_RAISE(value.acceleration_scale, ReadF64(batch, "acceleration_scale"));
  ARROW_ASSIGN_OR_RAISE(value.requested_duration_ns,
                        ReadOptionalI64(batch, "requested_duration_ns"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status MoveJointsFeedback::Validate() const {
  if (ToString(phase).empty()) return arrow::Status::Invalid("phase is invalid");
  if (progress && (!std::isfinite(*progress) || *progress < 0.0 || *progress > 1.0)) {
    return arrow::Status::Invalid("progress must be finite and in [0, 1] when specified");
  }
  if (elapsed_ns < 0) return arrow::Status::Invalid("elapsed_ns must be non-negative");
  ARROW_RETURN_NOT_OK(ValidateOptionalDuration("estimated_duration_ns", estimated_duration_ns));
  ARROW_RETURN_NOT_OK(ValidateJointNames(joint_names, false));
  ARROW_RETURN_NOT_OK(ValidateLen("target_positions", target_positions, joint_names.size()));
  ARROW_RETURN_NOT_OK(
      ValidateLen("actual_positions", actual_positions, joint_names.size(), true));
  return ValidateLen("position_errors", position_errors, joint_names.size(), true);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> MoveJointsFeedback::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto phase_array, ScalarString(ToString(phase)));
  ARROW_ASSIGN_OR_RAISE(auto progress_array, OptionalF64(progress));
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto duration_array, OptionalI64(estimated_duration_ns));
  ARROW_ASSIGN_OR_RAISE(auto names_array, StringList(joint_names));
  ARROW_ASSIGN_OR_RAISE(auto actual_array, F64List(actual_positions));
  ARROW_ASSIGN_OR_RAISE(auto target_array, F64List(target_positions));
  ARROW_ASSIGN_OR_RAISE(auto errors_array, F64List(position_errors));
  ARROW_ASSIGN_OR_RAISE(auto message_array, ScalarString(message));
  auto f64_list = ListType(arrow::float64());
  return MakeBatch({arrow::field("phase", arrow::utf8(), false),
                    arrow::field("progress", arrow::float64(), true),
                    arrow::field("elapsed_ns", arrow::int64(), false),
                    arrow::field("estimated_duration_ns", arrow::int64(), true),
                    arrow::field("joint_names", ListType(arrow::utf8()), false),
                    arrow::field("actual_positions", f64_list, false),
                    arrow::field("target_positions", f64_list, false),
                    arrow::field("position_errors", f64_list, false),
                    arrow::field("message", arrow::utf8(), false)},
                   {phase_array, progress_array, elapsed_array, duration_array, names_array,
                    actual_array, target_array, errors_array, message_array});
}

arrow::Result<MoveJointsFeedback> MoveJointsFeedback::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  MoveJointsFeedback value;
  ARROW_ASSIGN_OR_RAISE(auto phase, ReadString(batch, "phase"));
  ARROW_ASSIGN_OR_RAISE(value.phase, MotionPhaseFromString(phase));
  ARROW_ASSIGN_OR_RAISE(value.progress, ReadOptionalF64(batch, "progress"));
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.estimated_duration_ns,
                        ReadOptionalI64(batch, "estimated_duration_ns"));
  ARROW_ASSIGN_OR_RAISE(value.joint_names, ReadStringList(batch, "joint_names"));
  ARROW_ASSIGN_OR_RAISE(value.actual_positions, ReadF64List(batch, "actual_positions"));
  ARROW_ASSIGN_OR_RAISE(value.target_positions, ReadF64List(batch, "target_positions"));
  ARROW_ASSIGN_OR_RAISE(value.position_errors, ReadF64List(batch, "position_errors"));
  ARROW_ASSIGN_OR_RAISE(value.message, ReadString(batch, "message"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status MoveJointsResult::Validate() const {
  if (ToString(error_code).empty()) return arrow::Status::Invalid("error_code is invalid");
  if (elapsed_ns < 0) return arrow::Status::Invalid("elapsed_ns must be non-negative");
  ARROW_RETURN_NOT_OK(ValidateJointNames(joint_names, true));
  ARROW_RETURN_NOT_OK(ValidateLen("final_positions", final_positions, joint_names.size(), true));
  return ValidateLen("final_position_errors", final_position_errors, joint_names.size(), true);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> MoveJointsResult::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto error_array, ScalarString(ToString(error_code)));
  ARROW_ASSIGN_OR_RAISE(auto message_array, ScalarString(message));
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto names_array, StringList(joint_names));
  ARROW_ASSIGN_OR_RAISE(auto positions_array, F64List(final_positions));
  ARROW_ASSIGN_OR_RAISE(auto errors_array, F64List(final_position_errors));
  auto f64_list = ListType(arrow::float64());
  return MakeBatch({arrow::field("error_code", arrow::utf8(), false),
                    arrow::field("message", arrow::utf8(), false),
                    arrow::field("elapsed_ns", arrow::int64(), false),
                    arrow::field("joint_names", ListType(arrow::utf8()), false),
                    arrow::field("final_positions", f64_list, false),
                    arrow::field("final_position_errors", f64_list, false)},
                   {error_array, message_array, elapsed_array, names_array, positions_array,
                    errors_array});
}

arrow::Result<MoveJointsResult> MoveJointsResult::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  MoveJointsResult value;
  ARROW_ASSIGN_OR_RAISE(auto error_code, ReadString(batch, "error_code"));
  ARROW_ASSIGN_OR_RAISE(value.error_code, MotionErrorCodeFromString(error_code));
  ARROW_ASSIGN_OR_RAISE(value.message, ReadString(batch, "message"));
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.joint_names, ReadStringList(batch, "joint_names"));
  ARROW_ASSIGN_OR_RAISE(value.final_positions, ReadF64List(batch, "final_positions"));
  ARROW_ASSIGN_OR_RAISE(value.final_position_errors,
                        ReadF64List(batch, "final_position_errors"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status MovePoseGoal::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateRequired("group_name", group_name));
  ARROW_RETURN_NOT_OK(ValidateRequired("reference_frame", reference_frame));
  ARROW_RETURN_NOT_OK(ValidateRequired("target_frame", target_frame));
  ARROW_RETURN_NOT_OK(target_pose.Validate());
  ARROW_RETURN_NOT_OK(ValidateScale("velocity_scale", velocity_scale));
  ARROW_RETURN_NOT_OK(ValidateScale("acceleration_scale", acceleration_scale));
  ARROW_RETURN_NOT_OK(ValidateOptionalDuration("requested_duration_ns", requested_duration_ns));
  ARROW_RETURN_NOT_OK(ValidateOptionalNonNegative("position_tolerance_m", position_tolerance_m));
  return ValidateOptionalNonNegative("orientation_tolerance_rad", orientation_tolerance_rad);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> MovePoseGoal::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto group_array, ScalarString(group_name));
  ARROW_ASSIGN_OR_RAISE(auto reference_array, ScalarString(reference_frame));
  ARROW_ASSIGN_OR_RAISE(auto target_frame_array, ScalarString(target_frame));
  ARROW_ASSIGN_OR_RAISE(auto pose_array, RequiredStruct(target_pose));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, ScalarF64(velocity_scale));
  ARROW_ASSIGN_OR_RAISE(auto acceleration_array, ScalarF64(acceleration_scale));
  ARROW_ASSIGN_OR_RAISE(auto duration_array, OptionalI64(requested_duration_ns));
  ARROW_ASSIGN_OR_RAISE(auto position_tolerance_array, OptionalF64(position_tolerance_m));
  ARROW_ASSIGN_OR_RAISE(auto orientation_tolerance_array,
                        OptionalF64(orientation_tolerance_rad));
  auto pose_type = std::static_pointer_cast<arrow::StructArray>(pose_array)->type();
  return MakeBatch({arrow::field("group_name", arrow::utf8(), false),
                    arrow::field("reference_frame", arrow::utf8(), false),
                    arrow::field("target_frame", arrow::utf8(), false),
                    arrow::field("target_pose", pose_type, false),
                    arrow::field("velocity_scale", arrow::float64(), false),
                    arrow::field("acceleration_scale", arrow::float64(), false),
                    arrow::field("requested_duration_ns", arrow::int64(), true),
                    arrow::field("position_tolerance_m", arrow::float64(), true),
                    arrow::field("orientation_tolerance_rad", arrow::float64(), true)},
                   {group_array, reference_array, target_frame_array, pose_array, velocity_array,
                    acceleration_array, duration_array, position_tolerance_array,
                    orientation_tolerance_array});
}

arrow::Result<MovePoseGoal> MovePoseGoal::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  MovePoseGoal value;
  ARROW_ASSIGN_OR_RAISE(value.group_name, ReadString(batch, "group_name"));
  ARROW_ASSIGN_OR_RAISE(value.reference_frame, ReadString(batch, "reference_frame"));
  ARROW_ASSIGN_OR_RAISE(value.target_frame, ReadString(batch, "target_frame"));
  ARROW_ASSIGN_OR_RAISE(value.target_pose, ReadRequiredMessage<Pose>(batch, "target_pose"));
  ARROW_ASSIGN_OR_RAISE(value.velocity_scale, ReadF64(batch, "velocity_scale"));
  ARROW_ASSIGN_OR_RAISE(value.acceleration_scale, ReadF64(batch, "acceleration_scale"));
  ARROW_ASSIGN_OR_RAISE(value.requested_duration_ns,
                        ReadOptionalI64(batch, "requested_duration_ns"));
  ARROW_ASSIGN_OR_RAISE(value.position_tolerance_m,
                        ReadOptionalF64(batch, "position_tolerance_m"));
  ARROW_ASSIGN_OR_RAISE(value.orientation_tolerance_rad,
                        ReadOptionalF64(batch, "orientation_tolerance_rad"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status MovePoseFeedback::Validate() const {
  if (ToString(phase).empty()) return arrow::Status::Invalid("phase is invalid");
  if (progress && (!std::isfinite(*progress) || *progress < 0.0 || *progress > 1.0)) {
    return arrow::Status::Invalid("progress must be finite and in [0, 1] when specified");
  }
  if (elapsed_ns < 0) return arrow::Status::Invalid("elapsed_ns must be non-negative");
  ARROW_RETURN_NOT_OK(ValidateOptionalDuration("estimated_duration_ns", estimated_duration_ns));
  if (actual_pose) ARROW_RETURN_NOT_OK(actual_pose->Validate());
  ARROW_RETURN_NOT_OK(ValidateOptionalNonNegative("position_error_m", position_error_m));
  return ValidateOptionalNonNegative("orientation_error_rad", orientation_error_rad);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> MovePoseFeedback::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto phase_array, ScalarString(ToString(phase)));
  ARROW_ASSIGN_OR_RAISE(auto progress_array, OptionalF64(progress));
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto duration_array, OptionalI64(estimated_duration_ns));
  ARROW_ASSIGN_OR_RAISE(auto pose_array, OptionalPoseStruct(actual_pose));
  ARROW_ASSIGN_OR_RAISE(auto position_error_array, OptionalF64(position_error_m));
  ARROW_ASSIGN_OR_RAISE(auto orientation_error_array, OptionalF64(orientation_error_rad));
  ARROW_ASSIGN_OR_RAISE(auto message_array, ScalarString(message));
  auto pose_type = std::static_pointer_cast<arrow::StructArray>(pose_array)->type();
  return MakeBatch({arrow::field("phase", arrow::utf8(), false),
                    arrow::field("progress", arrow::float64(), true),
                    arrow::field("elapsed_ns", arrow::int64(), false),
                    arrow::field("estimated_duration_ns", arrow::int64(), true),
                    arrow::field("actual_pose", pose_type, true),
                    arrow::field("position_error_m", arrow::float64(), true),
                    arrow::field("orientation_error_rad", arrow::float64(), true),
                    arrow::field("message", arrow::utf8(), false)},
                   {phase_array, progress_array, elapsed_array, duration_array, pose_array,
                    position_error_array, orientation_error_array, message_array});
}

arrow::Result<MovePoseFeedback> MovePoseFeedback::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  MovePoseFeedback value;
  ARROW_ASSIGN_OR_RAISE(auto phase, ReadString(batch, "phase"));
  ARROW_ASSIGN_OR_RAISE(value.phase, MotionPhaseFromString(phase));
  ARROW_ASSIGN_OR_RAISE(value.progress, ReadOptionalF64(batch, "progress"));
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.estimated_duration_ns,
                        ReadOptionalI64(batch, "estimated_duration_ns"));
  ARROW_ASSIGN_OR_RAISE(value.actual_pose, ReadOptionalPose(batch, "actual_pose"));
  ARROW_ASSIGN_OR_RAISE(value.position_error_m,
                        ReadOptionalF64(batch, "position_error_m"));
  ARROW_ASSIGN_OR_RAISE(value.orientation_error_rad,
                        ReadOptionalF64(batch, "orientation_error_rad"));
  ARROW_ASSIGN_OR_RAISE(value.message, ReadString(batch, "message"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status MovePoseResult::Validate() const {
  if (ToString(error_code).empty()) return arrow::Status::Invalid("error_code is invalid");
  if (elapsed_ns < 0) return arrow::Status::Invalid("elapsed_ns must be non-negative");
  if (final_pose) ARROW_RETURN_NOT_OK(final_pose->Validate());
  ARROW_RETURN_NOT_OK(
      ValidateOptionalNonNegative("final_position_error_m", final_position_error_m));
  ARROW_RETURN_NOT_OK(
      ValidateOptionalNonNegative("final_orientation_error_rad", final_orientation_error_rad));
  ARROW_RETURN_NOT_OK(ValidateJointNames(joint_names, true));
  return ValidateLen("final_joint_positions", final_joint_positions, joint_names.size(), true);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> MovePoseResult::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto error_array, ScalarString(ToString(error_code)));
  ARROW_ASSIGN_OR_RAISE(auto message_array, ScalarString(message));
  ARROW_ASSIGN_OR_RAISE(auto elapsed_array, ScalarI64(elapsed_ns));
  ARROW_ASSIGN_OR_RAISE(auto pose_array, OptionalPoseStruct(final_pose));
  ARROW_ASSIGN_OR_RAISE(auto position_error_array, OptionalF64(final_position_error_m));
  ARROW_ASSIGN_OR_RAISE(auto orientation_error_array,
                        OptionalF64(final_orientation_error_rad));
  ARROW_ASSIGN_OR_RAISE(auto names_array, StringList(joint_names));
  ARROW_ASSIGN_OR_RAISE(auto positions_array, F64List(final_joint_positions));
  auto pose_type = std::static_pointer_cast<arrow::StructArray>(pose_array)->type();
  return MakeBatch({arrow::field("error_code", arrow::utf8(), false),
                    arrow::field("message", arrow::utf8(), false),
                    arrow::field("elapsed_ns", arrow::int64(), false),
                    arrow::field("final_pose", pose_type, true),
                    arrow::field("final_position_error_m", arrow::float64(), true),
                    arrow::field("final_orientation_error_rad", arrow::float64(), true),
                    arrow::field("joint_names", ListType(arrow::utf8()), false),
                    arrow::field("final_joint_positions", ListType(arrow::float64()), false)},
                   {error_array, message_array, elapsed_array, pose_array, position_error_array,
                    orientation_error_array, names_array, positions_array});
}

arrow::Result<MovePoseResult> MovePoseResult::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  MovePoseResult value;
  ARROW_ASSIGN_OR_RAISE(auto error_code, ReadString(batch, "error_code"));
  ARROW_ASSIGN_OR_RAISE(value.error_code, MotionErrorCodeFromString(error_code));
  ARROW_ASSIGN_OR_RAISE(value.message, ReadString(batch, "message"));
  ARROW_ASSIGN_OR_RAISE(value.elapsed_ns, ReadI64(batch, "elapsed_ns"));
  ARROW_ASSIGN_OR_RAISE(value.final_pose, ReadOptionalPose(batch, "final_pose"));
  ARROW_ASSIGN_OR_RAISE(value.final_position_error_m,
                        ReadOptionalF64(batch, "final_position_error_m"));
  ARROW_ASSIGN_OR_RAISE(value.final_orientation_error_rad,
                        ReadOptionalF64(batch, "final_orientation_error_rad"));
  ARROW_ASSIGN_OR_RAISE(value.joint_names, ReadStringList(batch, "joint_names"));
  ARROW_ASSIGN_OR_RAISE(value.final_joint_positions,
                        ReadF64List(batch, "final_joint_positions"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
