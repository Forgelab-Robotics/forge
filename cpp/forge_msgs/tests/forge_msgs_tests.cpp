#include "forge_msgs/forge_msgs.hpp"

#include <cmath>
#include <iostream>
#include <string>
#include <tuple>
#include <vector>

namespace {

int failures = 0;

void Check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << "\n";
    ++failures;
  }
}

void CheckFieldOrder(const arrow::RecordBatch& batch,
                     const std::vector<std::string>& expected,
                     const std::string& name) {
  Check(batch.num_columns() == static_cast<int>(expected.size()), name + " field count");
  if (batch.num_columns() != static_cast<int>(expected.size())) return;
  for (int i = 0; i < batch.num_columns(); ++i) {
    Check(batch.schema()->field(i)->name() == expected[static_cast<std::size_t>(i)],
          name + " field order at " + std::to_string(i));
  }
}

template <typename Message>
void CheckRoundTrip(const Message& message, const std::string& name) {
  auto batch = message.ToRecordBatch();
  Check(batch.ok(), name + " ToRecordBatch");
  if (!batch.ok()) return;
  auto back = Message::FromRecordBatch(**batch);
  Check(back.ok(), name + " FromRecordBatch");
  if (!back.ok()) return;
  Check((*back).ToRecordBatch().ok(), name + " returned value is valid");
}

template <typename Message>
void CheckSchema(const Message& message,
                 const std::vector<std::shared_ptr<arrow::Field>>& expected,
                 const std::string& name) {
  auto batch = message.ToRecordBatch();
  Check(batch.ok(), name + " schema batch");
  if (!batch.ok()) return;
  Check((*batch)->schema()->Equals(*arrow::schema(expected), false), name + " exact schema");
  Check((*batch)->GetColumnByName("goal_id") == nullptr, name + " excludes goal_id");
  Check((*batch)->GetColumnByName("goal_status") == nullptr, name + " excludes goal_status");
}

}  // namespace

