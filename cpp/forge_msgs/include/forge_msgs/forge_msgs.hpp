#pragma once

#include <cstdint>
#include <memory>
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
