#include "detail.hpp"

namespace forge_msgs {

using namespace detail;

arrow::Status Text::Validate() const { return arrow::Status::OK(); }

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Text::ToRecordBatch() const {
  ARROW_ASSIGN_OR_RAISE(auto text_array, ScalarString(text));
  return MakeBatch({arrow::field("text", arrow::utf8(), false)}, {text_array});
}

arrow::Result<Text> Text::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  ARROW_ASSIGN_OR_RAISE(auto text_value, ReadString(batch, "text"));
  return Text{text_value};
}

}  // namespace forge_msgs
