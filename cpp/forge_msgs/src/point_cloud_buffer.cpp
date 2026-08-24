#include "detail.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <set>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace forge_msgs {

using namespace detail;

namespace {

arrow::Status CheckedMultiply(std::uint64_t left, std::uint64_t right,
                              std::string_view expression,
                              std::uint64_t* result) {
  if (right != 0 && left > std::numeric_limits<std::uint64_t>::max() / right) {
    return arrow::Status::Invalid(expression, " overflows uint64");
  }
  *result = left * right;
  return arrow::Status::OK();
}

arrow::Status CheckedAdd(std::uint64_t left, std::uint64_t right,
                         std::string_view expression, std::uint64_t* result) {
  if (left > std::numeric_limits<std::uint64_t>::max() - right) {
    return arrow::Status::Invalid(expression, " overflows uint64");
  }
  *result = left + right;
  return arrow::Status::OK();
}

bool IsUtf8Continuation(std::uint8_t byte) {
  return (byte & 0xc0U) == 0x80U;
}

bool IsValidUtf8(std::string_view value) {
  std::size_t index = 0;
  while (index < value.size()) {
    const auto first = static_cast<std::uint8_t>(value[index]);
    if (first <= 0x7fU) {
      ++index;
      continue;
    }

    if (first >= 0xc2U && first <= 0xdfU) {
      if (value.size() - index < 2 ||
          !IsUtf8Continuation(static_cast<std::uint8_t>(value[index + 1]))) {
        return false;
      }
      index += 2;
      continue;
    }

    if (first >= 0xe0U && first <= 0xefU) {
      if (value.size() - index < 3) return false;
      const auto second = static_cast<std::uint8_t>(value[index + 1]);
      const auto third = static_cast<std::uint8_t>(value[index + 2]);
      const bool valid_second =
          (first == 0xe0U && second >= 0xa0U && second <= 0xbfU) ||
          (first == 0xedU && second >= 0x80U && second <= 0x9fU) ||
          (((first >= 0xe1U && first <= 0xecU) ||
            (first >= 0xeeU && first <= 0xefU)) &&
           IsUtf8Continuation(second));
      if (!valid_second || !IsUtf8Continuation(third)) return false;
      index += 3;
      continue;
    }

    if (first >= 0xf0U && first <= 0xf4U) {
      if (value.size() - index < 4) return false;
      const auto second = static_cast<std::uint8_t>(value[index + 1]);
      const auto third = static_cast<std::uint8_t>(value[index + 2]);
      const auto fourth = static_cast<std::uint8_t>(value[index + 3]);
      const bool valid_second =
          (first == 0xf0U && second >= 0x90U && second <= 0xbfU) ||
          (first == 0xf4U && second >= 0x80U && second <= 0x8fU) ||
          (first >= 0xf1U && first <= 0xf3U &&
           IsUtf8Continuation(second));
      if (!valid_second || !IsUtf8Continuation(third) ||
          !IsUtf8Continuation(fourth)) {
        return false;
      }
      index += 4;
      continue;
    }

    return false;
  }
  return true;
}

arrow::Status ValidatePointFieldName(std::string_view name) {
  if (name.empty()) {
    return arrow::Status::Invalid("PointField name must be non-empty");
  }
  if (!IsValidUtf8(name)) {
    return arrow::Status::Invalid("PointField name must be valid UTF-8");
  }
  return arrow::Status::OK();
}

arrow::Status ValidateByteOrder(ByteOrder value) {
  switch (value) {
    case ByteOrder::LittleEndian:
    case ByteOrder::BigEndian:
      return arrow::Status::OK();
  }
  return arrow::Status::Invalid("byte_order is invalid");
}

arrow::Result<bool> NeedsHostByteSwap(ByteOrder byte_order) {
  ARROW_RETURN_NOT_OK(ValidateByteOrder(byte_order));
  if constexpr (std::endian::native == std::endian::little) {
    return byte_order == ByteOrder::BigEndian;
  } else if constexpr (std::endian::native == std::endian::big) {
    return byte_order == ByteOrder::LittleEndian;
  } else {
    return arrow::Status::NotImplemented(
        "PointCloudBuffer does not support mixed-endian hosts");
  }
}

arrow::Status PointValueOffset(std::uint32_t row, std::uint32_t column,
                               std::uint64_t row_stride,
                               std::uint32_t point_stride,
                               std::uint32_t field_offset,
                               std::uint64_t* result) {
  std::uint64_t row_offset = 0;
  std::uint64_t column_offset = 0;
  std::uint64_t point_offset = 0;
  ARROW_RETURN_NOT_OK(CheckedMultiply(row, row_stride, "row * row_stride",
                                      &row_offset));
  ARROW_RETURN_NOT_OK(CheckedMultiply(column, point_stride,
                                      "column * point_stride",
                                      &column_offset));
  ARROW_RETURN_NOT_OK(CheckedAdd(row_offset, column_offset,
                                 "row offset + column offset", &point_offset));
  return CheckedAdd(point_offset, field_offset,
                    "point offset + field offset", result);
}

arrow::Status CopyWireScalar(std::span<const std::uint8_t> data,
                             std::uint64_t offset, std::size_t size,
                             ByteOrder byte_order, void* output) {
  if (size == 0 || size > 8) {
    return arrow::Status::Invalid("unsupported PointField scalar byte width");
  }
  if (offset > data.size() || size > data.size() - offset) {
    return arrow::Status::IndexError(
        "PointCloudBuffer scalar byte range is out of bounds");
  }

  std::array<std::uint8_t, 8> bytes{};
  std::memcpy(bytes.data(), data.data() + static_cast<std::size_t>(offset), size);
  ARROW_ASSIGN_OR_RAISE(const bool swap, NeedsHostByteSwap(byte_order));
  if (swap && size > 1) {
    std::reverse(bytes.begin(), bytes.begin() + static_cast<std::ptrdiff_t>(size));
  }
  std::memcpy(output, bytes.data(), size);
  return arrow::Status::OK();
}

template <typename T>
arrow::Result<T> ReadWireScalar(std::span<const std::uint8_t> data,
                                std::uint64_t offset, ByteOrder byte_order) {
  T value{};
  ARROW_RETURN_NOT_OK(
      CopyWireScalar(data, offset, sizeof(T), byte_order, &value));
  return value;
}

arrow::Result<std::uint64_t> FieldByteWidth(const PointField& field) {
  ARROW_ASSIGN_OR_RAISE(const auto datatype_size,
                        PointFieldDatatypeSize(field.datatype));
  std::uint64_t width = 0;
  ARROW_RETURN_NOT_OK(CheckedMultiply(datatype_size, field.count,
                                      "datatype_size * count", &width));
  return width;
}

arrow::Status ValidatePointCloudBuffer(
    std::uint32_t width, std::uint32_t height, bool is_dense,
    ByteOrder byte_order, std::uint32_t point_stride,
    std::uint64_t row_stride, const std::vector<PointField>& fields,
    std::span<const std::uint8_t> data) {
  if (height == 0) {
    return arrow::Status::Invalid("height must be greater than 0");
  }
  if (point_stride == 0) {
    return arrow::Status::Invalid("point_stride must be greater than 0");
  }
  if (width == 0 &&
      (height != 1 || row_stride != 0 || !data.empty())) {
    return arrow::Status::Invalid(
        "width == 0 requires height == 1, row_stride == 0, and empty data");
  }
  ARROW_RETURN_NOT_OK(ValidateByteOrder(byte_order));

  std::uint64_t point_count = 0;
  std::uint64_t minimum_row_stride = 0;
  std::uint64_t expected_data_length = 0;
  ARROW_RETURN_NOT_OK(
      CheckedMultiply(width, height, "width * height", &point_count));
  ARROW_RETURN_NOT_OK(CheckedMultiply(width, point_stride,
                                      "width * point_stride",
                                      &minimum_row_stride));
  if (row_stride < minimum_row_stride) {
    return arrow::Status::Invalid(
        "row_stride must be at least width * point_stride");
  }
  ARROW_RETURN_NOT_OK(CheckedMultiply(row_stride, height,
                                      "row_stride * height",
                                      &expected_data_length));
  if (expected_data_length > std::numeric_limits<std::size_t>::max() ||
      data.size() != static_cast<std::size_t>(expected_data_length)) {
    return arrow::Status::Invalid(
        "data length must equal row_stride * height");
  }

  if (fields.empty()) {
    return arrow::Status::Invalid("fields must contain at least one descriptor");
  }

  struct FieldRange {
    std::uint64_t begin;
    std::uint64_t end;
    std::string name;
  };

  std::set<std::string> names;
  std::vector<FieldRange> ranges;
  ranges.reserve(fields.size());
  const PointField* x = nullptr;
  const PointField* y = nullptr;
  const PointField* z = nullptr;

  for (const auto& field : fields) {
    ARROW_RETURN_NOT_OK(ValidatePointFieldName(field.name));
    if (!names.insert(field.name).second) {
      return arrow::Status::Invalid("PointField names must be unique");
    }
    if (field.count == 0) {
      return arrow::Status::Invalid("PointField count must be greater than 0: ",
                                    field.name);
    }

    ARROW_ASSIGN_OR_RAISE(const auto byte_width, FieldByteWidth(field));
    std::uint64_t end = 0;
    ARROW_RETURN_NOT_OK(CheckedAdd(field.offset, byte_width,
                                   "field offset + byte width", &end));
    if (end > point_stride) {
      return arrow::Status::Invalid("PointField exceeds point_stride: ",
                                    field.name);
    }
    ranges.push_back({field.offset, end, field.name});

    if (field.name == "x") x = &field;
    if (field.name == "y") y = &field;
    if (field.name == "z") z = &field;
  }

  std::sort(ranges.begin(), ranges.end(),
            [](const FieldRange& left, const FieldRange& right) {
              if (left.begin != right.begin) return left.begin < right.begin;
              if (left.end != right.end) return left.end < right.end;
              return left.name < right.name;
            });
  for (std::size_t index = 1; index < ranges.size(); ++index) {
    if (ranges[index].begin < ranges[index - 1].end) {
      return arrow::Status::Invalid(
          "PointField byte ranges must not overlap: ", ranges[index - 1].name,
          " and ", ranges[index].name);
    }
  }

  if (x == nullptr || y == nullptr || z == nullptr) {
    return arrow::Status::Invalid(
        "exactly one x, y, and z PointField must be present");
  }
  for (const auto* coordinate : {x, y, z}) {
    if (coordinate->count != 1) {
      return arrow::Status::Invalid(
          "x, y, and z PointFields must be scalar");
    }
    if (coordinate->datatype != PointFieldDatatype::Float32 &&
        coordinate->datatype != PointFieldDatatype::Float64) {
      return arrow::Status::Invalid(
          "x, y, and z PointFields must use float32 or float64");
    }
  }
  if (x->datatype != y->datatype || x->datatype != z->datatype) {
    return arrow::Status::Invalid(
        "x, y, and z PointFields must use the same datatype");
  }

  if (!is_dense) return arrow::Status::OK();

  for (std::uint32_t row = 0; row < height; ++row) {
    for (std::uint32_t column = 0; column < width; ++column) {
      for (const auto* coordinate : {x, y, z}) {
        std::uint64_t offset = 0;
        ARROW_RETURN_NOT_OK(PointValueOffset(
            row, column, row_stride, point_stride, coordinate->offset, &offset));
        if (coordinate->datatype == PointFieldDatatype::Float32) {
          ARROW_ASSIGN_OR_RAISE(
              const float value,
              ReadWireScalar<float>(data, offset, byte_order));
          if (!std::isfinite(value)) {
            return arrow::Status::Invalid(
                "dense PointCloudBuffer XYZ values must be finite");
          }
        } else {
          ARROW_ASSIGN_OR_RAISE(
              const double value,
              ReadWireScalar<double>(data, offset, byte_order));
          if (!std::isfinite(value)) {
            return arrow::Status::Invalid(
                "dense PointCloudBuffer XYZ values must be finite");
          }
        }
      }
    }
  }
  return arrow::Status::OK();
}

std::vector<std::shared_ptr<arrow::Field>> PointFieldArrowFields() {
  return {arrow::field("name", arrow::utf8(), false),
          arrow::field("offset", arrow::uint32(), false),
          arrow::field("datatype", arrow::utf8(), false),
          arrow::field("count", arrow::uint32(), false)};
}

std::shared_ptr<arrow::DataType> PointFieldListType() {
  return arrow::list(
      arrow::field("item", arrow::struct_(PointFieldArrowFields()), true));
}

arrow::Result<std::shared_ptr<arrow::Array>> PointFieldList(
    const std::vector<PointField>& fields) {
  const auto struct_type = arrow::struct_(PointFieldArrowFields());
  ARROW_ASSIGN_OR_RAISE(
      auto value_builder,
      arrow::MakeBuilder(struct_type, arrow::default_memory_pool()));
  auto shared_value_builder =
      std::shared_ptr<arrow::ArrayBuilder>(std::move(value_builder));
  arrow::ListBuilder list_builder(arrow::default_memory_pool(),
                                  shared_value_builder);
  auto* struct_builder =
      static_cast<arrow::StructBuilder*>(list_builder.value_builder());

  ARROW_RETURN_NOT_OK(list_builder.Append());
  for (const auto& field : fields) {
    ARROW_RETURN_NOT_OK(struct_builder->Append());
    auto* name_builder =
        static_cast<arrow::StringBuilder*>(struct_builder->field_builder(0));
    auto* offset_builder =
        static_cast<arrow::UInt32Builder*>(struct_builder->field_builder(1));
    auto* datatype_builder =
        static_cast<arrow::StringBuilder*>(struct_builder->field_builder(2));
    auto* count_builder =
        static_cast<arrow::UInt32Builder*>(struct_builder->field_builder(3));
    ARROW_RETURN_NOT_OK(name_builder->Append(field.name));
    ARROW_RETURN_NOT_OK(offset_builder->Append(field.offset));
    ARROW_RETURN_NOT_OK(datatype_builder->Append(ToString(field.datatype)));
    ARROW_RETURN_NOT_OK(count_builder->Append(field.count));
  }
  return list_builder.Finish();
}

arrow::Result<Bytes> CanonicalLittleEndianData(
    const PointCloudBuffer& value) {
  Bytes data = value.data;
  if (value.byte_order == ByteOrder::LittleEndian) return data;

  for (std::uint32_t row = 0; row < value.height; ++row) {
    for (std::uint32_t column = 0; column < value.width; ++column) {
      for (const auto& field : value.fields) {
        ARROW_ASSIGN_OR_RAISE(const auto datatype_size,
                              PointFieldDatatypeSize(field.datatype));
        if (datatype_size == 1) continue;
        std::uint64_t field_offset = 0;
        ARROW_RETURN_NOT_OK(PointValueOffset(
            row, column, value.row_stride, value.point_stride, field.offset,
            &field_offset));
        for (std::uint32_t element = 0; element < field.count; ++element) {
          std::uint64_t element_delta = 0;
          std::uint64_t element_offset = 0;
          ARROW_RETURN_NOT_OK(CheckedMultiply(
              element, datatype_size, "element * datatype_size",
              &element_delta));
          ARROW_RETURN_NOT_OK(CheckedAdd(
              field_offset, element_delta, "field offset + element offset",
              &element_offset));
          auto begin = data.begin() +
                       static_cast<std::ptrdiff_t>(element_offset);
          std::reverse(begin,
                       begin + static_cast<std::ptrdiff_t>(datatype_size));
        }
      }
    }
  }
  return data;
}

arrow::Result<int> UniqueColumnIndex(const arrow::RecordBatch& batch,
                                     const std::string& name) {
  int index = -1;
  int count = 0;
  for (int candidate = 0; candidate < batch.num_columns(); ++candidate) {
    if (batch.schema()->field(candidate)->name() == name) {
      index = candidate;
      ++count;
    }
  }
  if (count == 0) {
    return arrow::Status::Invalid("missing ", name, " column");
  }
  if (count != 1) {
    return arrow::Status::Invalid(name,
                                  " column must appear exactly once, got ",
                                  count);
  }
  return index;
}

template <typename ArrayType>
arrow::Result<std::shared_ptr<ArrayType>> RequiredArray(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(const int index, UniqueColumnIndex(batch, name));
  auto array = std::dynamic_pointer_cast<ArrayType>(batch.column(index));
  if (!array) {
    return arrow::Status::Invalid(name, " column has unexpected physical type");
  }
  if (array->length() != 1 || array->IsNull(0)) {
    return arrow::Status::Invalid(name,
                                  " must contain one non-null scalar row");
  }
  return array;
}

arrow::Status ValidatePointFieldStructType(
    const std::shared_ptr<arrow::StructArray>& values) {
  const auto expected = PointFieldArrowFields();
  const auto type = values->struct_type();
  if (type->num_fields() != static_cast<int>(expected.size())) {
    return arrow::Status::Invalid(
        "fields struct must contain name, offset, datatype, and count");
  }
  for (int index = 0; index < type->num_fields(); ++index) {
    if (type->field(index)->name() != expected[static_cast<std::size_t>(index)]->name() ||
        !type->field(index)->type()->Equals(
            *expected[static_cast<std::size_t>(index)]->type())) {
      return arrow::Status::Invalid(
          "fields struct has unexpected child name, order, or physical type");
    }
  }
  return arrow::Status::OK();
}

arrow::Result<std::vector<PointField>> ReadPointFields(
    const arrow::RecordBatch& batch) {
  ARROW_ASSIGN_OR_RAISE(auto list,
                        RequiredArray<arrow::ListArray>(batch, "fields"));
  auto values =
      std::dynamic_pointer_cast<arrow::StructArray>(list->value_slice(0));
  if (!values) {
    return arrow::Status::Invalid("fields values must be struct");
  }
  ARROW_RETURN_NOT_OK(ValidatePointFieldStructType(values));
  if (values->null_count() != 0) {
    return arrow::Status::Invalid("fields values must not contain null structs");
  }

  auto names = std::dynamic_pointer_cast<arrow::StringArray>(values->field(0));
  auto offsets =
      std::dynamic_pointer_cast<arrow::UInt32Array>(values->field(1));
  auto datatypes =
      std::dynamic_pointer_cast<arrow::StringArray>(values->field(2));
  auto counts =
      std::dynamic_pointer_cast<arrow::UInt32Array>(values->field(3));
  if (!names || !offsets || !datatypes || !counts) {
    return arrow::Status::Invalid(
        "fields struct children have unexpected physical types");
  }
  if (names->null_count() != 0 || offsets->null_count() != 0 ||
      datatypes->null_count() != 0 || counts->null_count() != 0) {
    return arrow::Status::Invalid(
        "fields struct children must not contain nulls");
  }

  std::vector<PointField> fields;
  fields.reserve(static_cast<std::size_t>(values->length()));
  for (std::int64_t index = 0; index < values->length(); ++index) {
    const auto name = names->GetString(index);
    ARROW_RETURN_NOT_OK(ValidatePointFieldName(name));
    ARROW_ASSIGN_OR_RAISE(
        auto datatype,
        PointFieldDatatypeFromString(datatypes->GetString(index)));
    fields.push_back(PointField{name, offsets->Value(index), datatype,
                                counts->Value(index)});
  }
  return fields;
}

struct PointCloudBufferColumns {
  std::uint32_t width;
  std::uint32_t height;
  bool is_dense;
  ByteOrder byte_order;
  std::uint32_t point_stride;
  std::uint64_t row_stride;
  std::vector<PointField> fields;
  std::shared_ptr<arrow::LargeBinaryArray> data;
};

arrow::Result<PointCloudBufferColumns> ReadPointCloudBufferColumns(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  PointCloudBufferColumns columns;

  ARROW_ASSIGN_OR_RAISE(auto width,
                        RequiredArray<arrow::UInt32Array>(batch, "width"));
  columns.width = width->Value(0);
  ARROW_ASSIGN_OR_RAISE(auto height,
                        RequiredArray<arrow::UInt32Array>(batch, "height"));
  columns.height = height->Value(0);
  ARROW_ASSIGN_OR_RAISE(
      auto is_dense,
      RequiredArray<arrow::BooleanArray>(batch, "is_dense"));
  columns.is_dense = is_dense->Value(0);
  ARROW_ASSIGN_OR_RAISE(
      auto byte_order,
      RequiredArray<arrow::StringArray>(batch, "byte_order"));
  ARROW_ASSIGN_OR_RAISE(
      columns.byte_order,
      ByteOrderFromString(byte_order->GetString(0)));
  ARROW_ASSIGN_OR_RAISE(
      auto point_stride,
      RequiredArray<arrow::UInt32Array>(batch, "point_stride"));
  columns.point_stride = point_stride->Value(0);
  ARROW_ASSIGN_OR_RAISE(
      auto row_stride,
      RequiredArray<arrow::UInt64Array>(batch, "row_stride"));
  columns.row_stride = row_stride->Value(0);
  ARROW_ASSIGN_OR_RAISE(columns.fields, ReadPointFields(batch));
  ARROW_ASSIGN_OR_RAISE(
      columns.data,
      RequiredArray<arrow::LargeBinaryArray>(batch, "data"));
  return columns;
}

std::span<const std::uint8_t> BinaryData(
    const std::shared_ptr<arrow::LargeBinaryArray>& data) {
  std::int64_t length = 0;
  const auto* bytes = data->GetValue(0, &length);
  return {bytes, static_cast<std::size_t>(length)};
}

}  // namespace

