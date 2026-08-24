#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#include "forge_msgs/forge_msgs.hpp"

namespace {

int Usage() {
  std::cerr
      << "usage: forge_msgs_ipc_fixture <command> <path>\n"
      << "commands: "
         "write/"
         "read-{text,audio,point-cloud,point-cloud-buffer,imu,classification,"
         "keypoint2d,keypoint3d,segmentation,follow-joint-trajectory-goal,"
         "gripper-command-goal,"
         "gripper-command-feedback,gripper-command-result,move-joints-goal,"
         "move-pose-goal,tool-message}\n";
  return 2;
}

int WriteBatch(const std::shared_ptr<arrow::RecordBatch>& batch,
               const std::string& path) {
  auto status = forge_msgs::WriteIpcStream(*batch, path);
  if (!status.ok()) {
    std::cerr << status.ToString() << "\n";
    return 1;
  }
  return 0;
}

template <typename T>
void StoreScalar(forge_msgs::Bytes& data, std::size_t offset, T value,
                 forge_msgs::ByteOrder byte_order) {
  std::array<std::uint8_t, sizeof(T)> bytes{};
  std::memcpy(bytes.data(), &value, sizeof(T));
  bool reverse = false;
  if constexpr (std::endian::native == std::endian::little) {
    reverse = byte_order == forge_msgs::ByteOrder::BigEndian;
  } else if constexpr (std::endian::native == std::endian::big) {
    reverse = byte_order == forge_msgs::ByteOrder::LittleEndian;
  }
  if (reverse) std::reverse(bytes.begin(), bytes.end());
  std::copy(bytes.begin(), bytes.end(), data.begin() + offset);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) return Usage();

  std::string command = argv[1];
  std::string path = argv[2];

  if (command == "write-text") {
    auto batch = forge_msgs::Text{"cpp hello"}.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-text") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto text = forge_msgs::Text::FromRecordBatch(**batch);
    if (!text.ok()) {
      std::cerr << text.status().ToString() << "\n";
      return 1;
    }
    std::cout << text->text << "\n";
    return 0;
  }

  if (command == "write-tool-message" ||
      command == "write-unresolved-tool-message") {
    forge_msgs::ToolMessage value;
    value.message_type = command == "write-tool-message"
                             ? "tool.invoke.request"
                             : "tool.invoke.response";
    value.request_id = "cpp-request-1";
    value.invocation_id = "cpp-invocation-1";
    value.attempt_id = "cpp-attempt-1";
    value.endpoint_id = "vision.yolo";
    if (command == "write-tool-message") {
      value.endpoint_instance_id = "cpp-instance-1";
      value.payload_json = "{\"arguments\":{\"class\":\"cube\"}}";
    } else {
      value.payload_json =
          "{\"accepted\":{\"details\":{}},\"outcome\":\"accepted\"}";
    }
    value.operation = "detect";
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-tool-message") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::ToolMessage::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << value->message_type << " "
              << (value->request_id ? *value->request_id : "null") << " "
              << (value->invocation_id ? *value->invocation_id : "null") << " "
              << (value->attempt_id ? *value->attempt_id : "null") << " "
              << value->endpoint_id << " "
              << (value->endpoint_instance_id ? *value->endpoint_instance_id
                                              : "null")
              << " " << (value->operation ? *value->operation : "null") << " ";
    if (value->sequence) {
      std::cout << *value->sequence;
    } else {
      std::cout << "null";
    }
    std::cout << " " << value->payload_json << "\n";
    return 0;
  }

  if (command == "write-audio") {
    forge_msgs::Bytes data(2 * sizeof(float));
    StoreScalar(data, 0, 0.0f, forge_msgs::ByteOrder::LittleEndian);
    StoreScalar(data, sizeof(float), 0.25f,
                forge_msgs::ByteOrder::LittleEndian);
    auto batch =
        forge_msgs::AudioChunk{16000, 1, "f32le", 2, data}.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-audio") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto audio = forge_msgs::AudioChunk::FromRecordBatch(**batch);
    if (!audio.ok()) {
      std::cerr << audio.status().ToString() << "\n";
      return 1;
    }
    std::cout << audio->sample_rate << " " << audio->channels << " "
              << audio->sample_format << " " << audio->frame_count << " "
              << audio->data.size() << "\n";
    return 0;
  }

