#pragma once

#include <arrow/api.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <tuple>
#include <type_traits>
#include <utility>
#include <vector>

namespace forge_msgs {

using Bytes = std::vector<std::uint8_t>;

arrow::Status WriteIpcStream(const arrow::RecordBatch& batch,
                             const std::string& path);
arrow::Result<std::shared_ptr<arrow::RecordBatch>> ReadIpcStream(
    const std::string& path);

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
  static arrow::Result<AudioChunk> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<CompressedImage> FromRecordBatch(
      const arrow::RecordBatch& batch);
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

  static arrow::Result<PointCloud> FromXyz(std::vector<float> x,
                                           std::vector<float> y,
                                           std::vector<float> z);
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<PointCloud> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

enum class ByteOrder {
  LittleEndian,
  BigEndian,
};

std::string ToString(ByteOrder value);
arrow::Result<ByteOrder> ByteOrderFromString(const std::string& value);

enum class PointFieldDatatype {
  Int8,
  UInt8,
  Int16,
  UInt16,
  Int32,
  UInt32,
  Int64,
  UInt64,
  Float32,
  Float64,
};

std::string ToString(PointFieldDatatype value);
arrow::Result<PointFieldDatatype> PointFieldDatatypeFromString(
    const std::string& value);
arrow::Result<std::size_t> PointFieldDatatypeSize(PointFieldDatatype value);

struct PointField {
  std::string name;
  std::uint32_t offset = 0;
  PointFieldDatatype datatype = PointFieldDatatype::Float32;
  std::uint32_t count = 1;
};

struct PointCloudBuffer {
  std::uint32_t width = 0;
  std::uint32_t height = 1;
  bool is_dense = false;
  ByteOrder byte_order = ByteOrder::LittleEndian;
  std::uint32_t point_stride = 0;
  std::uint64_t row_stride = 0;
  std::vector<PointField> fields;
  Bytes data;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<PointCloudBuffer> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

class PointCloudBufferView {
 public:
  static arrow::Result<PointCloudBufferView> FromPointCloudBuffer(
      PointCloudBuffer value);
  static arrow::Result<PointCloudBufferView> FromRecordBatch(
      const arrow::RecordBatch& batch);
  static arrow::Result<PointCloudBufferView> FromRecordBatch(
      std::shared_ptr<const arrow::RecordBatch> batch);

  std::uint32_t width() const noexcept { return width_; }
  std::uint32_t height() const noexcept { return height_; }
  bool is_dense() const noexcept { return is_dense_; }
  ByteOrder byte_order() const noexcept { return byte_order_; }
  std::uint32_t point_stride() const noexcept { return point_stride_; }
  std::uint64_t row_stride() const noexcept { return row_stride_; }
  std::span<const PointField> fields() const noexcept { return fields_; }
  std::span<const std::uint8_t> raw_bytes() const noexcept { return data_; }

  const PointField* FindField(std::string_view name) const noexcept;
  arrow::Result<std::span<const std::uint8_t>> PointBytes(
      std::uint32_t row, std::uint32_t column) const;

  template <typename T>
  arrow::Result<T> ReadScalar(std::uint32_t row, std::uint32_t column,
                              std::string_view field_name) const {
    const auto* field = FindField(field_name);
    if (field == nullptr) {
      return arrow::Status::Invalid("point field not found: ",
                                    std::string(field_name));
    }
    return ReadScalar<T>(row, column, *field);
  }

  template <typename T>
  arrow::Result<T> ReadScalar(std::uint32_t row, std::uint32_t column,
                              const PointField& field) const {
    if (field.count != 1) {
      return arrow::Status::Invalid("PointField is not scalar: ", field.name);
    }
    return ReadElement<T>(row, column, field, 0);
  }

  template <typename T>
  arrow::Result<T> ReadElement(std::uint32_t row, std::uint32_t column,
                               std::string_view field_name,
                               std::uint32_t element_index) const {
    const auto* field = FindField(field_name);
    if (field == nullptr) {
      return arrow::Status::Invalid("point field not found: ",
                                    std::string(field_name));
    }
    return ReadElement<T>(row, column, *field, element_index);
  }

  template <typename T>
  arrow::Result<T> ReadElement(std::uint32_t row, std::uint32_t column,
                               const PointField& field,
                               std::uint32_t element_index) const {
    static_assert(IsSupportedScalar<T>(),
                  "PointCloudBufferView field reads require an exact "
                  "fixed-width PointField C++ type");
    T value{};
    ARROW_RETURN_NOT_OK(ReadElementBytes(
        row, column, field, element_index, DatatypeFor<T>(), &value, sizeof(T)));
    return value;
  }