std::string ToString(ByteOrder value) {
  switch (value) {
    case ByteOrder::LittleEndian:
      return "little_endian";
    case ByteOrder::BigEndian:
      return "big_endian";
  }
  return {};
}

arrow::Result<ByteOrder> ByteOrderFromString(const std::string& value) {
  if (value == "little_endian") return ByteOrder::LittleEndian;
  if (value == "big_endian") return ByteOrder::BigEndian;
  return arrow::Status::Invalid("unsupported byte_order: ", value);
}

std::string ToString(PointFieldDatatype value) {
  switch (value) {
    case PointFieldDatatype::Int8:
      return "int8";
    case PointFieldDatatype::UInt8:
      return "uint8";
    case PointFieldDatatype::Int16:
      return "int16";
    case PointFieldDatatype::UInt16:
      return "uint16";
    case PointFieldDatatype::Int32:
      return "int32";
    case PointFieldDatatype::UInt32:
      return "uint32";
    case PointFieldDatatype::Int64:
      return "int64";
    case PointFieldDatatype::UInt64:
      return "uint64";
    case PointFieldDatatype::Float32:
      return "float32";
    case PointFieldDatatype::Float64:
      return "float64";
  }
  return {};
}

arrow::Result<PointFieldDatatype> PointFieldDatatypeFromString(
    const std::string& value) {
  if (value == "int8") return PointFieldDatatype::Int8;
  if (value == "uint8") return PointFieldDatatype::UInt8;
  if (value == "int16") return PointFieldDatatype::Int16;
  if (value == "uint16") return PointFieldDatatype::UInt16;
  if (value == "int32") return PointFieldDatatype::Int32;
  if (value == "uint32") return PointFieldDatatype::UInt32;
  if (value == "int64") return PointFieldDatatype::Int64;
  if (value == "uint64") return PointFieldDatatype::UInt64;
  if (value == "float32") return PointFieldDatatype::Float32;
  if (value == "float64") return PointFieldDatatype::Float64;
  return arrow::Status::Invalid("unsupported PointField datatype: ", value);
}