int main() {
  using namespace forge_msgs;

  CheckRoundTrip(Text{"前进"}, "Text");

  Bytes audio_data;
  for (float value : {0.0f, 0.25f, -0.5f, 1.0f}) {
    auto* bytes = reinterpret_cast<std::uint8_t*>(&value);
    audio_data.insert(audio_data.end(), bytes, bytes + sizeof(float));
  }
  CheckRoundTrip(AudioChunk{16000, 1, "f32le", 4, audio_data}, "AudioChunk");
  Check(!AudioChunk{16000, 2, "s16le", 2, {1, 2, 3}}.Validate().ok(),
        "AudioChunk rejects invalid data length");

  CheckRoundTrip(Image{2, 2, "rgb8", 6, Bytes{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}},
                 "Image");
  CheckRoundTrip(CompressedImage{"jpeg", Bytes{0xff, 0xd8, 0xff, 0xd9}}, "CompressedImage");

  CheckRoundTrip(PointCloud{2, 1, true, {1.0f, 2.0f}, {3.0f, 4.0f}, {5.0f, 6.0f},
                            {}, {255, 0}, {0, 255}, {0, 0}},
                 "PointCloud");
  Check(!PointCloud{1, 1, true, {NAN}, {0.0f}, {0.0f}, {}, {}, {}, {}}.Validate().ok(),
        "PointCloud rejects dense NaN");

  CheckRoundTrip(JointState{{"j1", "j2"}, {1.0, 2.0}, {0.1, 0.2}, {}}, "JointState");
  CheckRoundTrip(JointCommand{{"j1"}, "hybrid", {1.0}, {0.0}, {0.5}, {20.0}, {1.0}},
                 "JointCommand");
  Check(!JointCommand{{"j1"}, "bad", {}, {}, {}, {}, {}}.Validate().ok(),
        "JointCommand rejects invalid mode");

  CheckRoundTrip(LocomotionCommand{0.5, 0.1, 0.2}, "LocomotionCommand");
  Check(!LocomotionCommand{NAN, 0.0, 0.0}.Validate().ok(),
        "LocomotionCommand rejects NaN");

  CheckRoundTrip(PolicyCommand{"default", "start_recording", "rec-001", "{\"path\":\"x\"}"},
                 "PolicyCommand");
  CheckRoundTrip(PolicyCommandStatus{"default", "start_recording", "rec-001",
                                     PolicyCommandStatusValue::Done, "done", "{\"ok\":true}"},
                 "PolicyCommandStatus");
  Check(!PolicyCommand{"default", "Start", "", "{}"}.Validate().ok(),
        "PolicyCommand rejects non snake_case");

  auto pose = Pose::FromXyYaw(1.0, 2.0, 1.5707963267948966, 0.0);
  CheckRoundTrip(pose, "Pose");
  auto [x, y, yaw] = pose.XyYaw();
  Check(x == 1.0 && y == 2.0 && std::abs(yaw - 1.5707963267948966) < 1e-12,
        "Pose XyYaw helper");
  CheckRoundTrip(PoseSet{{"a", "b"}, {1.0, 2.0}, {2.0, 3.0}, {0.0, 0.0},
                         {0.0, 0.0}, {0.0, 0.0}, {0.0, 0.0}, {1.0, 1.0}},
                 "PoseSet");

  const auto f64_list = arrow::list(arrow::field("item", arrow::float64(), true));
  const auto string_list = arrow::list(arrow::field("item", arrow::utf8(), true));
  const std::vector<std::shared_ptr<arrow::Field>> point_fields = {
      arrow::field("positions", f64_list, false),
      arrow::field("velocities", f64_list, false),
      arrow::field("accelerations", f64_list, false),
      arrow::field("effort", f64_list, false),
      arrow::field("time_from_start_ns", arrow::int64(), false)};
  const auto point_type = arrow::struct_(point_fields);
  const std::vector<std::shared_ptr<arrow::Field>> trajectory_fields = {
      arrow::field("joint_names", string_list, false),
      arrow::field("points", arrow::list(arrow::field("item", point_type, true)), false)};
  const auto trajectory_type = arrow::struct_(trajectory_fields);
  const std::vector<std::shared_ptr<arrow::Field>> tolerance_fields = {
      arrow::field("joint_name", arrow::utf8(), false),
      arrow::field("position", arrow::float64(), true),
      arrow::field("velocity", arrow::float64(), true),
      arrow::field("acceleration", arrow::float64(), true)};
  const auto tolerance_type = arrow::struct_(tolerance_fields);
  const std::vector<std::shared_ptr<arrow::Field>> pose_fields = {
      arrow::field("x", arrow::float64(), false),
      arrow::field("y", arrow::float64(), false),
      arrow::field("z", arrow::float64(), false),
      arrow::field("qx", arrow::float64(), false),
      arrow::field("qy", arrow::float64(), false),
      arrow::field("qz", arrow::float64(), false),
      arrow::field("qw", arrow::float64(), false)};
  const auto pose_type = arrow::struct_(pose_fields);

  JointTrajectoryPoint point0{{0.0, 0.5}, {}, {}, {}, 0};
  JointTrajectoryPoint point1{{1.0, 1.5}, {0.1, 0.2}, {0.0, 0.0}, {}, 1000000};
  JointTrajectory trajectory{{"joint_1", "joint_2"}, {point0, point1}};
  JointTolerance tolerance{"joint_1", 0.05, std::nullopt, 0.1};
  FollowJointTrajectoryGoal follow_goal{trajectory, {tolerance}, {}, 2000000};
  FollowJointTrajectoryFeedback follow_feedback{7, 1, 1000000, 2000000,
                                                point1, point1,
                                                {{0.01, -0.01}, {}, {}, {}, 1000000}};
  FollowJointTrajectoryResult follow_result{FollowJointTrajectoryErrorCode::Success, "done",
                                            2000000, {"joint_1", "joint_2"},
                                            {0.01, -0.01}, {}};
  MoveJointsGoal move_joints_goal{"arm", {"joint_1", "joint_2"}, {1.0, 1.5},
                                  0.5, 0.4, std::nullopt};
  MoveJointsFeedback move_joints_feedback{MotionPhase::Executing, 0.5, 1000000,
                                          2000000, {"joint_1", "joint_2"},
                                          {0.5, 0.75}, {1.0, 1.5}, {0.5, 0.75}, "moving"};
  MoveJointsResult move_joints_result{MotionErrorCode::Success, "done", 2000000,
                                      {"joint_1", "joint_2"}, {1.0, 1.5}, {0.0, 0.0}};
  MovePoseGoal move_pose_goal{"arm", "world", "tool0", Pose::Identity(0.4, 0.2, 0.3),
                              0.5, 0.4, std::nullopt, 0.01, std::nullopt};
  MovePoseFeedback move_pose_feedback{MotionPhase::Executing, 0.5, 1000000,
                                      std::nullopt, std::nullopt, std::nullopt,
                                      std::nullopt, "planning"};
  MovePoseResult move_pose_result{MotionErrorCode::Success, "done", 2000000,
                                  Pose::Identity(0.4, 0.2, 0.3), 0.001, 0.002,
                                  {"joint_1", "joint_2"}, {1.0, 1.5}};

  CheckRoundTrip(point0, "JointTrajectoryPoint");
  CheckRoundTrip(trajectory, "JointTrajectory");
  CheckRoundTrip(tolerance, "JointTolerance");
  CheckRoundTrip(follow_goal, "FollowJointTrajectoryGoal");
  CheckRoundTrip(follow_feedback, "FollowJointTrajectoryFeedback");
  CheckRoundTrip(follow_result, "FollowJointTrajectoryResult");
  CheckRoundTrip(move_joints_goal, "MoveJointsGoal");
  CheckRoundTrip(move_joints_feedback, "MoveJointsFeedback");
  CheckRoundTrip(move_joints_result, "MoveJointsResult");
  CheckRoundTrip(move_pose_goal, "MovePoseGoal");
  CheckRoundTrip(move_pose_feedback, "MovePoseFeedback nullable pose");
  CheckRoundTrip(move_pose_result, "MovePoseResult");

  CheckSchema(point0, point_fields, "JointTrajectoryPoint");
  CheckSchema(trajectory, trajectory_fields, "JointTrajectory");
  CheckSchema(tolerance, tolerance_fields, "JointTolerance");
  CheckSchema(follow_goal,
              {arrow::field("trajectory", trajectory_type, false),
               arrow::field("path_tolerance",
                            arrow::list(arrow::field("item", tolerance_type, true)), false),
               arrow::field("goal_tolerance",
                            arrow::list(arrow::field("item", tolerance_type, true)), false),
               arrow::field("goal_time_tolerance_ns", arrow::int64(), true)},
              "FollowJointTrajectoryGoal");
  CheckSchema(follow_feedback,
              {arrow::field("sequence", arrow::uint64(), false),
               arrow::field("point_index", arrow::uint32(), false),
               arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("duration_ns", arrow::int64(), false),
               arrow::field("desired", point_type, false),
               arrow::field("actual", point_type, false),
               arrow::field("error", point_type, false)},
              "FollowJointTrajectoryFeedback");
  CheckSchema(follow_result,
              {arrow::field("error_code", arrow::utf8(), false),
               arrow::field("message", arrow::utf8(), false),
               arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("joint_names", string_list, false),
               arrow::field("final_position_error", f64_list, false),
               arrow::field("final_velocity_error", f64_list, false)},
              "FollowJointTrajectoryResult");
  CheckSchema(move_joints_goal,
              {arrow::field("group_name", arrow::utf8(), false),
               arrow::field("joint_names", string_list, false),
               arrow::field("positions", f64_list, false),
               arrow::field("velocity_scale", arrow::float64(), false),
               arrow::field("acceleration_scale", arrow::float64(), false),
               arrow::field("requested_duration_ns", arrow::int64(), true)},
              "MoveJointsGoal");
  CheckSchema(move_joints_feedback,
              {arrow::field("phase", arrow::utf8(), false),
               arrow::field("progress", arrow::float64(), true),
               arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("estimated_duration_ns", arrow::int64(), true),
               arrow::field("joint_names", string_list, false),
               arrow::field("actual_positions", f64_list, false),
               arrow::field("target_positions", f64_list, false),
               arrow::field("position_errors", f64_list, false),
               arrow::field("message", arrow::utf8(), false)},
              "MoveJointsFeedback");
  CheckSchema(move_joints_result,
              {arrow::field("error_code", arrow::utf8(), false),
               arrow::field("message", arrow::utf8(), false),
               arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("joint_names", string_list, false),
               arrow::field("final_positions", f64_list, false),
               arrow::field("final_position_errors", f64_list, false)},
              "MoveJointsResult");
  CheckSchema(move_pose_goal,
              {arrow::field("group_name", arrow::utf8(), false),
               arrow::field("reference_frame", arrow::utf8(), false),
               arrow::field("target_frame", arrow::utf8(), false),
               arrow::field("target_pose", pose_type, false),
               arrow::field("velocity_scale", arrow::float64(), false),
               arrow::field("acceleration_scale", arrow::float64(), false),
               arrow::field("requested_duration_ns", arrow::int64(), true),
               arrow::field("position_tolerance_m", arrow::float64(), true),
               arrow::field("orientation_tolerance_rad", arrow::float64(), true)},
              "MovePoseGoal");
  CheckSchema(move_pose_feedback,
              {arrow::field("phase", arrow::utf8(), false),
               arrow::field("progress", arrow::float64(), true),
               arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("estimated_duration_ns", arrow::int64(), true),
               arrow::field("actual_pose", pose_type, true),
               arrow::field("position_error_m", arrow::float64(), true),
               arrow::field("orientation_error_rad", arrow::float64(), true),
               arrow::field("message", arrow::utf8(), false)},
              "MovePoseFeedback");
  CheckSchema(move_pose_result,
              {arrow::field("error_code", arrow::utf8(), false),
               arrow::field("message", arrow::utf8(), false),
               arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("final_pose", pose_type, true),
               arrow::field("final_position_error_m", arrow::float64(), true),
               arrow::field("final_orientation_error_rad", arrow::float64(), true),
               arrow::field("joint_names", string_list, false),
               arrow::field("final_joint_positions", f64_list, false)},
              "MovePoseResult");

  Check(ToString(FollowJointTrajectoryErrorCode::FeedbackStale) == "FEEDBACK_STALE",
        "FollowJointTrajectoryErrorCode string value");
  Check(FollowJointTrajectoryErrorCodeFromString("HARDWARE_FAULT").ok(),
        "FollowJointTrajectoryErrorCode parses schema value");
  Check(ToString(MotionPhase::WaitingForController) == "WAITING_FOR_CONTROLLER",
        "MotionPhase string value");
  Check(MotionPhaseFromString("bad").status().IsInvalid(), "MotionPhase rejects invalid value");
  Check(ToString(MotionErrorCode::IkTimedOut) == "IK_TIMED_OUT",
        "MotionErrorCode string value");
  Check(MotionErrorCodeFromString("FINAL_POSE_TOLERANCE_VIOLATED").ok(),
        "MotionErrorCode parses schema value");

  Check(!JointTrajectory{{"joint_1"}, {point0, point0}}.Validate().ok(),
        "JointTrajectory rejects non-increasing time");
  Check(!JointTolerance{"joint_1", std::nullopt, std::nullopt, std::nullopt}.Validate().ok(),
        "JointTolerance requires one tolerance");
  Check(!MoveJointsGoal{"arm", {"joint_1"}, {NAN}, 0.5, 0.5, std::nullopt}
             .Validate().ok(),
        "MoveJointsGoal rejects non-finite position");
  Check(!MovePoseGoal{"arm", "world", "tool0", Pose{}, 0.0, 0.5, std::nullopt,
                      std::nullopt, std::nullopt}.Validate().ok(),
        "MovePoseGoal rejects zero scale");
  auto nullable_feedback_batch = move_pose_feedback.ToRecordBatch();
  Check(nullable_feedback_batch.ok() &&
            (*nullable_feedback_batch)->GetColumnByName("actual_pose")->IsNull(0),
        "MovePoseFeedback emits null optional pose");

  CheckRoundTrip(Classification{{"person", "vehicle"}, {0.9f, 0.1f}}, "Classification");
  Check(!Classification{{"person", "person"}, {0.9f, 0.1f}}.Validate().ok(),
        "Classification rejects duplicate class_id");
  Check(!Classification{{"person"}, {NAN}}.Validate().ok(),
        "Classification rejects non-finite score");
  Check(!Classification{{"person"}, {1.1f}}.Validate().ok(),
        "Classification rejects score outside [0, 1]");

  Keypoint2DSet keypoints_2d{{"person-0", "person-1"}, {}, {}, {0, 2, 3},
                            {"left_eye", "right_eye", "left_eye"},
                            {10.0f, 12.0f, 30.0f}, {20.0f, 20.0f, 40.0f},
                            {0.9f, 0.8f, 0.7f}};
  CheckRoundTrip(keypoints_2d, "Keypoint2DSet");
  auto keypoints_2d_batch = keypoints_2d.ToRecordBatch();
  Check(keypoints_2d_batch.ok(), "Keypoint2DSet schema batch");
  if (keypoints_2d_batch.ok()) {
    CheckFieldOrder(**keypoints_2d_batch,
                    {"instance_id", "detection_id", "track_id", "keypoint_offset",
                     "keypoint_id", "x", "y", "score"},
                    "Keypoint2DSet");
  }
  CheckRoundTrip(Keypoint2DSet{}, "Keypoint2DSet empty defaults");
  Check(!Keypoint2DSet{{"a", "a"}, {"", ""}, {"", ""}, {0, 0, 0}, {}, {}, {}, {}}
             .Validate()
             .ok(),
        "Keypoint2DSet rejects duplicate instance_id");
  Check(!Keypoint2DSet{{"a"}, {""}, {""}, {0, 2}, {"nose", "nose"},
                       {1.0f, 2.0f}, {3.0f, 4.0f}, {0.8f, 0.7f}}
             .Validate()
             .ok(),
        "Keypoint2DSet rejects duplicate keypoint_id within an instance");
  Check(Keypoint2DSet{{"a", "b"}, {"", ""}, {"", ""}, {0, 1, 2}, {"nose", "nose"},
                      {1.0f, 2.0f}, {3.0f, 4.0f}, {0.8f, 0.7f}}
            .Validate()
            .ok(),
        "Keypoint2DSet allows keypoint_id reuse across instances");
  Check(!Keypoint2DSet{{"a"}, {""}, {""}, {1, 1}, {}, {}, {}, {}}.Validate().ok(),
        "Keypoint2DSet rejects offset not starting at zero");
  Check(!Keypoint2DSet{{"a"}, {""}, {""}, {0, 1}, {"nose"}, {NAN}, {2.0f}, {0.5f}}
             .Validate()
             .ok(),
        "Keypoint2DSet rejects non-finite coordinates");

  Keypoint3DSet keypoints_3d{{"person-0"}, {"d0"}, {"track-7"}, {0, 2},
                            {"left_hand", "right_hand"}, {1.0f, 2.0f}, {3.0f, 4.0f},
                            {5.0f, 6.0f}, {0.95f, 0.85f}};
  CheckRoundTrip(keypoints_3d, "Keypoint3DSet");
  auto keypoints_3d_batch = keypoints_3d.ToRecordBatch();
  Check(keypoints_3d_batch.ok(), "Keypoint3DSet schema batch");
  if (keypoints_3d_batch.ok()) {
    CheckFieldOrder(**keypoints_3d_batch,
                    {"instance_id", "detection_id", "track_id", "keypoint_offset",
                     "keypoint_id", "x", "y", "z", "score"},
                    "Keypoint3DSet");
  }
  Check(!Keypoint3DSet{{"a"}, {""}, {""}, {0, 1}, {"nose"}, {1.0f}, {2.0f}, {3.0f},
                       {-0.1f}}
             .Validate()
             .ok(),
        "Keypoint3DSet rejects score outside [0, 1]");

  CheckRoundTrip(Detection2DSet{{"d0", "d1"}, {"track-7", ""}, {10.5f, 20.0f},
                                {11.0f, 21.0f}, {4.0f, 8.0f}, {5.0f, 9.0f},
                                {0.0f, 0.25f}, {0, 2, 3}, {"person", "worker", "cup"},
                                {0.9f, 0.1f, 0.8f}},
                 "Detection2DSet");
  CheckRoundTrip(Detection2DSet::Empty(), "Detection2DSet empty");

  CheckRoundTrip(Detection3DSet{{"d0"}, {""}, {1.0f}, {2.0f}, {3.0f}, {0.0f}, {0.0f},
                                {0.0f}, {1.0f}, {0.5f}, {0.6f}, {0.7f}, {0, 1},
                                {"box"}, {0.95f}},
                 "Detection3DSet");
  SegmentationMaskSet masks{{"m0"}, {"d0"}, {""}, {4}, {5}, {2}, {2},
                            "mono8", {Bytes{0, 255, 255, 0}}, {0.98f}};
  CheckRoundTrip(masks, "SegmentationMaskSet");
  auto masks_batch = masks.ToRecordBatch();
  Check(masks_batch.ok(), "SegmentationMaskSet schema batch");
  if (masks_batch.ok()) {
    CheckFieldOrder(**masks_batch,
                    {"mask_id", "detection_id", "track_id", "x_offset", "y_offset", "width",
                     "height", "encoding", "data", "score"},
                    "SegmentationMaskSet");

    std::vector<std::shared_ptr<arrow::Field>> legacy_fields;
    std::vector<std::shared_ptr<arrow::Array>> legacy_columns;
    for (int i = 0; i < (*masks_batch)->num_columns() - 1; ++i) {
      legacy_fields.push_back((*masks_batch)->schema()->field(i));
      legacy_columns.push_back((*masks_batch)->column(i));
    }
    auto legacy_batch = arrow::RecordBatch::Make(arrow::schema(legacy_fields), 1, legacy_columns);
    auto legacy_masks = SegmentationMaskSet::FromRecordBatch(*legacy_batch);
    Check(legacy_masks.ok() && legacy_masks->score.empty(),
          "SegmentationMaskSet reads legacy batch without score");

  }
  auto masks_without_score = SegmentationMaskSet{{"m0"}, {}, {}, {}, {}, {1}, {1},
                                                  "mono8", {Bytes{255}}, {}}
                                 .ToRecordBatch();
  Check(masks_without_score.ok(), "SegmentationMaskSet allows empty score");
  if (masks_without_score.ok()) {
    Check((*masks_without_score)->GetColumnByName("score") != nullptr,
          "SegmentationMaskSet always emits score");
  }
  Check(!SegmentationMaskSet{{"m0"}, {""}, {""}, {0}, {0}, {1}, {1}, "mono8",
                             {Bytes{255}}, {NAN}}
             .Validate()
             .ok(),
        "SegmentationMaskSet rejects non-finite score");
  Check(!SegmentationMaskSet{{"m0"}, {""}, {""}, {0}, {0}, {1}, {1}, "mono8",
                             {Bytes{255}}, {0.5f, 0.6f}}
             .Validate()
             .ok(),
        "SegmentationMaskSet rejects score length mismatch");

  if (failures != 0) {
    std::cerr << failures << " failure(s)\n";
    return 1;
  }
  return 0;
}