  template <typename T>
  arrow::Result<T> ReadScalarAt(std::uint64_t point_index,
                                std::string_view field_name) const {
    if (width_ == 0) {
      return arrow::Status::IndexError(
          "cannot read a point from a zero-width PointCloudBuffer");
    }
    const auto point_count =
        static_cast<std::uint64_t>(width_) * static_cast<std::uint64_t>(height_);
    if (point_index >= point_count) {
      return arrow::Status::IndexError("point index is out of range");
    }
    return ReadScalar<T>(
        static_cast<std::uint32_t>(point_index / width_),
        static_cast<std::uint32_t>(point_index % width_), field_name);
  }

  template <typename T>
  arrow::Result<T> ReadElementAt(std::uint64_t point_index,
                                 std::string_view field_name,
                                 std::uint32_t element_index) const {
    if (width_ == 0) {
      return arrow::Status::IndexError(
          "cannot read a point from a zero-width PointCloudBuffer");
    }
    const auto point_count =
        static_cast<std::uint64_t>(width_) * static_cast<std::uint64_t>(height_);
    if (point_index >= point_count) {
      return arrow::Status::IndexError("point index is out of range");
    }
    return ReadElement<T>(
        static_cast<std::uint32_t>(point_index / width_),
        static_cast<std::uint32_t>(point_index % width_), field_name,
        element_index);
  }

 private:
  PointCloudBufferView(std::uint32_t width, std::uint32_t height, bool is_dense,
                       ByteOrder byte_order, std::uint32_t point_stride,
                       std::uint64_t row_stride,
                       std::vector<PointField> fields,
                       std::span<const std::uint8_t> data,
                       std::shared_ptr<const void> owner);

  template <typename T>
  static consteval bool IsSupportedScalar() {
    return std::is_same_v<T, std::int8_t> ||
           std::is_same_v<T, std::uint8_t> ||
           std::is_same_v<T, std::int16_t> ||
           std::is_same_v<T, std::uint16_t> ||
           std::is_same_v<T, std::int32_t> ||
           std::is_same_v<T, std::uint32_t> ||
           std::is_same_v<T, std::int64_t> ||
           std::is_same_v<T, std::uint64_t> || std::is_same_v<T, float> ||
           std::is_same_v<T, double>;
  }

  template <typename T>
  static consteval PointFieldDatatype DatatypeFor() {
    if constexpr (std::is_same_v<T, std::int8_t>) {
      return PointFieldDatatype::Int8;
    } else if constexpr (std::is_same_v<T, std::uint8_t>) {
      return PointFieldDatatype::UInt8;
    } else if constexpr (std::is_same_v<T, std::int16_t>) {
      return PointFieldDatatype::Int16;
    } else if constexpr (std::is_same_v<T, std::uint16_t>) {
      return PointFieldDatatype::UInt16;
    } else if constexpr (std::is_same_v<T, std::int32_t>) {
      return PointFieldDatatype::Int32;
    } else if constexpr (std::is_same_v<T, std::uint32_t>) {
      return PointFieldDatatype::UInt32;
    } else if constexpr (std::is_same_v<T, std::int64_t>) {
      return PointFieldDatatype::Int64;
    } else if constexpr (std::is_same_v<T, std::uint64_t>) {
      return PointFieldDatatype::UInt64;
    } else if constexpr (std::is_same_v<T, float>) {
      return PointFieldDatatype::Float32;
    } else {
      static_assert(std::is_same_v<T, double>);
      return PointFieldDatatype::Float64;
    }
  }

  arrow::Status ReadElementBytes(std::uint32_t row, std::uint32_t column,
                                 const PointField& field,
                                 std::uint32_t element_index,
                                 PointFieldDatatype expected_datatype,
                                 void* output, std::size_t output_size) const;

  std::uint32_t width_ = 0;
  std::uint32_t height_ = 0;
  bool is_dense_ = false;
  ByteOrder byte_order_ = ByteOrder::LittleEndian;
  std::uint32_t point_stride_ = 0;
  std::uint64_t row_stride_ = 0;
  std::vector<PointField> fields_;
  std::span<const std::uint8_t> data_;
  std::shared_ptr<const void> owner_;
};

struct ImuOrientation {
  double qx = 0.0;
  double qy = 0.0;
  double qz = 0.0;
  double qw = 1.0;