arrow::Result<std::size_t> PointFieldDatatypeSize(
    PointFieldDatatype value) {
  switch (value) {
    case PointFieldDatatype::Int8:
    case PointFieldDatatype::UInt8:
      return 1;
    case PointFieldDatatype::Int16:
    case PointFieldDatatype::UInt16:
      return 2;
    case PointFieldDatatype::Int32:
    case PointFieldDatatype::UInt32:
    case PointFieldDatatype::Float32:
      return 4;
    case PointFieldDatatype::Int64:
    case PointFieldDatatype::UInt64:
    case PointFieldDatatype::Float64:
      return 8;
  }
  return arrow::Status::Invalid("PointField datatype is invalid");
}

arrow::Status PointCloudBuffer::Validate() const {
  return ValidatePointCloudBuffer(width, height, is_dense, byte_order,
                                  point_stride, row_stride, fields, data);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>>
PointCloudBuffer::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());

  std::vector<PointField> sorted_fields = fields;
  std::sort(sorted_fields.begin(), sorted_fields.end(),
            [](const PointField& left, const PointField& right) {
              if (left.offset != right.offset) return left.offset < right.offset;
              return left.name < right.name;
            });
  ARROW_ASSIGN_OR_RAISE(auto canonical_data,
                        CanonicalLittleEndianData(*this));

  ARROW_ASSIGN_OR_RAISE(auto width_array, ScalarU32(width));
  ARROW_ASSIGN_OR_RAISE(auto height_array, ScalarU32(height));
  ARROW_ASSIGN_OR_RAISE(auto is_dense_array, ScalarBool(is_dense));
  ARROW_ASSIGN_OR_RAISE(
      auto byte_order_array,
      ScalarString(ToString(ByteOrder::LittleEndian)));
  ARROW_ASSIGN_OR_RAISE(auto point_stride_array, ScalarU32(point_stride));
  ARROW_ASSIGN_OR_RAISE(auto row_stride_array, ScalarU64(row_stride));
  ARROW_ASSIGN_OR_RAISE(auto fields_array, PointFieldList(sorted_fields));
  ARROW_ASSIGN_OR_RAISE(auto data_array, ScalarBinary(canonical_data));

  return MakeBatch(
      {arrow::field("width", arrow::uint32(), false),
       arrow::field("height", arrow::uint32(), false),
       arrow::field("is_dense", arrow::boolean(), false),
       arrow::field("byte_order", arrow::utf8(), false),
       arrow::field("point_stride", arrow::uint32(), false),
       arrow::field("row_stride", arrow::uint64(), false),
       arrow::field("fields", PointFieldListType(), false),
       arrow::field("data", arrow::large_binary(), false)},
      {width_array, height_array, is_dense_array, byte_order_array,
       point_stride_array, row_stride_array, fields_array, data_array});
}

