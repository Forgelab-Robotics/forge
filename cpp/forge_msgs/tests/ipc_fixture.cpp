#include <cstdint>
#include <iostream>
#include <string>

#include "forge_msgs/forge_msgs.hpp"

namespace {

int Usage() {
  std::cerr
      << "usage: forge_msgs_ipc_fixture <command> <path>\n"
      << "commands: "
         "write/"
         "read-{text,audio,classification,keypoint2d,keypoint3d,segmentation,"
         "follow-joint-trajectory-goal,gripper-command-goal,gripper-command-"
         "feedback,"
         "gripper-command-result,move-joints-goal,move-pose-goal,tool-message}"
         "\n";
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
    forge_msgs::Bytes data;
    for (float value : {0.0f, 0.25f}) {
      auto* bytes = reinterpret_cast<std::uint8_t*>(&value);
      data.insert(data.end(), bytes, bytes + sizeof(float));
    }
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