  if (command == "write-point-cloud") {
    forge_msgs::PointCloud value{2, 1, true, {1.0f, 2.0f}, {3.0f, 4.0f}, {5.0f, 6.0f},
                                 {}, {255, 0}, {0, 255}, {0, 0}};
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-point-cloud") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::PointCloud::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << value->width << " " << value->height << " " << value->x.size() << " "
              << value->is_dense;
    if (value->x.empty()) {
      std::cout << " empty\n";
      return 0;
    }
    std::cout << " " << value->x.back() << " " << value->y.back() << " " << value->z.back();
    if (value->red.empty()) {
      std::cout << " no-rgb";
    } else {
      std::cout << " " << static_cast<unsigned>(value->red.back()) << " "
                << static_cast<unsigned>(value->green.back()) << " "
                << static_cast<unsigned>(value->blue.back());
    }
    if (value->intensity.empty()) {
      std::cout << " empty\n";
    } else {
      std::cout << " " << value->intensity.back() << "\n";
    }
    return 0;
  }

  if (command == "write-point-cloud-buffer") {
    using forge_msgs::PointField;
    using forge_msgs::PointFieldDatatype;
    forge_msgs::PointCloudBuffer value;
    value.width = 2;
    value.height = 1;
    value.is_dense = true;
    value.byte_order = forge_msgs::ByteOrder::LittleEndian;
    value.point_stride = 16;
    value.row_stride = 32;
    value.fields = {
        PointField{"ring", 12, PointFieldDatatype::UInt16, 1},
        PointField{"z", 8, PointFieldDatatype::Float32, 1},
        PointField{"x", 0, PointFieldDatatype::Float32, 1},
        PointField{"y", 4, PointFieldDatatype::Float32, 1},
    };
    value.data.assign(32, 0);
    for (std::uint32_t point = 0; point < value.width; ++point) {
      const std::size_t offset = point * value.point_stride;
      StoreScalar(value.data, offset, static_cast<float>(point * 3 + 1),
                  value.byte_order);
      StoreScalar(value.data, offset + 4,
                  static_cast<float>(point * 3 + 2), value.byte_order);
      StoreScalar(value.data, offset + 8,
                  static_cast<float>(point * 3 + 3), value.byte_order);
      StoreScalar(value.data, offset + 12,
                  static_cast<std::uint16_t>(point + 7), value.byte_order);
    }
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-point-cloud-buffer") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    std::shared_ptr<const arrow::RecordBatch> owner = *batch;
    auto view =
        forge_msgs::PointCloudBufferView::FromRecordBatch(std::move(owner));
    if (!view.ok()) {
      std::cerr << view.status().ToString() << "\n";
      return 1;
    }
    if (view->width() == 0) {
      std::cerr << "PointCloudBuffer fixture requires at least one point\n";
      return 1;
    }
    const auto row = view->height() - 1;
    const auto column = view->width() - 1;
    auto x = view->ReadScalar<float>(row, column, "x");
    auto y = view->ReadScalar<float>(row, column, "y");
    auto z = view->ReadScalar<float>(row, column, "z");
    auto ring = view->ReadScalar<std::uint16_t>(row, column, "ring");
    if (!x.ok() || !y.ok() || !z.ok() || !ring.ok()) {
      const auto status = !x.ok()   ? x.status()
                          : !y.ok() ? y.status()
                          : !z.ok() ? z.status()
                                    : ring.status();
      std::cerr << status.ToString() << "\n";
      return 1;
    }
    std::cout << view->width() << " " << view->height() << " "
              << forge_msgs::ToString(view->byte_order()) << " "
              << view->fields().size() << " " << view->raw_bytes().size()
              << " " << *x << " " << *y << " " << *z << " " << *ring
              << "\n";
    return 0;
  }