arrow::Result<PointCloudBuffer> PointCloudBuffer::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_ASSIGN_OR_RAISE(auto columns, ReadPointCloudBufferColumns(batch));
  const auto data = BinaryData(columns.data);
  PointCloudBuffer value{columns.width,
                         columns.height,
                         columns.is_dense,
                         columns.byte_order,
                         columns.point_stride,
                         columns.row_stride,
                         std::move(columns.fields),
                         Bytes(data.begin(), data.end())};
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

PointCloudBufferView::PointCloudBufferView(
    std::uint32_t width, std::uint32_t height, bool is_dense,
    ByteOrder byte_order, std::uint32_t point_stride,
    std::uint64_t row_stride, std::vector<PointField> fields,
    std::span<const std::uint8_t> data, std::shared_ptr<const void> owner)
    : width_(width),
      height_(height),
      is_dense_(is_dense),
      byte_order_(byte_order),
      point_stride_(point_stride),
      row_stride_(row_stride),
      fields_(std::move(fields)),
      data_(data),
      owner_(std::move(owner)) {}

arrow::Result<PointCloudBufferView>
PointCloudBufferView::FromPointCloudBuffer(PointCloudBuffer value) {
  ARROW_RETURN_NOT_OK(value.Validate());
  auto owner = std::make_shared<const PointCloudBuffer>(std::move(value));
  const std::span<const std::uint8_t> data(owner->data);
  auto fields = owner->fields;
  std::shared_ptr<const void> storage = owner;
  return PointCloudBufferView(
      owner->width, owner->height, owner->is_dense, owner->byte_order,
      owner->point_stride, owner->row_stride, std::move(fields), data,
      std::move(storage));
}

