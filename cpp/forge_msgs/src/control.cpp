#include "detail.hpp"

namespace forge_msgs {

using namespace detail;

arrow::Status JointState::Validate() const {
  if (name.empty()) return arrow::Status::Invalid("name must contain at least one joint");
  ARROW_RETURN_NOT_OK(ValidateUnique("name", name));
  ARROW_RETURN_NOT_OK(ValidateLen("position", position, name.size(), true));
  ARROW_RETURN_NOT_OK(ValidateLen("velocity", velocity, name.size(), true));
  return ValidateLen("effort", effort, name.size(), true);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> JointState::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto name_array, StringList(name));
  ARROW_ASSIGN_OR_RAISE(auto position_array, F64List(position));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, F64List(velocity));
  ARROW_ASSIGN_OR_RAISE(auto effort_array, F64List(effort));
  auto f64_list = ListType(arrow::float64());
  return MakeBatch({arrow::field("name", ListType(arrow::utf8()), false),
                    arrow::field("position", f64_list, false),
                    arrow::field("velocity", f64_list, false),
                    arrow::field("effort", f64_list, false)},
                   {name_array, position_array, velocity_array, effort_array});
}

arrow::Result<JointState> JointState::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  JointState value;
  ARROW_ASSIGN_OR_RAISE(value.name, ReadStringList(batch, "name"));
  ARROW_ASSIGN_OR_RAISE(value.position, ReadF64List(batch, "position"));
  ARROW_ASSIGN_OR_RAISE(value.velocity, ReadF64List(batch, "velocity"));
  ARROW_ASSIGN_OR_RAISE(value.effort, ReadF64List(batch, "effort"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status JointCommand::Validate() const {
  if (name.empty()) return arrow::Status::Invalid("name must contain at least one joint");
  ARROW_RETURN_NOT_OK(ValidateUnique("name", name));
  if (!(mode == "position" || mode == "velocity" || mode == "effort" || mode == "hybrid")) {
    return arrow::Status::Invalid("mode must be one of position, velocity, effort, hybrid");
  }
  ARROW_RETURN_NOT_OK(ValidateLen("position", position, name.size(), true));
  ARROW_RETURN_NOT_OK(ValidateLen("velocity", velocity, name.size(), true));
  ARROW_RETURN_NOT_OK(ValidateLen("effort", effort, name.size(), true));
  ARROW_RETURN_NOT_OK(ValidateLen("kp", kp, name.size(), true));
  return ValidateLen("kd", kd, name.size(), true);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> JointCommand::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto name_array, StringList(name));
  ARROW_ASSIGN_OR_RAISE(auto mode_array, ScalarString(mode));
  ARROW_ASSIGN_OR_RAISE(auto position_array, F64List(position));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, F64List(velocity));
  ARROW_ASSIGN_OR_RAISE(auto effort_array, F64List(effort));
  ARROW_ASSIGN_OR_RAISE(auto kp_array, F64List(kp));
  ARROW_ASSIGN_OR_RAISE(auto kd_array, F64List(kd));
  auto f64_list = ListType(arrow::float64());
  return MakeBatch({arrow::field("name", ListType(arrow::utf8()), false),
                    arrow::field("mode", arrow::utf8(), false),
                    arrow::field("position", f64_list, false),
                    arrow::field("velocity", f64_list, false),
                    arrow::field("effort", f64_list, false),
                    arrow::field("kp", f64_list, false),
                    arrow::field("kd", f64_list, false)},
                   {name_array, mode_array, position_array, velocity_array, effort_array, kp_array, kd_array});
}

arrow::Result<JointCommand> JointCommand::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  JointCommand value;
  ARROW_ASSIGN_OR_RAISE(value.name, ReadStringList(batch, "name"));
  ARROW_ASSIGN_OR_RAISE(value.mode, ReadOptionalString(batch, "mode", "position"));
  ARROW_ASSIGN_OR_RAISE(value.position, ReadF64List(batch, "position"));
  ARROW_ASSIGN_OR_RAISE(value.velocity, ReadF64List(batch, "velocity"));
  ARROW_ASSIGN_OR_RAISE(value.effort, ReadF64List(batch, "effort"));
  ARROW_ASSIGN_OR_RAISE(value.kp, ReadF64List(batch, "kp"));
  ARROW_ASSIGN_OR_RAISE(value.kd, ReadF64List(batch, "kd"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status LocomotionCommand::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateFinite("vx", vx));
  ARROW_RETURN_NOT_OK(ValidateFinite("vy", vy));
  return ValidateFinite("wz", wz);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> LocomotionCommand::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto vx_array, ScalarF64(vx));
  ARROW_ASSIGN_OR_RAISE(auto vy_array, ScalarF64(vy));
  ARROW_ASSIGN_OR_RAISE(auto wz_array, ScalarF64(wz));
  return MakeBatch({arrow::field("vx", arrow::float64(), false),
                    arrow::field("vy", arrow::float64(), false),
                    arrow::field("wz", arrow::float64(), false)},
                   {vx_array, vy_array, wz_array});
}