  if (command == "write-imu") {
    forge_msgs::Imu value;
    value.orientation = forge_msgs::ImuOrientation{0.0, 0.0, 0.0, 2.0};
    value.angular_velocity = {0.1, 0.2, 0.3};
    value.linear_acceleration = {1.0, 2.0, 9.8};
    value.orientation_covariance = {1.0, 0.0, 0.0, 0.0, 2.0,
                                    0.0, 0.0, 0.0, 3.0};
    value.angular_velocity_covariance = {};
    value.linear_acceleration_covariance = {4.0, 0.0, 0.0, 0.0, 5.0,
                                            0.0, 0.0, 0.0, 6.0};
    value.temperature_celsius = std::nullopt;
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-imu") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::Imu::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->orientation) {
      std::cout << value->orientation->qw;
    } else {
      std::cout << "null";
    }
    std::cout << " " << value->angular_velocity.z << " "
              << value->linear_acceleration.z << " "
              << value->orientation_covariance.size() << " "
              << value->angular_velocity_covariance.size() << " "
              << value->linear_acceleration_covariance.size() << " ";
    if (value->temperature_celsius) {
      std::cout << *value->temperature_celsius;
    } else {
      std::cout << "null";
    }
    std::cout << "\n";
    return 0;
  }

  if (command == "write-classification") {
    auto batch = forge_msgs::Classification{{"person", "vehicle"}, {0.9f, 0.1f}}
                     .ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-classification") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::Classification::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->class_id.empty()) {
      std::cout << "0 empty\n";
    } else {
      std::cout << value->class_id.size() << " " << value->class_id.front()
                << " " << value->score.front() << "\n";
    }
    return 0;
  }

  if (command == "write-keypoint2d") {
    auto batch = forge_msgs::Keypoint2DSet{{"person-0"},
                                           {"d0"},
                                           {"track-0"},
                                           {0, 2},
                                           {"left_eye", "right_eye"},
                                           {10.0f, 12.0f},
                                           {20.0f, 20.0f},
                                           {0.9f, 0.8f}}
                     .ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-keypoint2d") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::Keypoint2DSet::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->instance_id.empty() || value->keypoint_id.empty()) {
      std::cout << value->instance_id.size() << " " << value->keypoint_id.size()
                << " empty\n";
    } else {
      std::cout << value->instance_id.front() << " "
                << value->keypoint_id.size() << " " << value->x.front() << " "
                << value->score.front() << "\n";
    }
    return 0;
  }

  if (command == "write-keypoint3d") {
    auto batch = forge_msgs::Keypoint3DSet{{"person-0"}, {"d0"},   {"track-0"},
                                           {0, 1},       {"nose"}, {1.0f},
                                           {2.0f},       {3.0f},   {0.95f}}
                     .ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-keypoint3d") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::Keypoint3DSet::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->instance_id.empty() || value->keypoint_id.empty()) {
      std::cout << value->instance_id.size() << " " << value->keypoint_id.size()
                << " empty\n";
    } else {
      std::cout << value->instance_id.front() << " "
                << value->keypoint_id.front() << " " << value->z.front() << " "
                << value->score.front() << "\n";
    }
    return 0;
  }

  if (command == "write-segmentation") {
    auto batch =
        forge_msgs::SegmentationMaskSet{
            {"m0"}, {"d0"},  {"track-0"},        {4},    {5}, {2},
            {2},    "mono8", {{0, 255, 255, 0}}, {0.98f}}
            .ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-segmentation") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::SegmentationMaskSet::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->mask_id.empty()) {
      std::cout << "0 0 empty\n";
    } else {
      std::cout << value->mask_id.front() << " " << value->data.front().size()
                << " ";
      if (value->score.empty()) {
        std::cout << "empty\n";
      } else {
        std::cout << value->score.front() << "\n";
      }
    }
    return 0;
  }

  if (command == "write-gripper-command-goal") {
    forge_msgs::GripperCommandGoal value{0.08, std::nullopt, 12.0};
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-gripper-command-goal") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::GripperCommandGoal::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << value->position << " ";
    if (value->max_velocity) {
      std::cout << *value->max_velocity << " ";
    } else {
      std::cout << "null ";
    }
    if (value->max_effort) {
      std::cout << *value->max_effort << "\n";
    } else {
      std::cout << "null\n";
    }
    return 0;
  }

  if (command == "write-gripper-command-feedback") {
    forge_msgs::GripperCommandFeedback value{15,    1.2,   std::nullopt,
                                             -0.25, false, false};
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-gripper-command-feedback") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::GripperCommandFeedback::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << value->elapsed_ns << " " << value->position << " ";
    if (value->velocity) {
      std::cout << *value->velocity << " ";
    } else {
      std::cout << "null ";
    }
    if (value->effort) {
      std::cout << *value->effort << " ";
    } else {
      std::cout << "null ";
    }
    std::cout << value->stalled << " " << value->reached_goal << "\n";
    return 0;
  }

  if (command == "write-gripper-command-result") {
    forge_msgs::GripperCommandResult value{
        forge_msgs::GripperCommandErrorCode::NoFreshRobotState,
        "state_unavailable",
        0,
        std::nullopt,
        std::nullopt,
        std::nullopt,
        false,
        false};
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-gripper-command-result") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::GripperCommandResult::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << forge_msgs::ToString(value->error_code) << " "
              << value->message << " " << value->elapsed_ns << " ";
    if (value->position) {
      std::cout << *value->position << " ";
    } else {
      std::cout << "null ";
    }
    if (value->velocity) {
      std::cout << *value->velocity << " ";
    } else {
      std::cout << "null ";
    }
    if (value->effort) {
      std::cout << *value->effort << " ";
    } else {
      std::cout << "null ";
    }
    std::cout << value->stalled << " " << value->reached_goal << "\n";
    return 0;
  }

  if (command == "write-follow-joint-trajectory-goal") {
    forge_msgs::JointTrajectory trajectory{
        {"joint_1", "joint_2"},
        {{{0.0, 0.5}, {}, {}, {}, 0},
         {{1.0, 1.5}, {0.1, 0.2}, {}, {}, 1000000}}};
    forge_msgs::FollowJointTrajectoryGoal value{
        trajectory,
        {{"joint_1", 0.05, std::nullopt, std::nullopt}},
        {},
        2000000};
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-follow-joint-trajectory-goal") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value =
        forge_msgs::FollowJointTrajectoryGoal::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << value->trajectory.joint_names.size() << " "
              << value->trajectory.points.size() << " "
              << value->path_tolerance.size() << " ";
    if (value->goal_time_tolerance_ns) {
      std::cout << *value->goal_time_tolerance_ns << "\n";
    } else {
      std::cout << "null\n";
    }
    return 0;
  }

  if (command == "write-move-joints-goal") {
    forge_msgs::MoveJointsGoal value{
        "arm", {"joint_1", "joint_2"}, {1.0, 1.5}, 0.5, 0.4, std::nullopt};
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-move-joints-goal") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::MoveJointsGoal::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << value->group_name << " " << value->joint_names.size() << " "
              << value->positions.front() << " ";
    if (value->requested_duration_ns) {
      std::cout << *value->requested_duration_ns << "\n";
    } else {
      std::cout << "null\n";
    }
    return 0;
  }

  if (command == "write-move-pose-goal") {
    forge_msgs::MovePoseGoal value{
        "arm",        "world",
        "tool0",      forge_msgs::Pose::Identity(0.4, 0.2, 0.3),
        0.5,          0.4,
        std::nullopt, 0.01,
        std::nullopt};
    auto batch = value.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-move-pose-goal") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::MovePoseGoal::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    std::cout << value->group_name << " " << value->reference_frame << " "
              << value->target_frame << " " << value->target_pose.x << " ";
    if (value->requested_duration_ns) {
      std::cout << *value->requested_duration_ns << " ";
    } else {
      std::cout << "null ";
    }
    if (value->position_tolerance_m) {
      std::cout << *value->position_tolerance_m << "\n";
    } else {
      std::cout << "null\n";
    }
    return 0;
  }

  return Usage();
}