  arrow::Status Validate() const;
};

struct ImuVector3 {
  double x = 0.0;
  double y = 0.0;
  double z = 0.0;

  arrow::Status Validate() const;
};

struct Imu {
  std::optional<ImuOrientation> orientation;
  ImuVector3 angular_velocity;
  ImuVector3 linear_acceleration;
  std::vector<double> orientation_covariance;
  std::vector<double> angular_velocity_covariance;
  std::vector<double> linear_acceleration_covariance;
  std::optional<double> temperature_celsius;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Imu> FromRecordBatch(const arrow::RecordBatch& batch);
};

struct JointState {
  std::vector<std::string> name;
  std::vector<double> position;
  std::vector<double> velocity;
  std::vector<double> effort;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointState> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<JointCommand> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct LocomotionCommand {
  double vx = 0.0;
  double vy = 0.0;
  double wz = 0.0;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<LocomotionCommand> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct ToolMessage {
  std::string protocol = "forge.tool.endpoint/v1alpha1";
  std::string message_type;
  std::optional<std::string> request_id;
  std::optional<std::string> invocation_id;
  std::optional<std::string> attempt_id;
  std::string endpoint_id;
  std::optional<std::string> endpoint_instance_id;
  std::optional<std::string> operation;
  std::optional<std::int64_t> sequence;
  std::string payload_json = "{}";

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<ToolMessage> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct PolicyCommand {
  std::string policy_id;
  std::string command;
  std::string request_id;
  std::string inputs_json = "{}";

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<PolicyCommand> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<PolicyCommandStatus> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<JointTrajectoryPoint> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct JointTrajectory {
  std::vector<std::string> joint_names;
  std::vector<JointTrajectoryPoint> points;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointTrajectory> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct JointTolerance {
  std::string joint_name;
  std::optional<double> position;
  std::optional<double> velocity;
  std::optional<double> acceleration;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<JointTolerance> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
arrow::Result<FollowJointTrajectoryErrorCode>
FollowJointTrajectoryErrorCodeFromString(const std::string& value);

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
arrow::Result<MotionErrorCode> MotionErrorCodeFromString(
    const std::string& value);

enum class GripperCommandErrorCode {
  Success,
  InvalidGoal,
  Busy,
  PositionLimitViolation,
  UnsupportedVelocity,
  UnsupportedEffort,
  NoFreshRobotState,
  FeedbackStale,
  Stalled,
  ExecutionTimedOut,
  HardwareFault,
  Canceled,
  InternalError,
};

std::string ToString(GripperCommandErrorCode value);
arrow::Result<GripperCommandErrorCode> GripperCommandErrorCodeFromString(
    const std::string& value);

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
  FollowJointTrajectoryErrorCode error_code =
      FollowJointTrajectoryErrorCode::Success;
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

struct GripperCommandGoal {
  double position = 0.0;
  std::optional<double> max_velocity;
  std::optional<double> max_effort;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<GripperCommandGoal> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct GripperCommandFeedback {
  std::int64_t elapsed_ns = 0;
  double position = 0.0;
  std::optional<double> velocity;
  std::optional<double> effort;
  bool stalled = false;
  bool reached_goal = false;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<GripperCommandFeedback> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct GripperCommandResult {
  GripperCommandErrorCode error_code = GripperCommandErrorCode::Success;
  std::string message;
  std::int64_t elapsed_ns = 0;
  std::optional<double> position;
  std::optional<double> velocity;
  std::optional<double> effort;
  bool stalled = false;
  bool reached_goal = false;

  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<GripperCommandResult> FromRecordBatch(
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
  static arrow::Result<MoveJointsGoal> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<MoveJointsFeedback> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<MoveJointsResult> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<MovePoseGoal> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<MovePoseFeedback> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<MovePoseResult> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<PoseSet> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

struct Classification {
  std::vector<std::string> class_id;
  std::vector<float> score;

  arrow::Status NormalizeDefaults();
  arrow::Status Validate() const;
  arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToRecordBatch() const;
  static arrow::Result<Classification> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<Keypoint2DSet> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<Keypoint3DSet> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<Detection2DSet> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<Detection3DSet> FromRecordBatch(
      const arrow::RecordBatch& batch);
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
  static arrow::Result<SegmentationMaskSet> FromRecordBatch(
      const arrow::RecordBatch& batch);
};

}  // namespace forge_msgs
