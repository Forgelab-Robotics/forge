#include "detail.hpp"

namespace forge_msgs {

using namespace detail;

arrow::Status AudioChunk::Validate() const {
  if (sample_rate == 0) return arrow::Status::Invalid("sample_rate must be greater than 0");
  if (channels == 0) return arrow::Status::Invalid("channels must be greater than 0");
  auto bytes_per_sample = BytesPerSample(sample_format);
  if (bytes_per_sample == 0) {
    return arrow::Status::Invalid("unsupported audio sample format: ", sample_format);
  }
  auto expected = static_cast<std::size_t>(frame_count) * channels * bytes_per_sample;
  if (data.size() != expected) {
    return arrow::Status::Invalid("data length must equal frame_count * channels * bytes_per_sample");
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> AudioChunk::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto sample_rate_array, ScalarU32(sample_rate));
  ARROW_ASSIGN_OR_RAISE(auto channels_array, ScalarU32(channels));
  ARROW_ASSIGN_OR_RAISE(auto sample_format_array, ScalarString(sample_format));
  ARROW_ASSIGN_OR_RAISE(auto frame_count_array, ScalarU32(frame_count));
  ARROW_ASSIGN_OR_RAISE(auto data_array, ScalarBinary(data));
  return MakeBatch(
      {arrow::field("sample_rate", arrow::uint32(), false),
       arrow::field("channels", arrow::uint32(), false),
       arrow::field("sample_format", arrow::utf8(), false),
       arrow::field("frame_count", arrow::uint32(), false),
       arrow::field("data", arrow::large_binary(), false)},
      {sample_rate_array, channels_array, sample_format_array, frame_count_array, data_array});
}

arrow::Result<AudioChunk> AudioChunk::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  AudioChunk value;
  ARROW_ASSIGN_OR_RAISE(value.sample_rate, ReadU32(batch, "sample_rate"));
  ARROW_ASSIGN_OR_RAISE(value.channels, ReadU32(batch, "channels"));
  ARROW_ASSIGN_OR_RAISE(value.sample_format, ReadString(batch, "sample_format"));
  ARROW_ASSIGN_OR_RAISE(value.frame_count, ReadU32(batch, "frame_count"));
  ARROW_ASSIGN_OR_RAISE(value.data, ReadBinary(batch, "data"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