arrow::Result<LocomotionCommand> LocomotionCommand::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  LocomotionCommand value;
  ARROW_ASSIGN_OR_RAISE(value.vx, ReadF64(batch, "vx"));
  ARROW_ASSIGN_OR_RAISE(value.vy, ReadF64(batch, "vy"));
  ARROW_ASSIGN_OR_RAISE(value.wz, ReadF64(batch, "wz"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

std::string ToString(PolicyCommandStatusValue value) {
  switch (value) {
    case PolicyCommandStatusValue::Accepted: return "accepted";
    case PolicyCommandStatusValue::Rejected: return "rejected";
    case PolicyCommandStatusValue::Running: return "running";
    case PolicyCommandStatusValue::Done: return "done";
    case PolicyCommandStatusValue::Error: return "error";
  }
  return "error";
}

arrow::Result<PolicyCommandStatusValue> PolicyCommandStatusValueFromString(const std::string& value) {
  if (value == "accepted") return PolicyCommandStatusValue::Accepted;
  if (value == "rejected") return PolicyCommandStatusValue::Rejected;
  if (value == "running") return PolicyCommandStatusValue::Running;
  if (value == "done") return PolicyCommandStatusValue::Done;
  if (value == "error") return PolicyCommandStatusValue::Error;
  return arrow::Status::Invalid("unsupported status: ", value);
}

arrow::Status PolicyCommand::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateRequired("policy_id", policy_id));
  ARROW_RETURN_NOT_OK(ValidateRequired("command", command));
  ARROW_RETURN_NOT_OK(ValidateSnakeCase(command));
  return ValidateJsonObject("inputs_json", inputs_json);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> PolicyCommand::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto policy_array, ScalarString(policy_id));
  ARROW_ASSIGN_OR_RAISE(auto command_array, ScalarString(command));
  ARROW_ASSIGN_OR_RAISE(auto request_array, ScalarString(request_id));
  ARROW_ASSIGN_OR_RAISE(auto inputs_array, ScalarString(inputs_json));
  return MakeBatch({arrow::field("policy_id", arrow::utf8(), false),
                    arrow::field("command", arrow::utf8(), false),
                    arrow::field("request_id", arrow::utf8(), false),
                    arrow::field("inputs_json", arrow::utf8(), false)},
                   {policy_array, command_array, request_array, inputs_array});
}

arrow::Result<PolicyCommand> PolicyCommand::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  PolicyCommand value;
  ARROW_ASSIGN_OR_RAISE(value.policy_id, ReadString(batch, "policy_id"));
  ARROW_ASSIGN_OR_RAISE(value.command, ReadString(batch, "command"));
  ARROW_ASSIGN_OR_RAISE(value.request_id, ReadString(batch, "request_id"));
  ARROW_ASSIGN_OR_RAISE(value.inputs_json, ReadString(batch, "inputs_json"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status PolicyCommandStatus::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateRequired("policy_id", policy_id));
  ARROW_RETURN_NOT_OK(ValidateRequired("command", command));
  ARROW_RETURN_NOT_OK(ValidateSnakeCase(command));
  return ValidateJsonObject("outputs_json", outputs_json);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> PolicyCommandStatus::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto policy_array, ScalarString(policy_id));
  ARROW_ASSIGN_OR_RAISE(auto command_array, ScalarString(command));
  ARROW_ASSIGN_OR_RAISE(auto request_array, ScalarString(request_id));
  ARROW_ASSIGN_OR_RAISE(auto status_array, ScalarString(ToString(status)));
  ARROW_ASSIGN_OR_RAISE(auto message_array, ScalarString(message));
  ARROW_ASSIGN_OR_RAISE(auto outputs_array, ScalarString(outputs_json));
  return MakeBatch({arrow::field("policy_id", arrow::utf8(), false),
                    arrow::field("command", arrow::utf8(), false),
                    arrow::field("request_id", arrow::utf8(), false),
                    arrow::field("status", arrow::utf8(), false),
                    arrow::field("message", arrow::utf8(), false),
                    arrow::field("outputs_json", arrow::utf8(), false)},
                   {policy_array, command_array, request_array, status_array, message_array, outputs_array});
}

arrow::Result<PolicyCommandStatus> PolicyCommandStatus::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  PolicyCommandStatus value;
  ARROW_ASSIGN_OR_RAISE(value.policy_id, ReadString(batch, "policy_id"));
  ARROW_ASSIGN_OR_RAISE(value.command, ReadString(batch, "command"));
  ARROW_ASSIGN_OR_RAISE(value.request_id, ReadString(batch, "request_id"));
  ARROW_ASSIGN_OR_RAISE(auto status_text, ReadString(batch, "status"));
  ARROW_ASSIGN_OR_RAISE(value.status, PolicyCommandStatusValueFromString(status_text));
  ARROW_ASSIGN_OR_RAISE(value.message, ReadString(batch, "message"));
  ARROW_ASSIGN_OR_RAISE(value.outputs_json, ReadString(batch, "outputs_json"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
