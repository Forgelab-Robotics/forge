#pragma once

#include <arrow/api.h>
#include <arrow/result.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "forge_msgs/forge_msgs.hpp"

namespace forge_msgs::detail {

inline arrow::Status RequireOneRow(const arrow::RecordBatch& batch) {
  if (batch.num_rows() != 1) {
    return arrow::Status::Invalid("RecordBatch must contain one row");
  }
  return arrow::Status::OK();
}

inline std::shared_ptr<arrow::DataType> ListType(
    std::shared_ptr<arrow::DataType> value_type) {
  return arrow::list(arrow::field("item", std::move(value_type), true));
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ScalarString(
    const std::string& value) {
  arrow::StringBuilder builder;
  ARROW_RETURN_NOT_OK(builder.Append(value));
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> OptionalString(
    const std::optional<std::string>& value) {
  arrow::StringBuilder builder;
  if (value) {
    ARROW_RETURN_NOT_OK(builder.Append(*value));
  } else {
    ARROW_RETURN_NOT_OK(builder.AppendNull());
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ScalarU32(
    std::uint32_t value) {
  arrow::UInt32Builder builder;
  ARROW_RETURN_NOT_OK(builder.Append(value));
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ScalarU64(
    std::uint64_t value) {
  arrow::UInt64Builder builder;
  ARROW_RETURN_NOT_OK(builder.Append(value));
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ScalarI64(
    std::int64_t value) {
  arrow::Int64Builder builder;
  ARROW_RETURN_NOT_OK(builder.Append(value));
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> OptionalI64(
    const std::optional<std::int64_t>& value) {
  arrow::Int64Builder builder;
  if (value) {
    ARROW_RETURN_NOT_OK(builder.Append(*value));
  } else {
    ARROW_RETURN_NOT_OK(builder.AppendNull());
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ScalarF64(double value) {
  arrow::DoubleBuilder builder;
  ARROW_RETURN_NOT_OK(builder.Append(value));
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> OptionalF64(
    const std::optional<double>& value) {
  arrow::DoubleBuilder builder;
  if (value) {
    ARROW_RETURN_NOT_OK(builder.Append(*value));
  } else {
    ARROW_RETURN_NOT_OK(builder.AppendNull());
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ScalarBool(bool value) {
  arrow::BooleanBuilder builder;
  ARROW_RETURN_NOT_OK(builder.Append(value));
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ScalarBinary(
    const Bytes& value) {
  arrow::LargeBinaryBuilder builder;
  ARROW_RETURN_NOT_OK(
      builder.Append(value.data(), static_cast<std::int64_t>(value.size())));
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> StringList(
    const std::vector<std::string>& values) {
  auto value_builder = std::make_shared<arrow::StringBuilder>();
  arrow::ListBuilder builder(arrow::default_memory_pool(), value_builder);
  ARROW_RETURN_NOT_OK(builder.Append());
  auto* inner = static_cast<arrow::StringBuilder*>(builder.value_builder());
  for (const auto& value : values) {
    ARROW_RETURN_NOT_OK(inner->Append(value));
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> F64List(
    const std::vector<double>& values) {
  auto value_builder = std::make_shared<arrow::DoubleBuilder>();
  arrow::ListBuilder builder(arrow::default_memory_pool(), value_builder);
  ARROW_RETURN_NOT_OK(builder.Append());
  auto* inner = static_cast<arrow::DoubleBuilder*>(builder.value_builder());
  for (double value : values) {
    ARROW_RETURN_NOT_OK(inner->Append(value));
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> F32List(
    const std::vector<float>& values) {
  auto value_builder = std::make_shared<arrow::FloatBuilder>();
  arrow::ListBuilder builder(arrow::default_memory_pool(), value_builder);
  ARROW_RETURN_NOT_OK(builder.Append());
  auto* inner = static_cast<arrow::FloatBuilder*>(builder.value_builder());
  for (float value : values) {
    ARROW_RETURN_NOT_OK(inner->Append(value));
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> U32List(
    const std::vector<std::uint32_t>& values) {
  auto value_builder = std::make_shared<arrow::UInt32Builder>();
  arrow::ListBuilder builder(arrow::default_memory_pool(), value_builder);
  ARROW_RETURN_NOT_OK(builder.Append());
  auto* inner = static_cast<arrow::UInt32Builder*>(builder.value_builder());
  for (std::uint32_t value : values) {
    ARROW_RETURN_NOT_OK(inner->Append(value));
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> U8List(
    const std::vector<std::uint8_t>& values) {
  auto value_builder = std::make_shared<arrow::UInt8Builder>();
  arrow::ListBuilder builder(arrow::default_memory_pool(), value_builder);
  ARROW_RETURN_NOT_OK(builder.Append());
  auto* inner = static_cast<arrow::UInt8Builder*>(builder.value_builder());
  for (std::uint8_t value : values) {
    ARROW_RETURN_NOT_OK(inner->Append(value));
  }
  return builder.Finish();
}

inline arrow::Result<std::shared_ptr<arrow::Array>> BinaryList(
    const std::vector<Bytes>& values) {
  auto value_builder = std::make_shared<arrow::LargeBinaryBuilder>();
  arrow::ListBuilder builder(arrow::default_memory_pool(), value_builder);
  ARROW_RETURN_NOT_OK(builder.Append());
  auto* inner =
      static_cast<arrow::LargeBinaryBuilder*>(builder.value_builder());
  for (const auto& value : values) {
    ARROW_RETURN_NOT_OK(
        inner->Append(value.data(), static_cast<std::int64_t>(value.size())));
  }
  return builder.Finish();
}

inline std::shared_ptr<arrow::Array> Column(const arrow::RecordBatch& batch,
                                            const std::string& name) {
  return batch.GetColumnByName(name);
}

template <typename ArrayType>
inline arrow::Result<std::shared_ptr<ArrayType>> ColumnAs(
    const arrow::RecordBatch& batch, const std::string& name) {
  auto column = Column(batch, name);
  if (!column) {
    return arrow::Status::Invalid("missing ", name, " column");
  }
  auto typed = std::dynamic_pointer_cast<ArrayType>(column);
  if (!typed) {
    return arrow::Status::Invalid(name, " column has unexpected type");
  }
  return typed;
}

template <typename ArrayType>
inline arrow::Result<std::shared_ptr<ArrayType>> ScalarColumn(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array, ColumnAs<ArrayType>(batch, name));
  if (array->length() == 0 || array->IsNull(0)) {
    return arrow::Status::Invalid(name,
                                  " must contain one non-null scalar row");
  }
  return array;
}

inline arrow::Result<std::string> ReadString(const arrow::RecordBatch& batch,
                                             const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        ScalarColumn<arrow::StringArray>(batch, name));
  return array->GetString(0);
}

inline arrow::Result<std::optional<std::string>> ReadOptionalString(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array, ColumnAs<arrow::StringArray>(batch, name));
  if (array->length() != 1)
    return arrow::Status::Invalid(name, " must contain one row");
  if (array->IsNull(0)) return std::optional<std::string>{};
  return std::optional<std::string>{array->GetString(0)};
}

inline arrow::Result<std::string> ReadOptionalString(
    const arrow::RecordBatch& batch, const std::string& name,
    const std::string& default_value) {
  auto column = Column(batch, name);
  if (!column) {
    return default_value;
  }
  auto array = std::dynamic_pointer_cast<arrow::StringArray>(column);
  if (!array) {
    return arrow::Status::Invalid(name, " column must be utf8");
  }
  if (array->length() == 0) {
    return arrow::Status::Invalid(name, " column is empty");
  }
  if (array->IsNull(0)) {
    return default_value;
  }
  return array->GetString(0);
}

inline arrow::Result<std::uint32_t> ReadU32(const arrow::RecordBatch& batch,
                                            const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        ScalarColumn<arrow::UInt32Array>(batch, name));
  return array->Value(0);
}

inline arrow::Result<std::uint64_t> ReadU64(const arrow::RecordBatch& batch,
                                            const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        ScalarColumn<arrow::UInt64Array>(batch, name));
  return array->Value(0);
}

inline arrow::Result<std::int64_t> ReadI64(const arrow::RecordBatch& batch,
                                           const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        ScalarColumn<arrow::Int64Array>(batch, name));
  return array->Value(0);
}

inline arrow::Result<std::optional<std::int64_t>> ReadOptionalI64(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array, ColumnAs<arrow::Int64Array>(batch, name));
  if (array->length() != 1)
    return arrow::Status::Invalid(name, " must contain one row");
  if (array->IsNull(0)) return std::optional<std::int64_t>{};
  return std::optional<std::int64_t>{array->Value(0)};
}

inline arrow::Result<double> ReadF64(const arrow::RecordBatch& batch,
                                     const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        ScalarColumn<arrow::DoubleArray>(batch, name));
  return array->Value(0);
}

inline arrow::Result<std::optional<double>> ReadOptionalF64(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array, ColumnAs<arrow::DoubleArray>(batch, name));
  if (array->length() != 1)
    return arrow::Status::Invalid(name, " must contain one row");
  if (array->IsNull(0)) return std::optional<double>{};
  return std::optional<double>{array->Value(0)};
}

inline arrow::Result<bool> ReadBool(const arrow::RecordBatch& batch,
                                    const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        ScalarColumn<arrow::BooleanArray>(batch, name));
  return array->Value(0);
}

inline arrow::Result<Bytes> ReadBinary(const arrow::RecordBatch& batch,
                                       const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        ScalarColumn<arrow::LargeBinaryArray>(batch, name));
  auto view = array->GetView(0);
  return Bytes(view.begin(), view.end());
}

inline arrow::Result<std::shared_ptr<arrow::Array>> ListValues(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto list, ColumnAs<arrow::ListArray>(batch, name));
  if (list->length() == 0 || list->IsNull(0)) {
    return arrow::Status::Invalid(name, " must contain one non-null list row");
  }
  return list->value_slice(0);
}

template <typename ArrayType>
inline arrow::Status RejectNullItems(const std::shared_ptr<ArrayType>& array,
                                     const std::string& name) {
  if (array->null_count() != 0) {
    return arrow::Status::Invalid(name, " values must not contain nulls");
  }
  return arrow::Status::OK();
}

inline arrow::Result<std::vector<std::string>> ReadStringList(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto values, ListValues(batch, name));
  auto array = std::dynamic_pointer_cast<arrow::StringArray>(values);
  if (!array) {
    return arrow::Status::Invalid(name, " values must be utf8");
  }
  ARROW_RETURN_NOT_OK(RejectNullItems(array, name));
  std::vector<std::string> out;
  out.reserve(static_cast<std::size_t>(array->length()));
  for (int64_t i = 0; i < array->length(); ++i) {
    out.push_back(array->GetString(i));
  }
  return out;
}

inline arrow::Result<std::vector<double>> ReadF64List(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto values, ListValues(batch, name));
  auto array = std::dynamic_pointer_cast<arrow::DoubleArray>(values);
  if (!array) {
    return arrow::Status::Invalid(name, " values must be float64");
  }
  ARROW_RETURN_NOT_OK(RejectNullItems(array, name));
  std::vector<double> out;
  out.reserve(static_cast<std::size_t>(array->length()));
  for (int64_t i = 0; i < array->length(); ++i) {
    out.push_back(array->Value(i));
  }
  return out;
}

inline arrow::Result<std::vector<float>> ReadF32List(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto values, ListValues(batch, name));
  auto array = std::dynamic_pointer_cast<arrow::FloatArray>(values);
  if (!array) {
    return arrow::Status::Invalid(name, " values must be float32");
  }
  ARROW_RETURN_NOT_OK(RejectNullItems(array, name));
  std::vector<float> out;
  out.reserve(static_cast<std::size_t>(array->length()));
  for (int64_t i = 0; i < array->length(); ++i) {
    out.push_back(array->Value(i));
  }
  return out;
}

inline arrow::Result<std::vector<std::uint32_t>> ReadU32List(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto values, ListValues(batch, name));
  auto array = std::dynamic_pointer_cast<arrow::UInt32Array>(values);
  if (!array) {
    return arrow::Status::Invalid(name, " values must be uint32");
  }
  ARROW_RETURN_NOT_OK(RejectNullItems(array, name));
  std::vector<std::uint32_t> out;
  out.reserve(static_cast<std::size_t>(array->length()));
  for (int64_t i = 0; i < array->length(); ++i) {
    out.push_back(array->Value(i));
  }
  return out;
}

inline arrow::Result<std::vector<std::uint8_t>> ReadU8List(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto values, ListValues(batch, name));
  auto array = std::dynamic_pointer_cast<arrow::UInt8Array>(values);
  if (!array) {
    return arrow::Status::Invalid(name, " values must be uint8");
  }
  ARROW_RETURN_NOT_OK(RejectNullItems(array, name));
  std::vector<std::uint8_t> out;
  out.reserve(static_cast<std::size_t>(array->length()));
  for (int64_t i = 0; i < array->length(); ++i) {
    out.push_back(array->Value(i));
  }
  return out;
}

inline arrow::Result<std::vector<Bytes>> ReadBinaryList(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto values, ListValues(batch, name));
  auto array = std::dynamic_pointer_cast<arrow::LargeBinaryArray>(values);
  if (!array) {
    return arrow::Status::Invalid(name, " values must be large_binary");
  }
  ARROW_RETURN_NOT_OK(RejectNullItems(array, name));
  std::vector<Bytes> out;
  out.reserve(static_cast<std::size_t>(array->length()));
  for (int64_t i = 0; i < array->length(); ++i) {
    auto view = array->GetView(i);
    out.emplace_back(view.begin(), view.end());
  }
  return out;
}

inline arrow::Result<std::shared_ptr<arrow::RecordBatch>> MakeBatch(
    std::vector<std::shared_ptr<arrow::Field>> fields,
    std::vector<std::shared_ptr<arrow::Array>> columns) {
  return arrow::RecordBatch::Make(arrow::schema(std::move(fields)), 1,
                                  std::move(columns));
}

inline arrow::Status ValidateUnique(const std::string& name,
                                    const std::vector<std::string>& values) {
  std::set<std::string> seen;
  for (const auto& value : values) {
    if (!seen.insert(value).second) {
      return arrow::Status::Invalid(name, " items must be unique");
    }
  }
  return arrow::Status::OK();
}

inline arrow::Status ValidateRequired(const std::string& name,
                                      const std::string& value) {
  if (value.empty()) {
    return arrow::Status::Invalid(name, " must be non-empty");
  }
  return arrow::Status::OK();
}

inline arrow::Status ValidateSnakeCase(const std::string& value) {
  if (value.empty() ||
      !std::islower(static_cast<unsigned char>(value.front()))) {
    return arrow::Status::Invalid("command must use snake_case");
  }
  for (char c : value) {
    if (!(std::islower(static_cast<unsigned char>(c)) ||
          std::isdigit(static_cast<unsigned char>(c)) || c == '_')) {
      return arrow::Status::Invalid("command must use snake_case");
    }
  }
  return arrow::Status::OK();
}

inline arrow::Status ValidateJsonObject(const std::string& name,
                                        const std::string& value) {
  auto first = value.find_first_not_of(" \t\r\n");
  auto last = value.find_last_not_of(" \t\r\n");
  if (first == std::string::npos || value[first] != '{' || value[last] != '}') {
    return arrow::Status::Invalid(name, " must be a JSON object");
  }
  return arrow::Status::OK();
}

template <typename T>
inline arrow::Status ValidateLen(const std::string& field,
                                 const std::vector<T>& values,
                                 std::size_t expected,
                                 bool allow_empty = false) {
  if ((allow_empty && values.empty()) || values.size() == expected) {
    return arrow::Status::OK();
  }
  return arrow::Status::Invalid(
      field, allow_empty ? " must be empty or have the expected length"
                         : " must have the expected length");
}

inline arrow::Status ValidateFinite(const std::string& name, double value) {
  if (!std::isfinite(value)) {
    return arrow::Status::Invalid(name, " must be finite");
  }
  return arrow::Status::OK();
}

inline arrow::Status ValidateFiniteList(const std::string& name,
                                        const std::vector<float>& values) {
  for (float value : values) {
    if (!std::isfinite(value)) {
      return arrow::Status::Invalid(name, " values must be finite");
    }
  }
  return arrow::Status::OK();
}

inline arrow::Status ValidateNonNegativeList(const std::string& name,
                                             const std::vector<float>& values) {
  ARROW_RETURN_NOT_OK(ValidateFiniteList(name, values));
  for (float value : values) {
    if (value < 0.0f) {
      return arrow::Status::Invalid(name, " values must be non-negative");
    }
  }
  return arrow::Status::OK();
}

inline arrow::Status ValidateQuaternion(double qx, double qy, double qz,
                                        double qw) {
  if (qx == 0.0 && qy == 0.0 && qz == 0.0 && qw == 0.0) {
    return arrow::Status::Invalid("quaternion must not be all zero");
  }
  return arrow::Status::OK();
}

inline arrow::Status ValidateHypotheses(
    std::size_t detection_count, const std::vector<std::uint32_t>& offsets,
    const std::vector<std::string>& class_id, const std::vector<float>& score) {
  if (offsets.size() != detection_count + 1) {
    return arrow::Status::Invalid(
        "hypothesis_offset must have detection_count + 1 entries");
  }
  if (offsets.empty() || offsets.front() != 0 ||
      offsets.back() != class_id.size()) {
    return arrow::Status::Invalid(
        "hypothesis_offset must start at 0 and end at len(class_id)");
  }
  for (std::size_t i = 1; i < offsets.size(); ++i) {
    if (offsets[i] < offsets[i - 1]) {
      return arrow::Status::Invalid(
          "hypothesis_offset must be monotonically non-decreasing");
    }
  }
  if (score.size() != class_id.size()) {
    return arrow::Status::Invalid(
        "score must have the same length as class_id");
  }
  for (float value : score) {
    if (!std::isfinite(value) || value < 0.0f || value > 1.0f) {
      return arrow::Status::Invalid(
          "score values must be finite and in [0, 1]");
    }
  }
  return arrow::Status::OK();
}

inline std::size_t BytesPerSample(const std::string& sample_format) {
  if (sample_format == "f32le") return 4;
  if (sample_format == "s16le") return 2;
  return 0;
}

arrow::Result<std::shared_ptr<arrow::Array>> StructScalar(
    const arrow::RecordBatch& batch, bool valid = true);
arrow::Result<std::shared_ptr<arrow::Array>> StructList(
    const std::vector<std::shared_ptr<arrow::RecordBatch>>& batches,
    const std::vector<std::shared_ptr<arrow::Field>>& fields);
arrow::Result<std::shared_ptr<arrow::RecordBatch>> ReadStruct(
    const arrow::RecordBatch& batch, const std::string& name);
arrow::Result<std::optional<std::shared_ptr<arrow::RecordBatch>>>
ReadOptionalStruct(const arrow::RecordBatch& batch, const std::string& name);
arrow::Result<std::vector<std::shared_ptr<arrow::RecordBatch>>> ReadStructList(
    const arrow::RecordBatch& batch, const std::string& name);

inline std::size_t BytesPerPixel(const std::string& encoding) {
  if (encoding == "rgb8" || encoding == "bgr8") return 3;
  if (encoding == "mono8" || encoding == "8UC1") return 1;
  if (encoding == "16UC1") return 2;
  if (encoding == "32SC1" || encoding == "32FC1") return 4;
  return 0;
}

}  // namespace forge_msgs::detail