arrow::Result<PointCloudBufferView> PointCloudBufferView::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_ASSIGN_OR_RAISE(auto value, PointCloudBuffer::FromRecordBatch(batch));
  return FromPointCloudBuffer(std::move(value));
}

arrow::Result<PointCloudBufferView> PointCloudBufferView::FromRecordBatch(
    std::shared_ptr<const arrow::RecordBatch> batch) {
  if (!batch) {
    return arrow::Status::Invalid("RecordBatch owner must not be null");
  }
  ARROW_ASSIGN_OR_RAISE(auto columns, ReadPointCloudBufferColumns(*batch));
  const auto data = BinaryData(columns.data);
  ARROW_RETURN_NOT_OK(ValidatePointCloudBuffer(
      columns.width, columns.height, columns.is_dense, columns.byte_order,
      columns.point_stride, columns.row_stride, columns.fields, data));
  std::shared_ptr<const void> owner = batch;
  return PointCloudBufferView(
      columns.width, columns.height, columns.is_dense, columns.byte_order,
      columns.point_stride, columns.row_stride, std::move(columns.fields), data,
      std::move(owner));
}

const PointField* PointCloudBufferView::FindField(
    std::string_view name) const noexcept {
  const auto match = std::find_if(
      fields_.begin(), fields_.end(),
      [name](const PointField& field) { return field.name == name; });
  return match == fields_.end() ? nullptr : &*match;
}

