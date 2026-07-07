#include "forge_robot/forge_robot.hpp"

#include <arrow/api.h>
#include <arrow/c/bridge.h>

#include "dora-node-api.h"

namespace forge_robot {
namespace {

arrow::Result<std::shared_ptr<arrow::RecordBatch>> ArrayToRecordBatch(
    const std::shared_ptr<arrow::Array>& array) {
  if (array->type_id() != arrow::Type::STRUCT) {
    return arrow::Status::Invalid("expected Dora Arrow payload to be a StructArray");
  }

  auto struct_array = std::static_pointer_cast<arrow::StructArray>(array);
  auto struct_type = std::static_pointer_cast<arrow::StructType>(array->type());
  std::vector<std::shared_ptr<arrow::Array>> columns;
  columns.reserve(struct_type->num_fields());
  for (int i = 0; i < struct_type->num_fields(); ++i) {
    columns.push_back(struct_array->field(i));
  }
  return arrow::RecordBatch::Make(
      arrow::schema(struct_type->fields()),
      struct_array->length(),
      std::move(columns));
}

arrow::Result<std::shared_ptr<arrow::StructArray>> RecordBatchToStructArray(
    const arrow::RecordBatch& batch) {
  return arrow::StructArray::Make(batch.columns(), batch.schema()->fields());
}

arrow::Status SendState(
    DoraNode& dora_node,
    RobotDriver& driver,
    const RobotNodeOptions& options) {
  auto state = driver.GetState();
  ARROW_ASSIGN_OR_RAISE(auto batch, state.ToRecordBatch());
  if (!options.joint_order.empty()) {
    ARROW_ASSIGN_OR_RAISE(
        batch,
        ValidateRobotStateRecordBatch(
            *batch, options.joint_order, options.strict_extra_arrow_columns));
  }
  ARROW_ASSIGN_OR_RAISE(auto array, RecordBatchToStructArray(*batch));

  struct ArrowArray c_array = {};
  struct ArrowSchema c_schema = {};
  ARROW_RETURN_NOT_OK(arrow::ExportArray(*array, &c_array, &c_schema));

  auto result = send_arrow_output(
      dora_node.send_output,
      "state",
      reinterpret_cast<uint8_t*>(&c_array),
      reinterpret_cast<uint8_t*>(&c_schema));
  if (!result.error.empty()) {
    if (c_array.release != nullptr) {
      c_array.release(&c_array);
    }
    if (c_schema.release != nullptr) {
      c_schema.release(&c_schema);
    }
    return arrow::Status::IOError("failed to send Dora state output: ", std::string(result.error));
  }
  return arrow::Status::OK();
}

class DisconnectOnExit {
 public:
  explicit DisconnectOnExit(RobotDriver& driver) : driver_(driver) {}
  ~DisconnectOnExit() {
    try {
      driver_.Disconnect();
    } catch (...) {
    }
  }

 private:
  RobotDriver& driver_;
};

}  // namespace

int RunDoraRobotNode(RobotDriver& driver, const RobotNodeOptions& options) {
  auto logger = forge_common::GetLogger("forge_robot");
  driver.Connect();
  DisconnectOnExit disconnect(driver);

  auto dora_node = init_dora_node();

  for (;;) {
    auto event = dora_node.events->next();
    auto type = event_type(event);

    if (type == DoraEventType::AllInputsClosed || type == DoraEventType::Stop) {
      break;
    }
    if (type == DoraEventType::Error) {
      logger.Error("Dora node received an error event");
      break;
    }
    if (type != DoraEventType::Input) {
      continue;
    }

    struct ArrowArray c_array = {};
    struct ArrowSchema c_schema = {};
    auto info = event_as_arrow_input_with_info(
        std::move(event),
        reinterpret_cast<uint8_t*>(&c_array),
        reinterpret_cast<uint8_t*>(&c_schema));
    auto input_id = std::string(info.id);

    if (input_id == "tick") {
      auto status = SendState(dora_node, driver, options);
      if (!status.ok()) {
        logger.Error(status.ToString());
        return 1;
      }
      continue;
    }

    if (!info.error.empty()) {
      if (c_array.release != nullptr) {
        c_array.release(&c_array);
      }
      if (c_schema.release != nullptr) {
        c_schema.release(&c_schema);
      }
      logger.Error(
          "failed to read Dora Arrow input `" + input_id + "`: " + std::string(info.error));
      continue;
    }

    auto imported = arrow::ImportArray(&c_array, &c_schema);
    if (!imported.ok()) {
      logger.Error("failed to import Dora Arrow input `" + input_id + "`: " +
                   imported.status().ToString());
      continue;
    }
    auto batch = ArrayToRecordBatch(*imported);
    if (!batch.ok()) {
      logger.Error("failed to normalize Dora Arrow input `" + input_id + "`: " +
                   batch.status().ToString());
      continue;
    }

    HandleRobotInput(input_id, **batch, driver, options);
  }

  return 0;
}

}  // namespace forge_robot
