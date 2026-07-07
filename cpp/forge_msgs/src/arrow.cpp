#include "forge_msgs/forge_msgs.hpp"

#include <arrow/io/api.h>
#include <arrow/ipc/api.h>

namespace forge_msgs {

arrow::Status WriteIpcStream(const arrow::RecordBatch& batch, const std::string& path) {
  ARROW_ASSIGN_OR_RAISE(auto output, arrow::io::FileOutputStream::Open(path));
  ARROW_ASSIGN_OR_RAISE(auto writer, arrow::ipc::MakeStreamWriter(output.get(), batch.schema()));
  ARROW_RETURN_NOT_OK(writer->WriteRecordBatch(batch));
  ARROW_RETURN_NOT_OK(writer->Close());
  return output->Close();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> ReadIpcStream(const std::string& path) {
  ARROW_ASSIGN_OR_RAISE(auto input, arrow::io::ReadableFile::Open(path));
  ARROW_ASSIGN_OR_RAISE(auto reader, arrow::ipc::RecordBatchStreamReader::Open(input));
  std::shared_ptr<arrow::RecordBatch> batch;
  ARROW_RETURN_NOT_OK(reader->ReadNext(&batch));
  if (!batch) {
    return arrow::Status::Invalid("IPC stream did not contain a RecordBatch");
  }
  return batch;
}

}  // namespace forge_msgs
