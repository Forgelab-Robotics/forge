#include <cmath>
#include <iostream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include "forge_msgs/forge_msgs.hpp"

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
  Check(batch.num_columns() == static_cast<int>(expected.size()),
        name + " field count");
  if (batch.num_columns() != static_cast<int>(expected.size())) return;
  for (int i = 0; i < batch.num_columns(); ++i) {
    Check(batch.schema()->field(i)->name() ==
              expected[static_cast<std::size_t>(i)],
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
  Check((*batch)->schema()->Equals(*arrow::schema(expected), false),
        name + " exact schema");
  Check((*batch)->GetColumnByName("goal_id") == nullptr,
        name + " excludes goal_id");
  Check((*batch)->GetColumnByName("goal_status") == nullptr,
        name + " excludes goal_status");
}

template <typename Message>
void CheckRejectsMalformedSchemas(const Message& message,
                                  const std::string& name) {
  auto batch_result = message.ToRecordBatch();
  Check(batch_result.ok(), name + " malformed schema source batch");
  if (!batch_result.ok()) return;

  const auto& batch = **batch_result;
  const auto fields = batch.schema()->fields();
  const auto columns = batch.columns();
  const auto check_rejected =
      [&](std::vector<std::shared_ptr<arrow::Field>> bad_fields,
          std::vector<std::shared_ptr<arrow::Array>> bad_columns,
          const std::string& reason) {
        auto malformed =
            arrow::RecordBatch::Make(arrow::schema(std::move(bad_fields)),
                                     batch.num_rows(), std::move(bad_columns));
        Check(!Message::FromRecordBatch(*malformed).ok(),
              name + " rejects " + reason);
      };

  auto extra_fields = fields;
  auto extra_columns = columns;
  extra_fields.push_back(arrow::field("goal_id", fields.front()->type(),
                                      fields.front()->nullable()));
  extra_columns.push_back(columns.front());
  check_rejected(std::move(extra_fields), std::move(extra_columns),
                 "extra goal_id field");

  auto nullable_fields = fields;
  nullable_fields.front() =
      arrow::field(fields.front()->name(), fields.front()->type(),
                   !fields.front()->nullable());
  check_rejected(std::move(nullable_fields), columns,
                 "wrong field nullability");

  auto reordered_fields = fields;
  auto reordered_columns = columns;
  std::swap(reordered_fields[0], reordered_fields[1]);
  std::swap(reordered_columns[0], reordered_columns[1]);
  check_rejected(std::move(reordered_fields), std::move(reordered_columns),
                 "wrong field order");

  arrow::Int32Builder builder;
  auto append_status = builder.Append(1);
  Check(append_status.ok(), name + " wrong-type test array append");
  auto wrong_type_array = builder.Finish();
  Check(wrong_type_array.ok(), name + " wrong-type test array finish");
  if (!append_status.ok() || !wrong_type_array.ok()) return;
  auto wrong_type_fields = fields;
  auto wrong_type_columns = columns;
  wrong_type_fields.front() = arrow::field(
      fields.front()->name(), arrow::int32(), fields.front()->nullable());
  wrong_type_columns.front() = *wrong_type_array;
  check_rejected(std::move(wrong_type_fields), std::move(wrong_type_columns),
                 "wrong field type");
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

  CheckRoundTrip(
      Image{2, 2, "rgb8", 6, Bytes{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}},
      "Image");
  CheckRoundTrip(CompressedImage{"jpeg", Bytes{0xff, 0xd8, 0xff, 0xd9}},
                 "CompressedImage");

  CheckRoundTrip(PointCloud{2,
                            1,
                            true,
                            {1.0f, 2.0f},
                            {3.0f, 4.0f},
                            {5.0f, 6.0f},
                            {},
                            {255, 0},
                            {0, 255},
                            {0, 0}},
                 "PointCloud");
  Check(!PointCloud{1, 1, true, {NAN}, {0.0f}, {0.0f}, {}, {}, {}, {}}
             .Validate()
             .ok(),
        "PointCloud rejects dense NaN");

  CheckRoundTrip(JointState{{"j1", "j2"}, {1.0, 2.0}, {0.1, 0.2}, {}},
                 "JointState");
  CheckRoundTrip(
      JointCommand{{"j1"}, "hybrid", {1.0}, {0.0}, {0.5}, {20.0}, {1.0}},
      "JointCommand");
  Check(!JointCommand{{"j1"}, "bad", {}, {}, {}, {}, {}}.Validate().ok(),
        "JointCommand rejects invalid mode");

  CheckRoundTrip(LocomotionCommand{0.5, 0.1, 0.2}, "LocomotionCommand");
  Check(!LocomotionCommand{NAN, 0.0, 0.0}.Validate().ok(),
        "LocomotionCommand rejects NaN");

  CheckRoundTrip(PolicyCommand{"default", "start_recording", "rec-001",
                               "{\"path\":\"x\"}"},
                 "PolicyCommand");
  CheckRoundTrip(PolicyCommandStatus{"default", "start_recording", "rec-001",
                                     PolicyCommandStatusValue::Done, "done",
                                     "{\"ok\":true}"},
                 "PolicyCommandStatus");
  Check(!PolicyCommand{"default", "Start", "", "{}"}.Validate().ok(),
        "PolicyCommand rejects non snake_case");

  ToolMessage tool_request;
  tool_request.message_type = "tool.invoke.request";
  tool_request.request_id = "request-1";
  tool_request.invocation_id = "invocation-1";
  tool_request.attempt_id = "attempt-1";
  tool_request.endpoint_id = "vision.yolo";
  tool_request.endpoint_instance_id = "endpoint-instance-1";
  tool_request.operation = "detect";
  tool_request.payload_json = "{\"arguments\":{\"class\":\"方块\"}}";
  CheckRoundTrip(tool_request, "ToolMessage request");
  auto tool_request_batch = tool_request.ToRecordBatch();
  Check(tool_request_batch.ok(), "ToolMessage request batch");
  if (tool_request_batch.ok()) {
    Check((*tool_request_batch)->num_rows() == 1,
          "ToolMessage emits exactly one row");
    Check((*tool_request_batch)->num_columns() == 10,
          "ToolMessage emits exactly ten columns");
    auto round_trip = ToolMessage::FromRecordBatch(**tool_request_batch);
    Check(round_trip.ok(), "ToolMessage request round trip");
    if (round_trip.ok()) {
      Check(round_trip->protocol == tool_request.protocol,
            "ToolMessage preserves protocol");
      Check(round_trip->message_type == tool_request.message_type,
            "ToolMessage preserves message_type");
      Check(round_trip->request_id == tool_request.request_id,
            "ToolMessage preserves request_id");
      Check(round_trip->invocation_id == tool_request.invocation_id,
            "ToolMessage preserves invocation_id");
      Check(round_trip->attempt_id == tool_request.attempt_id,
            "ToolMessage preserves attempt_id");
      Check(round_trip->endpoint_id == tool_request.endpoint_id,
            "ToolMessage preserves endpoint_id");
      Check(
          round_trip->endpoint_instance_id == tool_request.endpoint_instance_id,
          "ToolMessage preserves endpoint_instance_id");
      Check(round_trip->operation == tool_request.operation,
            "ToolMessage preserves operation");
      Check(round_trip->sequence == tool_request.sequence,
            "ToolMessage preserves sequence");
      Check(round_trip->payload_json == tool_request.payload_json,
            "ToolMessage preserves payload_json");
    }
    Check((*tool_request_batch)->GetColumnByName("sequence")->IsNull(0),
          "ToolMessage emits null optional sequence");
  }

  ToolMessage tool_event = tool_request;
  tool_event.message_type = "tool.event";
  tool_event.request_id = std::nullopt;
  tool_event.sequence = 9007199254740991LL;
  CheckRoundTrip(tool_event, "ToolMessage event");

  for (const auto& message_type :
       {"tool.invoke.request", "tool.invoke.response", "tool.status.request",
        "tool.status.response", "tool.result.request", "tool.result.response",
        "tool.control.request", "tool.control.response", "tool.error"}) {
    ToolMessage execution_message = tool_request;
    execution_message.message_type = message_type;
    Check(execution_message.Validate().ok(),
          std::string("ToolMessage accepts execution type ") + message_type);
  }

  ToolMessage management_message;
  management_message.message_type = "endpoint.heartbeat";
  management_message.request_id = "management-request-1";
  management_message.endpoint_id = "vision.yolo";
  management_message.endpoint_instance_id = "endpoint-instance-1";
  CheckRoundTrip(management_message, "ToolMessage management");
  for (const auto& message_type :
       {"endpoint.register", "endpoint.unregister", "endpoint.heartbeat",
        "endpoint.registry.response"}) {
    ToolMessage typed_management_message = management_message;
    typed_management_message.message_type = message_type;
    Check(typed_management_message.Validate().ok(),
          std::string("ToolMessage accepts management type ") + message_type);
  }
  ToolMessage endpoint_status = management_message;
  endpoint_status.message_type = "endpoint.status";
  endpoint_status.request_id = std::nullopt;
  CheckRoundTrip(endpoint_status, "ToolMessage unsolicited endpoint status");
  auto management_batch = management_message.ToRecordBatch();
  Check(management_batch.ok(), "ToolMessage management batch");
  if (management_batch.ok()) {
    Check(!(*management_batch)->GetColumnByName("request_id")->IsNull(0),
          "ToolMessage management exchange emits request_id");
    for (const auto& field : {"invocation_id", "attempt_id", "operation",
                              "sequence"}) {
      Check((*management_batch)->GetColumnByName(field)->IsNull(0),
            std::string("ToolMessage management emits null ") + field);
    }
  }

  ToolMessage bad_tool_message = tool_request;
  bad_tool_message.protocol = "forge.tool.endpoint/v2";
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage rejects unsupported protocol");
  bad_tool_message = tool_request;
  bad_tool_message.message_type = "tool.unknown";
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage rejects unsupported message type");
  bad_tool_message = tool_request;
  bad_tool_message.request_id = std::nullopt;
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage execution requires request_id");
  bad_tool_message = tool_request;
  bad_tool_message.operation = std::nullopt;
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage execution requires operation");
  bad_tool_message = management_message;
  bad_tool_message.invocation_id = "invocation-1";
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage management rejects execution correlation");
  for (const auto& message_type :
       {"endpoint.register", "endpoint.unregister", "endpoint.heartbeat",
        "endpoint.registry.response"}) {
    bad_tool_message = management_message;
    bad_tool_message.message_type = message_type;
    bad_tool_message.request_id = std::nullopt;
    Check(!bad_tool_message.Validate().ok(),
          std::string("ToolMessage management exchange requires request_id: ") +
              message_type);
  }
  bad_tool_message = management_message;
  bad_tool_message.message_type = "endpoint.status";
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage endpoint status rejects request_id");
  bad_tool_message.request_id = std::nullopt;
  Check(bad_tool_message.Validate().ok(),
        "ToolMessage endpoint status requires null request_id");
  bad_tool_message = tool_event;
  bad_tool_message.request_id = "request-1";
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage event rejects request_id");
  bad_tool_message = tool_event;
  bad_tool_message.sequence = std::nullopt;
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage event requires sequence");
  bad_tool_message = tool_event;
  bad_tool_message.sequence = -1;
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage rejects negative event sequence");
  bad_tool_message = tool_event;
  bad_tool_message.sequence = 9007199254740992LL;
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage rejects event sequence above JSON-safe range");
  bad_tool_message = tool_request;
  bad_tool_message.sequence = 0;
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage non-event rejects sequence");
  bad_tool_message = tool_request;
  bad_tool_message.request_id = " \t";
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage rejects blank optional strings");
  bad_tool_message = tool_request;
  bad_tool_message.endpoint_id = std::string("\xC2\xA0", 2);
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage rejects Unicode-whitespace-only identifiers");
  bad_tool_message = tool_request;
  bad_tool_message.endpoint_id = std::string("\xC3", 1);
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage rejects invalid UTF-8 identifiers");
  bad_tool_message = tool_request;
  bad_tool_message.payload_json = " [] ";
  Check(!bad_tool_message.Validate().ok(),
        "ToolMessage payload_json must have object shape");

  const auto check_tool_payload = [&](const std::string& payload_json,
                                      bool should_be_valid,
                                      const std::string& reason) {
    ToolMessage message = tool_request;
    message.payload_json = payload_json;
    Check(message.Validate().ok() == should_be_valid,
          std::string("ToolMessage payload_json ") +
              (should_be_valid ? "accepts " : "rejects ") + reason);
  };

  for (const auto& [payload_json, reason] :
       std::vector<std::pair<std::string, std::string>>{
           {"{}", "empty object"},
           {" \n\t{\"array\":[true,false,null,{\"nested\":[]}],\"decimal\":-12."
            "5e+2}\r ",
            "whitespace and nested JSON values"},
           {"{\"raw\":\"方块 😀\",\"escaped\":\"\\u65B9\\u5757 "
            "\\uD83D\\uDE00\"}",
            "raw UTF-8 and escaped Unicode"},
           {"{\"escaped\":\"\\\"\\\\\\/\\b\\f\\n\\r\\t\"}",
            "valid string escapes"},
           {"{\"minimum\":-9007199254740991,\"maximum\":9007199254740991,"
            "\"decimal\":1.7976931348623157e308,\"underflow\":1e-999}",
            "safe integers and finite decimal/exponent numbers"},
       }) {
    check_tool_payload(payload_json, true, reason);
  }

  std::string maximum_depth_payload = "{\"value\":";
  maximum_depth_payload.append(64, '[');
  maximum_depth_payload.append(64, ']');
  maximum_depth_payload.push_back('}');
  check_tool_payload(maximum_depth_payload, true, "nesting at depth 64");

  for (const auto& [payload_json, reason] :
       std::vector<std::pair<std::string, std::string>>{
           {"{\"value\":}", "missing value"},
           {"{not-json}", "unquoted object key"},
           {"[]", "array root"},
           {"null", "null root"},
           {"{\"duplicate\":1,\"duplicate\":2}", "duplicate object key"},
           {"{\"a\":1,\"\\u0061\":2}", "escape-equivalent duplicate key"},
           {"{\"value\":NaN}", "NaN"},
           {"{\"value\":Infinity}", "Infinity"},
           {"{\"value\":-Infinity}", "negative Infinity"},
           {"{\"value\":1e309}", "positive floating-point overflow"},
           {"{\"value\":-1e309}", "negative floating-point overflow"},
           {"{\"value\":9007199254740992}", "integer above safe range"},
           {"{\"value\":-9007199254740992}", "integer below safe range"},
           {"{\"value\":01}", "number with a leading zero"},
           {"{\"value\":1.}", "number with an incomplete fraction"},
           {"{\"value\":1e+}", "number with an incomplete exponent"},
           {"{\"value\":\"\\x\"}", "invalid string escape"},
           {"{\"value\":\"\\uD800\"}", "unpaired high surrogate"},
           {"{\"value\":\"\\uDC00\"}", "unpaired low surrogate"},
           {"{\"value\":\"\\uD800\\u0041\"}", "invalid surrogate pair"},
           {"{\"value\":\"line\nbreak\"}",
            "unescaped string control character"},
           {"{} trailing", "trailing data"},
       }) {
    check_tool_payload(payload_json, false, reason);
  }

  std::string too_deep_payload = "{\"value\":";
  too_deep_payload.append(65, '[');
  too_deep_payload.append(65, ']');
  too_deep_payload.push_back('}');
  check_tool_payload(too_deep_payload, false, "nesting deeper than 64");

  std::string invalid_utf8_payload = "{\"value\":\"";
  invalid_utf8_payload.push_back(static_cast<char>(0xC3));
  invalid_utf8_payload += "\"}";
  check_tool_payload(invalid_utf8_payload, false, "invalid UTF-8 string data");

  const std::vector<std::shared_ptr<arrow::Field>> tool_message_fields = {
      arrow::field("protocol", arrow::utf8(), false),
      arrow::field("message_type", arrow::utf8(), false),
      arrow::field("request_id", arrow::utf8(), true),
      arrow::field("invocation_id", arrow::utf8(), true),
      arrow::field("attempt_id", arrow::utf8(), true),
      arrow::field("endpoint_id", arrow::utf8(), false),
      arrow::field("endpoint_instance_id", arrow::utf8(), false),
      arrow::field("operation", arrow::utf8(), true),
      arrow::field("sequence", arrow::int64(), true),
      arrow::field("payload_json", arrow::utf8(), false)};
  CheckSchema(tool_request, tool_message_fields, "ToolMessage");
  CheckRejectsMalformedSchemas(tool_request, "ToolMessage");
  if (tool_request_batch.ok()) {
    std::vector<std::shared_ptr<arrow::Array>> empty_columns;
    for (const auto& column : (*tool_request_batch)->columns()) {
      empty_columns.push_back(column->Slice(0, 0));
    }
    auto empty_batch = arrow::RecordBatch::Make((*tool_request_batch)->schema(),
                                                0, std::move(empty_columns));
    Check(!ToolMessage::FromRecordBatch(*empty_batch).ok(),
          "ToolMessage rejects non-single-row batch");
  }

  auto pose = Pose::FromXyYaw(1.0, 2.0, 1.5707963267948966, 0.0);
  CheckRoundTrip(pose, "Pose");
  auto [x, y, yaw] = pose.XyYaw();
  Check(x == 1.0 && y == 2.0 && std::abs(yaw - 1.5707963267948966) < 1e-12,
        "Pose XyYaw helper");
  CheckRoundTrip(PoseSet{{"a", "b"},
                         {1.0, 2.0},
                         {2.0, 3.0},
                         {0.0, 0.0},
                         {0.0, 0.0},
                         {0.0, 0.0},
                         {0.0, 0.0},
                         {1.0, 1.0}},
                 "PoseSet");

  const auto f64_list =
      arrow::list(arrow::field("item", arrow::float64(), true));
  const auto string_list =
      arrow::list(arrow::field("item", arrow::utf8(), true));
  const std::vector<std::shared_ptr<arrow::Field>> point_fields = {
      arrow::field("positions", f64_list, false),
      arrow::field("velocities", f64_list, false),
      arrow::field("accelerations", f64_list, false),
      arrow::field("effort", f64_list, false),
      arrow::field("time_from_start_ns", arrow::int64(), false)};
  const auto point_type = arrow::struct_(point_fields);
  const std::vector<std::shared_ptr<arrow::Field>> trajectory_fields = {
      arrow::field("joint_names", string_list, false),
      arrow::field("points",
                   arrow::list(arrow::field("item", point_type, true)), false)};
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
  FollowJointTrajectoryFeedback follow_feedback{
      7,
      1,
      1000000,
      2000000,
      point1,
      point1,
      {{0.01, -0.01}, {}, {}, {}, 1000000}};
  FollowJointTrajectoryResult follow_result{
      FollowJointTrajectoryErrorCode::Success,
      "done",
      2000000,
      {"joint_1", "joint_2"},
      {0.01, -0.01},
      {}};
  GripperCommandGoal gripper_goal{0.08, std::nullopt, 12.0};
  GripperCommandFeedback gripper_feedback{1000000, 0.04,  std::nullopt,
                                          -0.25,   false, false};
  GripperCommandResult gripper_result{
      GripperCommandErrorCode::NoFreshRobotState,
      "state unavailable",
      0,
      std::nullopt,
      std::nullopt,
      std::nullopt,
      false,
      false};
  MoveJointsGoal move_joints_goal{
      "arm", {"joint_1", "joint_2"}, {1.0, 1.5}, 0.5, 0.4, std::nullopt};
  MoveJointsFeedback move_joints_feedback{MotionPhase::Executing,
                                          0.5,
                                          1000000,
                                          2000000,
                                          {"joint_1", "joint_2"},
                                          {0.5, 0.75},
                                          {1.0, 1.5},
                                          {0.5, 0.75},
                                          "moving"};
  MoveJointsResult move_joints_result{
      MotionErrorCode::Success, "done",     2000000,
      {"joint_1", "joint_2"},   {1.0, 1.5}, {0.0, 0.0}};
  MovePoseGoal move_pose_goal{
      "arm",       "world", "tool0",      Pose::Identity(0.4, 0.2, 0.3),
      0.5,         0.4,     std::nullopt, 0.01,
      std::nullopt};
  MovePoseFeedback move_pose_feedback{
      MotionPhase::Executing, 0.5,          1000000,      std::nullopt,
      std::nullopt,           std::nullopt, std::nullopt, "planning"};
  MovePoseResult move_pose_result{
      MotionErrorCode::Success,      "done",    2000000,
      Pose::Identity(0.4, 0.2, 0.3), 0.001,     0.002,
      {"joint_1", "joint_2"},        {1.0, 1.5}};

  CheckRoundTrip(point0, "JointTrajectoryPoint");
  CheckRoundTrip(trajectory, "JointTrajectory");
  CheckRoundTrip(tolerance, "JointTolerance");
  CheckRoundTrip(follow_goal, "FollowJointTrajectoryGoal");
  CheckRoundTrip(follow_feedback, "FollowJointTrajectoryFeedback");
  CheckRoundTrip(follow_result, "FollowJointTrajectoryResult");
  CheckRoundTrip(gripper_goal, "GripperCommandGoal");
  CheckRoundTrip(gripper_feedback, "GripperCommandFeedback");
  CheckRoundTrip(gripper_result, "GripperCommandResult");
  CheckRoundTrip(move_joints_goal, "MoveJointsGoal");
  CheckRoundTrip(move_joints_feedback, "MoveJointsFeedback");
  CheckRoundTrip(move_joints_result, "MoveJointsResult");
  CheckRoundTrip(move_pose_goal, "MovePoseGoal");
  CheckRoundTrip(move_pose_feedback, "MovePoseFeedback nullable pose");
  CheckRoundTrip(move_pose_result, "MovePoseResult");

  CheckSchema(point0, point_fields, "JointTrajectoryPoint");
  CheckSchema(trajectory, trajectory_fields, "JointTrajectory");
  CheckSchema(tolerance, tolerance_fields, "JointTolerance");
  CheckSchema(
      follow_goal,
      {arrow::field("trajectory", trajectory_type, false),
       arrow::field("path_tolerance",
                    arrow::list(arrow::field("item", tolerance_type, true)),
                    false),
       arrow::field("goal_tolerance",
                    arrow::list(arrow::field("item", tolerance_type, true)),
                    false),
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
  CheckSchema(gripper_goal,
              {arrow::field("position", arrow::float64(), false),
               arrow::field("max_velocity", arrow::float64(), true),
               arrow::field("max_effort", arrow::float64(), true)},
              "GripperCommandGoal");
  CheckSchema(gripper_feedback,
              {arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("position", arrow::float64(), false),
               arrow::field("velocity", arrow::float64(), true),
               arrow::field("effort", arrow::float64(), true),
               arrow::field("stalled", arrow::boolean(), false),
               arrow::field("reached_goal", arrow::boolean(), false)},
              "GripperCommandFeedback");
  CheckSchema(gripper_result,
              {arrow::field("error_code", arrow::utf8(), false),
               arrow::field("message", arrow::utf8(), false),
               arrow::field("elapsed_ns", arrow::int64(), false),
               arrow::field("position", arrow::float64(), true),
               arrow::field("velocity", arrow::float64(), true),
               arrow::field("effort", arrow::float64(), true),
               arrow::field("stalled", arrow::boolean(), false),
               arrow::field("reached_goal", arrow::boolean(), false)},
              "GripperCommandResult");
  CheckRejectsMalformedSchemas(gripper_goal, "GripperCommandGoal");
  CheckRejectsMalformedSchemas(gripper_feedback, "GripperCommandFeedback");
  CheckRejectsMalformedSchemas(gripper_result, "GripperCommandResult");
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
  CheckSchema(
      move_pose_goal,
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
  CheckSchema(
      move_pose_result,
      {arrow::field("error_code", arrow::utf8(), false),
       arrow::field("message", arrow::utf8(), false),
       arrow::field("elapsed_ns", arrow::int64(), false),
       arrow::field("final_pose", pose_type, true),
       arrow::field("final_position_error_m", arrow::float64(), true),
       arrow::field("final_orientation_error_rad", arrow::float64(), true),
       arrow::field("joint_names", string_list, false),
       arrow::field("final_joint_positions", f64_list, false)},
      "MovePoseResult");

  Check(ToString(FollowJointTrajectoryErrorCode::FeedbackStale) ==
            "FEEDBACK_STALE",
        "FollowJointTrajectoryErrorCode string value");
  Check(FollowJointTrajectoryErrorCodeFromString("HARDWARE_FAULT").ok(),
        "FollowJointTrajectoryErrorCode parses schema value");
  Check(ToString(MotionPhase::WaitingForController) == "WAITING_FOR_CONTROLLER",
        "MotionPhase string value");
  Check(MotionPhaseFromString("bad").status().IsInvalid(),
        "MotionPhase rejects invalid value");
  Check(ToString(MotionErrorCode::IkTimedOut) == "IK_TIMED_OUT",
        "MotionErrorCode string value");
  Check(MotionErrorCodeFromString("FINAL_POSE_TOLERANCE_VIOLATED").ok(),
        "MotionErrorCode parses schema value");
  Check(ToString(GripperCommandErrorCode::UnsupportedVelocity) ==
            "UNSUPPORTED_VELOCITY",
        "GripperCommandErrorCode string value");
  Check(GripperCommandErrorCodeFromString("POSITION_LIMIT_VIOLATION").ok(),
        "GripperCommandErrorCode parses schema value");
  Check(GripperCommandErrorCodeFromString("bad").status().IsInvalid(),
        "GripperCommandErrorCode rejects invalid value");

  Check(!JointTrajectory{{"joint_1"}, {point0, point0}}.Validate().ok(),
        "JointTrajectory rejects non-increasing time");
  Check(!JointTolerance{"joint_1", std::nullopt, std::nullopt, std::nullopt}
             .Validate()
             .ok(),
        "JointTolerance requires one tolerance");
  Check(!GripperCommandGoal{NAN, std::nullopt, std::nullopt}.Validate().ok(),
        "GripperCommandGoal rejects non-finite position");
  Check(!GripperCommandGoal{0.0, -0.1, std::nullopt}.Validate().ok(),
        "GripperCommandGoal rejects negative max velocity");
  Check(
      !GripperCommandFeedback{-1, 0.0, std::nullopt, std::nullopt, false, false}
           .Validate()
           .ok(),
      "GripperCommandFeedback rejects negative elapsed time");
  const auto gripper_result_flags_valid = [](GripperCommandErrorCode error_code,
                                             bool stalled, bool reached_goal) {
    return GripperCommandResult{error_code,   "",           0,
                                std::nullopt, std::nullopt, std::nullopt,
                                stalled,      reached_goal}
        .Validate()
        .ok();
  };
  Check(!gripper_result_flags_valid(GripperCommandErrorCode::Success, false,
                                    false),
        "GripperCommandResult SUCCESS requires a terminal flag");
  Check(
      !gripper_result_flags_valid(GripperCommandErrorCode::Success, true, true),
      "GripperCommandResult SUCCESS rejects both terminal flags");
  Check(!gripper_result_flags_valid(GripperCommandErrorCode::Stalled, false,
                                    false),
        "GripperCommandResult STALLED requires stalled");
  Check(!gripper_result_flags_valid(GripperCommandErrorCode::Stalled, false,
                                    true),
        "GripperCommandResult STALLED rejects reached_goal only");
  Check(
      !gripper_result_flags_valid(GripperCommandErrorCode::Stalled, true, true),
      "GripperCommandResult STALLED rejects both terminal flags");
  Check(!gripper_result_flags_valid(GripperCommandErrorCode::InternalError,
                                    true, true),
        "GripperCommandResult always rejects both terminal flags");
  Check(
      gripper_result_flags_valid(GripperCommandErrorCode::Success, true, false),
      "GripperCommandResult SUCCESS allows stalled only");
  Check(
      gripper_result_flags_valid(GripperCommandErrorCode::Success, false, true),
      "GripperCommandResult SUCCESS allows reached_goal only");
  Check(
      gripper_result_flags_valid(GripperCommandErrorCode::Stalled, true, false),
      "GripperCommandResult STALLED requires stalled only");
  Check(gripper_result_flags_valid(GripperCommandErrorCode::InternalError,
                                   false, false),
        "GripperCommandResult non-SUCCESS allows neither terminal flag");
  Check(gripper_result_flags_valid(GripperCommandErrorCode::InternalError, true,
                                   false),
        "GripperCommandResult non-SUCCESS allows stalled only");
  Check(gripper_result_flags_valid(GripperCommandErrorCode::InternalError,
                                   false, true),
        "GripperCommandResult non-SUCCESS allows reached_goal only");
  Check(!MoveJointsGoal{"arm", {"joint_1"}, {NAN}, 0.5, 0.5, std::nullopt}
             .Validate()
             .ok(),
        "MoveJointsGoal rejects non-finite position");
  Check(!MovePoseGoal{"arm", "world", "tool0", Pose{}, 0.0, 0.5, std::nullopt,
                      std::nullopt, std::nullopt}
             .Validate()
             .ok(),
        "MovePoseGoal rejects zero scale");
  auto nullable_gripper_batch = gripper_result.ToRecordBatch();
  Check(nullable_gripper_batch.ok() &&
            (*nullable_gripper_batch)->GetColumnByName("position")->IsNull(0),
        "GripperCommandResult emits null optional state");
  auto nullable_feedback_batch = move_pose_feedback.ToRecordBatch();
  Check(
      nullable_feedback_batch.ok() &&
          (*nullable_feedback_batch)->GetColumnByName("actual_pose")->IsNull(0),
      "MovePoseFeedback emits null optional pose");

  CheckRoundTrip(Classification{{"person", "vehicle"}, {0.9f, 0.1f}},
                 "Classification");
  Check(!Classification{{"person", "person"}, {0.9f, 0.1f}}.Validate().ok(),
        "Classification rejects duplicate class_id");
  Check(!Classification{{"person"}, {NAN}}.Validate().ok(),
        "Classification rejects non-finite score");
  Check(!Classification{{"person"}, {1.1f}}.Validate().ok(),
        "Classification rejects score outside [0, 1]");

  Keypoint2DSet keypoints_2d{{"person-0", "person-1"},
                             {},
                             {},
                             {0, 2, 3},
                             {"left_eye", "right_eye", "left_eye"},
                             {10.0f, 12.0f, 30.0f},
                             {20.0f, 20.0f, 40.0f},
                             {0.9f, 0.8f, 0.7f}};
  CheckRoundTrip(keypoints_2d, "Keypoint2DSet");
  auto keypoints_2d_batch = keypoints_2d.ToRecordBatch();
  Check(keypoints_2d_batch.ok(), "Keypoint2DSet schema batch");
  if (keypoints_2d_batch.ok()) {
    CheckFieldOrder(**keypoints_2d_batch,
                    {"instance_id", "detection_id", "track_id",
                     "keypoint_offset", "keypoint_id", "x", "y", "score"},
                    "Keypoint2DSet");
  }
  CheckRoundTrip(Keypoint2DSet{}, "Keypoint2DSet empty defaults");
  Check(
      !Keypoint2DSet{{"a", "a"}, {"", ""}, {"", ""}, {0, 0, 0}, {}, {}, {}, {}}
           .Validate()
           .ok(),
      "Keypoint2DSet rejects duplicate instance_id");
  Check(!Keypoint2DSet{{"a"},
                       {""},
                       {""},
                       {0, 2},
                       {"nose", "nose"},
                       {1.0f, 2.0f},
                       {3.0f, 4.0f},
                       {0.8f, 0.7f}}
             .Validate()
             .ok(),
        "Keypoint2DSet rejects duplicate keypoint_id within an instance");
  Check(Keypoint2DSet{{"a", "b"},
                      {"", ""},
                      {"", ""},
                      {0, 1, 2},
                      {"nose", "nose"},
                      {1.0f, 2.0f},
                      {3.0f, 4.0f},
                      {0.8f, 0.7f}}
            .Validate()
            .ok(),
        "Keypoint2DSet allows keypoint_id reuse across instances");
  Check(
      !Keypoint2DSet{{"a"}, {""}, {""}, {1, 1}, {}, {}, {}, {}}.Validate().ok(),
      "Keypoint2DSet rejects offset not starting at zero");
  Check(
      !Keypoint2DSet{{"a"}, {""}, {""}, {0, 1}, {"nose"}, {NAN}, {2.0f}, {0.5f}}
           .Validate()
           .ok(),
      "Keypoint2DSet rejects non-finite coordinates");

  Keypoint3DSet keypoints_3d{{"person-0"},
                             {"d0"},
                             {"track-7"},
                             {0, 2},
                             {"left_hand", "right_hand"},
                             {1.0f, 2.0f},
                             {3.0f, 4.0f},
                             {5.0f, 6.0f},
                             {0.95f, 0.85f}};
  CheckRoundTrip(keypoints_3d, "Keypoint3DSet");
  auto keypoints_3d_batch = keypoints_3d.ToRecordBatch();
  Check(keypoints_3d_batch.ok(), "Keypoint3DSet schema batch");
  if (keypoints_3d_batch.ok()) {
    CheckFieldOrder(**keypoints_3d_batch,
                    {"instance_id", "detection_id", "track_id",
                     "keypoint_offset", "keypoint_id", "x", "y", "z", "score"},
                    "Keypoint3DSet");
  }
  Check(
      !Keypoint3DSet{
          {"a"}, {""}, {""}, {0, 1}, {"nose"}, {1.0f}, {2.0f}, {3.0f}, {-0.1f}}
           .Validate()
           .ok(),
      "Keypoint3DSet rejects score outside [0, 1]");

  CheckRoundTrip(Detection2DSet{{"d0", "d1"},
                                {"track-7", ""},
                                {10.5f, 20.0f},
                                {11.0f, 21.0f},
                                {4.0f, 8.0f},
                                {5.0f, 9.0f},
                                {0.0f, 0.25f},
                                {0, 2, 3},
                                {"person", "worker", "cup"},
                                {0.9f, 0.1f, 0.8f}},
                 "Detection2DSet");
  CheckRoundTrip(Detection2DSet::Empty(), "Detection2DSet empty");

  CheckRoundTrip(Detection3DSet{{"d0"},
                                {""},
                                {1.0f},
                                {2.0f},
                                {3.0f},
                                {0.0f},
                                {0.0f},
                                {0.0f},
                                {1.0f},
                                {0.5f},
                                {0.6f},
                                {0.7f},
                                {0, 1},
                                {"box"},
                                {0.95f}},
                 "Detection3DSet");
  SegmentationMaskSet masks{{"m0"}, {"d0"},  {""},
                            {4},    {5},     {2},
                            {2},    "mono8", {Bytes{0, 255, 255, 0}},
                            {0.98f}};
  CheckRoundTrip(masks, "SegmentationMaskSet");
  auto masks_batch = masks.ToRecordBatch();
  Check(masks_batch.ok(), "SegmentationMaskSet schema batch");
  if (masks_batch.ok()) {
    CheckFieldOrder(
        **masks_batch,
        {"mask_id", "detection_id", "track_id", "x_offset", "y_offset", "width",
         "height", "encoding", "data", "score"},
        "SegmentationMaskSet");

    std::vector<std::shared_ptr<arrow::Field>> legacy_fields;
    std::vector<std::shared_ptr<arrow::Array>> legacy_columns;
    for (int i = 0; i < (*masks_batch)->num_columns() - 1; ++i) {
      legacy_fields.push_back((*masks_batch)->schema()->field(i));
      legacy_columns.push_back((*masks_batch)->column(i));
    }
    auto legacy_batch = arrow::RecordBatch::Make(arrow::schema(legacy_fields),
                                                 1, legacy_columns);
    auto legacy_masks = SegmentationMaskSet::FromRecordBatch(*legacy_batch);
    Check(legacy_masks.ok() && legacy_masks->score.empty(),
          "SegmentationMaskSet reads legacy batch without score");
  }
  auto masks_without_score =
      SegmentationMaskSet{{"m0"}, {},  {},      {},           {},
                          {1},    {1}, "mono8", {Bytes{255}}, {}}
          .ToRecordBatch();
  Check(masks_without_score.ok(), "SegmentationMaskSet allows empty score");
  if (masks_without_score.ok()) {
    Check((*masks_without_score)->GetColumnByName("score") != nullptr,
          "SegmentationMaskSet always emits score");
  }
  Check(
      !SegmentationMaskSet{
          {"m0"}, {""}, {""}, {0}, {0}, {1}, {1}, "mono8", {Bytes{255}}, {NAN}}
           .Validate()
           .ok(),
      "SegmentationMaskSet rejects non-finite score");
  Check(!SegmentationMaskSet{{"m0"},
                             {""},
                             {""},
                             {0},
                             {0},
                             {1},
                             {1},
                             "mono8",
                             {Bytes{255}},
                             {0.5f, 0.6f}}
             .Validate()
             .ok(),
        "SegmentationMaskSet rejects score length mismatch");

  if (failures != 0) {
    std::cerr << failures << " failure(s)\n";
    return 1;
  }
  return 0;
}
