#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include <arrow/api.h>

namespace forge_msgs {

using Bytes = std::vector<std::uint8_t>;

arrow::Status WriteIpcStream(const arrow::RecordBatch& batch, const std::string& path);
arrow::Result<std::shared_ptr<arrow::RecordBatch>> ReadIpcStream(const std::string& path);

struct Text {
  std::string text;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Text> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct AudioChunk {
  std::uint32_t sample_rate = 0;
  std::uint32_t channels = 0;
  std::string sample_format;
  std::uint32_t frame_count = 0;
  Bytes data;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<AudioChunk> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct Image {
  std::uint32_t height = 0;
  std::uint32_t width = 0;
  std::string encoding;
  std::uint32_t step = 0;
  Bytes data;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Image> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct CompressedImage {
  std::string format;
  Bytes data;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<CompressedImage> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct PointCloud {
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  bool is_dense = false;
  std::vector<float> x;
  std::vector<float> y;
  std::vector<float> z;
  std::vector<float> intensity;
  std::vector<std::uint8_t> red;
  std::vector<std::uint8_t> green;
  std::vector<std::uint8_t> blue;

  static arrow::Result<PointCloud> FromXyz(std::vector<float> x, std::vector<float> y,
                                           std::vector<float> z);
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<PointCloud> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct JointState {
  std::vector<std::string> name;
  std::vector<double> position;
  std::vector<double> velocity;
  std::vector<double> effort;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointState> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct JointCommand {
  std::vector<std::string> name;
  std::string mode = "position";
  std::vector<double> position;
  std::vector<double> velocity;
  std::vector<double> effort;
  std::vector<double> kp;
  std::vector<double> kd;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointCommand> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct LocomotionCommand {
  double vx = 0.0;
  double vy = 0.0;
  double wz = 0.0;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<LocomotionCommand> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct PolicyCommand {
  std::string policy_id;
  std::string command;
  std::string request_id;
  std::string inputs_json = "{}";

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<PolicyCommand> FromRecordBatch(const arrow::RecordBatch& batch);
};

enum class PolicyCommandStatusValue {
  Accepted,
  Rejected,
  Running,
  Done,
  Error,
};

std::string ToString(PolicyCommandStatusValue value);
arrow::Result<PolicyCommandStatusValue> PolicyCommandStatusValueFromString(
    const std::string& value);

struct PolicyCommandStatus {
  std::string policy_id;
  std::string command;
  std::string request_id;
  PolicyCommandStatusValue status = PolicyCommandStatusValue::Running;
  std::string message;
  std::string outputs_json = "{}";

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<PolicyCommandStatus> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct Pose {
  double x = 0.0;
  double y = 0.0;
  double z = 0.0;
  double qx = 0.0;
  double qy = 0.0;
  double qz = 0.0;
  double qw = 1.0;

  static Pose Identity(double x, double y, double z);
  static Pose FromXyYaw(double x, double y, double yaw, double z = 0.0);
  std::tuple<double, double, double> XyYaw() const;
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Pose> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct JointTrajectoryPoint {
  std::vector<double> positions;
  std::vector<double> velocities;
  std::vector<double> accelerations;
  std::vector<double> effort;
  std::int64_t time_from_start_ns = 0;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointTrajectoryPoint> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct JointTrajectory {
  std::vector<std::string> joint_names;
  std::vector<JointTrajectoryPoint> points;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointTrajectory> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct JointTolerance {
  std::string joint_name;
  std::optional<double> position;
  std::optional<double> velocity;
  std::optional<double> acceleration;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointTolerance> FromRecordBatch(const arrow::RecordBatch& batch);
};

enum class FollowJointTrajectoryErrorCode {
  Success,
  InvalidGoal,
  InvalidJoints,
  Busy,
  NoFreshRobotState,
  StartStateMismatch,
  PathToleranceViolated,
  GoalToleranceViolated,
  FeedbackStale,
  ExecutionTimedOut,
  HardwareFault,
  Canceled,
  InternalError,
};

std::string ToString(FollowJointTrajectoryErrorCode value);
arrow::Result<FollowJointTrajectoryErrorCode> FollowJointTrajectoryErrorCodeFromString(
    const std::string& value);

enum class MotionPhase {
  Validating,
  Planning,
  WaitingForController,
  Executing,
  Settling,
};

std::string ToString(MotionPhase value);
arrow::Result<MotionPhase> MotionPhaseFromString(const std::string& value);

enum class MotionErrorCode {
  Success,
  InvalidGoal,
  Busy,
  InvalidGroup,
  InvalidJoints,
  InvalidFrame,
  NoFreshRobotState,
  IkFailed,
  IkTimedOut,
  JointLimitViolation,
  PlanningFailed,
  TrajectoryGenerationFailed,
  TrajectoryRejected,
  TrajectoryExecutionFailed,
  FinalJointToleranceViolated,
  FinalPoseToleranceViolated,
  Canceled,
  InternalError,
};

std::string ToString(MotionErrorCode value);
arrow::Result<MotionErrorCode> MotionErrorCodeFromString(const std::string& value);

struct FollowJointTrajectoryGoal {
  JointTrajectory trajectory;
  std::vector<JointTolerance> path_tolerance;
  std::vector<JointTolerance> goal_tolerance;
  std::optional<std::int64_t> goal_time_tolerance_ns;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<FollowJointTrajectoryGoal> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct FollowJointTrajectoryFeedback {
  std::uint64_t sequence = 0;
  std::uint32_t point_index = 0;
  std::int64_t elapsed_ns = 0;
  std::int64_t duration_ns = 0;
  JointTrajectoryPoint desired;
  JointTrajectoryPoint actual;
  JointTrajectoryPoint error;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<FollowJointTrajectoryFeedback> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct FollowJointTrajectoryResult {
  FollowJointTrajectoryErrorCode error_code = FollowJointTrajectoryErrorCode::Success;
  std::string message;
  std::int64_t elapsed_ns = 0;
  std::vector<std::string> joint_names;
  std::vector<double> final_position_error;
  std::vector<double> final_velocity_error;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<FollowJointTrajectoryResult> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct MoveJointsGoal {
  std::string group_name;
  std::vector<std::string> joint_names;
  std::vector<double> positions;
  double velocity_scale = 1.0;
  double acceleration_scale = 1.0;
  std::optional<std::int64_t> requested_duration_ns;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<MoveJointsGoal> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct MoveJointsFeedback {
  MotionPhase phase = MotionPhase::Validating;
  std::optional<double> progress;
  std::int64_t elapsed_ns = 0;
  std::optional<std::int64_t> estimated_duration_ns;
  std::vector<std::string> joint_names;
  std::vector<double> actual_positions;
  std::vector<double> target_positions;
  std::vector<double> position_errors;
  std::string message;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<MoveJointsFeedback> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct MoveJointsResult {
  MotionErrorCode error_code = MotionErrorCode::Success;
  std::string message;
  std::int64_t elapsed_ns = 0;
  std::vector<std::string> joint_names;
  std::vector<double> final_positions;
  std::vector<double> final_position_errors;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<MoveJointsResult> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct MovePoseGoal {
  std::string group_name;
  std::string reference_frame;
  std::string target_frame;
  Pose target_pose;
  double velocity_scale = 1.0;
  double acceleration_scale = 1.0;
  std::optional<std::int64_t> requested_duration_ns;
  std::optional<double> position_tolerance_m;
  std::optional<double> orientation_tolerance_rad;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<MovePoseGoal> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct MovePoseFeedback {
  MotionPhase phase = MotionPhase::Validating;
  std::optional<double> progress;
  std::int64_t elapsed_ns = 0;
  std::optional<std::int64_t> estimated_duration_ns;
  std::optional<Pose> actual_pose;
  std::optional<double> position_error_m;
  std::optional<double> orientation_error_rad;
  std::string message;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<MovePoseFeedback> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct MovePoseResult {
  MotionErrorCode error_code = MotionErrorCode::Success;
  std::string message;
  std::int64_t elapsed_ns = 0;
  std::optional<Pose> final_pose;
  std::optional<double> final_position_error_m;
  std::optional<double> final_orientation_error_rad;
  std::vector<std::string> joint_names;
  std::vector<double> final_joint_positions;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<MovePoseResult> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct PoseSet {
  std::vector<std::string> name;
  std::vector<double> x;
  std::vector<double> y;
  std::vector<double> z;
  std::vector<double> qx;
  std::vector<double> qy;
  std::vector<double> qz;
  std::vector<double> qw;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<PoseSet> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct Classification {
  std::vector<std::string> class_id;
  std::vector<float> score;

  arrow::Status NormalizeDefaults();
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Classification> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct Keypoint2DSet {
  std::vector<std::string> instance_id;
  std::vector<std::string> detection_id;
  std::vector<std::string> track_id;
  std::vector<std::uint32_t> keypoint_offset;
  std::vector<std::string> keypoint_id;
  std::vector<float> x;
  std::vector<float> y;
  std::vector<float> score;

  arrow::Status NormalizeDefaults();
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Keypoint2DSet> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct Keypoint3DSet {
  std::vector<std::string> instance_id;
  std::vector<std::string> detection_id;
  std::vector<std::string> track_id;
  std::vector<std::uint32_t> keypoint_offset;
  std::vector<std::string> keypoint_id;
  std::vector<float> x;
  std::vector<float> y;
  std::vector<float> z;
  std::vector<float> score;

  arrow::Status NormalizeDefaults();
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Keypoint3DSet> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct Detection2DSet {
  std::vector<std::string> detection_id;
  std::vector<std::string> track_id;
  std::vector<float> center_x;
  std::vector<float> center_y;
  std::vector<float> size_x;
  std::vector<float> size_y;
  std::vector<float> rotation;
  std::vector<std::uint32_t> hypothesis_offset;
  std::vector<std::string> class_id;
  std::vector<float> score;

  static Detection2DSet Empty();
  arrow::Status NormalizeDefaults();
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Detection2DSet> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct Detection3DSet {
  std::vector<std::string> detection_id;
  std::vector<std::string> track_id;
  std::vector<float> center_x;
  std::vector<float> center_y;
  std::vector<float> center_z;
  std::vector<float> qx;
  std::vector<float> qy;
  std::vector<float> qz;
  std::vector<float> qw;
  std::vector<float> size_x;
  std::vector<float> size_y;
  std::vector<float> size_z;
  std::vector<std::uint32_t> hypothesis_offset;
  std::vector<std::string> class_id;
  std::vector<float> score;

  arrow::Status NormalizeDefaults();
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Detection3DSet> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct SegmentationMaskSet {
  std::vector<std::string> mask_id;
  std::vector<std::string> detection_id;
  std::vector<std::string> track_id;
  std::vector<std::uint32_t> x_offset;
  std::vector<std::uint32_t> y_offset;
  std::vector<std::uint32_t> width;
  std::vector<std::uint32_t> height;
  std::string encoding = "mono8";
  std::vector<Bytes> data;
  std::vector<float> score;

  arrow::Status NormalizeDefaults();
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<SegmentationMaskSet> FromRecordBatch(const arrow::RecordBatch& batch);
};

}  // namespace forge_msgs