arrow::Result<std::span<const std::uint8_t>>
PointCloudBufferView::PointBytes(std::uint32_t row,
                                 std::uint32_t column) const {
  if (row >= height_ || column >= width_) {
    return arrow::Status::IndexError("point row or column is out of range");
  }
  std::uint64_t offset = 0;
  ARROW_RETURN_NOT_OK(PointValueOffset(row, column, row_stride_, point_stride_,
                                      0, &offset));
  if (offset > data_.size() || point_stride_ > data_.size() - offset) {
    return arrow::Status::IndexError(
        "PointCloudBuffer point byte range is out of bounds");
  }
  return data_.subspan(static_cast<std::size_t>(offset), point_stride_);
}

arrow::Status PointCloudBufferView::ReadElementBytes(
    std::uint32_t row, std::uint32_t column, const PointField& field,
    std::uint32_t element_index, PointFieldDatatype expected_datatype,
    void* output, std::size_t output_size) const {
  if (row >= height_ || column >= width_) {
    return arrow::Status::IndexError("point row or column is out of range");
  }
  if (element_index >= field.count) {
    return arrow::Status::IndexError("PointField element index is out of range: ",
                                     field.name);
  }
  if (field.datatype != expected_datatype) {
    return arrow::Status::TypeError("PointField ", field.name, " has datatype ",
                                    ToString(field.datatype),
                                    ", incompatible with requested C++ type");
  }
  ARROW_ASSIGN_OR_RAISE(const auto datatype_size,
                        PointFieldDatatypeSize(field.datatype));
  if (datatype_size != output_size) {
    return arrow::Status::TypeError(
        "requested C++ scalar size does not match PointField datatype");
  }
  ARROW_ASSIGN_OR_RAISE(const auto field_width, FieldByteWidth(field));
  std::uint64_t field_end = 0;
  ARROW_RETURN_NOT_OK(CheckedAdd(field.offset, field_width,
                                 "field offset + field byte width", &field_end));
  if (field_end > point_stride_) {
    return arrow::Status::Invalid("PointField exceeds point_stride: ",
                                  field.name);
  }

  std::uint64_t field_offset = 0;
  std::uint64_t element_delta = 0;
  std::uint64_t element_offset = 0;
  ARROW_RETURN_NOT_OK(PointValueOffset(row, column, row_stride_, point_stride_,
                                      field.offset, &field_offset));
  ARROW_RETURN_NOT_OK(CheckedMultiply(element_index, datatype_size,
                                      "element index * datatype size",
                                      &element_delta));
  ARROW_RETURN_NOT_OK(CheckedAdd(field_offset, element_delta,
                                 "field offset + element offset",
                                 &element_offset));
  return CopyWireScalar(data_, element_offset, datatype_size, byte_order_,
                        output);
}

}  // namespace forge_msgs
