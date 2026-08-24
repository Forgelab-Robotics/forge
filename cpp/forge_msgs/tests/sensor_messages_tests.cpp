#include <arrow/api.h>
#include <arrow/buffer.h>

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <string>
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

template <typename T>
void StoreScalar(forge_msgs::Bytes& data, std::size_t offset, T value,
                 forge_msgs::ByteOrder byte_order) {
  std::array<std::uint8_t, sizeof(T)> bytes{};
  std::memcpy(bytes.data(), &value, sizeof(T));
  bool reverse = false;
  if constexpr (std::endian::native == std::endian::little) {
    reverse = byte_order == forge_msgs::ByteOrder::BigEndian;
  } else if constexpr (std::endian::native == std::endian::big) {
    reverse = byte_order == forge_msgs::ByteOrder::LittleEndian;
  }
  if (reverse) std::reverse(bytes.begin(), bytes.end());
  std::copy(bytes.begin(), bytes.end(), data.begin() + offset);
}

forge_msgs::PointCloudBuffer MakePointCloudBuffer(
    forge_msgs::ByteOrder byte_order = forge_msgs::ByteOrder::LittleEndian) {
  using forge_msgs::PointField;
  using forge_msgs::PointFieldDatatype;

  forge_msgs::PointCloudBuffer value;
  value.width = 2;
  value.height = 2;
  value.is_dense = true;
  value.byte_order = byte_order;
  value.point_stride = 16;
  value.row_stride = 35;
  value.fields = {
      PointField{"ring", 13, PointFieldDatatype::UInt16, 1},
      PointField{"z", 9, PointFieldDatatype::Float32, 1},
      PointField{"x", 1, PointFieldDatatype::Float32, 1},
      PointField{"y", 5, PointFieldDatatype::Float32, 1},
  };
  value.data.assign(70, 0xa5);

  for (std::uint32_t row = 0; row < value.height; ++row) {
    for (std::uint32_t column = 0; column < value.width; ++column) {
      const std::uint32_t index = row * value.width + column;
      const std::size_t point =
          static_cast<std::size_t>(row * value.row_stride +
                                   column * value.point_stride);
      StoreScalar(value.data, point + 1, static_cast<float>(index + 1),
                  byte_order);
      StoreScalar(value.data, point + 5, static_cast<float>(index + 11),
                  byte_order);
      StoreScalar(value.data, point + 9, static_cast<float>(index + 21),
                  byte_order);
      StoreScalar(value.data, point + 13,
                  static_cast<std::uint16_t>(index + 100), byte_order);
    }
  }
  return value;
}

forge_msgs::PointCloudBuffer MakeFixedArrayPointCloudBuffer() {
  using forge_msgs::ByteOrder;
  using forge_msgs::PointField;
  using forge_msgs::PointFieldDatatype;

  forge_msgs::PointCloudBuffer value;
  value.width = 1;
  value.height = 1;
  value.is_dense = true;
  value.byte_order = ByteOrder::BigEndian;
  value.point_stride = 25;
  value.row_stride = 25;
  value.fields = {
      PointField{"returns", 13, PointFieldDatatype::UInt32, 3},
      PointField{"z", 9, PointFieldDatatype::Float32, 1},
      PointField{"x", 1, PointFieldDatatype::Float32, 1},
      PointField{"y", 5, PointFieldDatatype::Float32, 1},
  };
  value.data.assign(25, 0xa5);
  StoreScalar(value.data, 1, 1.0f, value.byte_order);
  StoreScalar(value.data, 5, 2.0f, value.byte_order);
  StoreScalar(value.data, 9, 3.0f, value.byte_order);
  StoreScalar(value.data, 13, std::uint32_t{0x01020304}, value.byte_order);
  StoreScalar(value.data, 17, std::uint32_t{0x11223344}, value.byte_order);
  StoreScalar(value.data, 21, std::uint32_t{0xa1b2c3d4}, value.byte_order);
  return value;
}

std::shared_ptr<arrow::Schema> PointCloudBufferSchema() {
  auto point_field_type = arrow::struct_({
      arrow::field("name", arrow::utf8(), false),
      arrow::field("offset", arrow::uint32(), false),
      arrow::field("datatype", arrow::utf8(), false),
      arrow::field("count", arrow::uint32(), false),
  });
  auto point_fields =
      arrow::list(arrow::field("item", point_field_type, true));
  return arrow::schema({
      arrow::field("width", arrow::uint32(), false),
      arrow::field("height", arrow::uint32(), false),
      arrow::field("is_dense", arrow::boolean(), false),
      arrow::field("byte_order", arrow::utf8(), false),
      arrow::field("point_stride", arrow::uint32(), false),
      arrow::field("row_stride", arrow::uint64(), false),
      arrow::field("fields", point_fields, false),
      arrow::field("data", arrow::large_binary(), false),
  });
}

arrow::Result<std::shared_ptr<arrow::Array>> PointFieldListArray(
    const std::vector<forge_msgs::PointField>& fields) {
  auto struct_type = arrow::struct_({
      arrow::field("name", arrow::utf8(), false),
      arrow::field("offset", arrow::uint32(), false),
      arrow::field("datatype", arrow::utf8(), false),
      arrow::field("count", arrow::uint32(), false),
  });
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
    ARROW_RETURN_NOT_OK(
        static_cast<arrow::StringBuilder*>(struct_builder->field_builder(0))
            ->Append(field.name));
    ARROW_RETURN_NOT_OK(
        static_cast<arrow::UInt32Builder*>(struct_builder->field_builder(1))
            ->Append(field.offset));
    ARROW_RETURN_NOT_OK(
        static_cast<arrow::StringBuilder*>(struct_builder->field_builder(2))
            ->Append(forge_msgs::ToString(field.datatype)));
    ARROW_RETURN_NOT_OK(
        static_cast<arrow::UInt32Builder*>(struct_builder->field_builder(3))
            ->Append(field.count));
  }
  return list_builder.Finish();
}

std::shared_ptr<arrow::Schema> ImuSchema() {
  auto orientation = arrow::struct_({
      arrow::field("qx", arrow::float64(), false),
      arrow::field("qy", arrow::float64(), false),
      arrow::field("qz", arrow::float64(), false),
      arrow::field("qw", arrow::float64(), false),
  });
  auto vector3 = arrow::struct_({
      arrow::field("x", arrow::float64(), false),
      arrow::field("y", arrow::float64(), false),
      arrow::field("z", arrow::float64(), false),
  });
  auto covariance =
      arrow::list(arrow::field("item", arrow::float64(), true));
  return arrow::schema({
      arrow::field("orientation", orientation, true),
      arrow::field("angular_velocity", vector3, false),
      arrow::field("linear_acceleration", vector3, false),
      arrow::field("orientation_covariance", covariance, false),
      arrow::field("angular_velocity_covariance", covariance, false),
      arrow::field("linear_acceleration_covariance", covariance, false),
      arrow::field("temperature_celsius", arrow::float64(), true),
  });
}

std::shared_ptr<arrow::RecordBatch> WithReorderedColumnsAndExtra(
    const arrow::RecordBatch& batch) {
  std::vector<std::shared_ptr<arrow::Field>> fields;
  std::vector<std::shared_ptr<arrow::Array>> columns;
  for (int index = batch.num_columns() - 1; index >= 0; --index) {
    fields.push_back(batch.schema()->field(index));
    columns.push_back(batch.column(index));
  }
  arrow::StringBuilder builder;
  if (!builder.Append("ignored").ok()) return nullptr;
  auto extra = builder.Finish();
  if (!extra.ok()) return nullptr;
  fields.push_back(arrow::field("extra", arrow::utf8(), true));
  columns.push_back(*extra);
  return arrow::RecordBatch::Make(arrow::schema(std::move(fields)), 1,
                                  std::move(columns));
}

std::shared_ptr<arrow::RecordBatch> WithoutColumn(
    const arrow::RecordBatch& batch, const std::string& name) {
  std::vector<std::shared_ptr<arrow::Field>> fields;
  std::vector<std::shared_ptr<arrow::Array>> columns;
  for (int index = 0; index < batch.num_columns(); ++index) {
    if (batch.schema()->field(index)->name() == name) continue;
    fields.push_back(batch.schema()->field(index));
    columns.push_back(batch.column(index));
  }
  return arrow::RecordBatch::Make(arrow::schema(std::move(fields)), 1,
                                  std::move(columns));
}

std::shared_ptr<arrow::RecordBatch> WithDuplicateColumn(
    const arrow::RecordBatch& batch, const std::string& name) {
  auto fields = batch.schema()->fields();
  auto columns = batch.columns();
  const int index = batch.schema()->GetFieldIndex(name);
  fields.push_back(batch.schema()->field(index));
  columns.push_back(batch.column(index));
  return arrow::RecordBatch::Make(arrow::schema(std::move(fields)), 1,
                                  std::move(columns));
}

std::shared_ptr<arrow::RecordBatch> ReplaceColumn(
    const arrow::RecordBatch& batch, const std::string& name,
    std::shared_ptr<arrow::Field> field,
    std::shared_ptr<arrow::Array> column) {
  auto fields = batch.schema()->fields();
  auto columns = batch.columns();
  const int index = batch.schema()->GetFieldIndex(name);
  fields[static_cast<std::size_t>(index)] = std::move(field);
  columns[static_cast<std::size_t>(index)] = std::move(column);
  return arrow::RecordBatch::Make(arrow::schema(std::move(fields)), 1,
                                  std::move(columns));
}

void TestPointCloudBufferRoundTripAndView() {
  using namespace forge_msgs;

  auto value = MakePointCloudBuffer();
  Check(value.Validate().ok(), "PointCloudBuffer accepts padded unaligned layout");

  auto snapshot_source = value;
  auto snapshot =
      PointCloudBufferView::FromPointCloudBuffer(snapshot_source);
  StoreScalar(snapshot_source.data, 1, 99.0f, ByteOrder::LittleEndian);
  auto snapshot_x = snapshot.ok()
                        ? snapshot->ReadScalar<float>(0, 0, "x")
                        : arrow::Result<float>(snapshot.status());
  Check(snapshot_x.ok() && *snapshot_x == 1.0f,
        "PointCloudBufferView owns an immutable by-value snapshot");

  auto batch = value.ToRecordBatch();
  Check(batch.ok(), "PointCloudBuffer ToRecordBatch");
  if (!batch.ok()) return;

  Check((*batch)->schema()->Equals(*PointCloudBufferSchema(), false),
        "PointCloudBuffer exact canonical Arrow schema");
  Check((*batch)->num_rows() == 1,
        "PointCloudBuffer emits exactly one row");
  auto byte_order = std::dynamic_pointer_cast<arrow::StringArray>(
      (*batch)->GetColumnByName("byte_order"));
  Check(byte_order && byte_order->GetString(0) == "little_endian",
        "PointCloudBuffer canonical writer emits little_endian");

  auto field_list = std::dynamic_pointer_cast<arrow::ListArray>(
      (*batch)->GetColumnByName("fields"));
  auto field_values = field_list
                          ? std::dynamic_pointer_cast<arrow::StructArray>(
                                field_list->value_slice(0))
                          : nullptr;
  auto names = field_values
                   ? std::dynamic_pointer_cast<arrow::StringArray>(
                         field_values->field(0))
                   : nullptr;
  Check(names && names->length() == 4 && names->GetString(0) == "x" &&
            names->GetString(1) == "y" && names->GetString(2) == "z" &&
            names->GetString(3) == "ring",
        "PointCloudBuffer writer sorts descriptors by offset then name");
  Check(field_values && field_values->null_count() == 0,
        "PointCloudBuffer descriptor structs are non-null");
  if (field_values) {
    for (int index = 0; index < field_values->num_fields(); ++index) {
      Check(field_values->field(index)->null_count() == 0,
            "PointCloudBuffer descriptor children are non-null");
    }
  }

  auto round_trip = PointCloudBuffer::FromRecordBatch(**batch);
  Check(round_trip.ok(), "PointCloudBuffer FromRecordBatch");
  if (round_trip.ok()) {
    Check(round_trip->byte_order == ByteOrder::LittleEndian,
          "PointCloudBuffer reads canonical byte order");
    Check(round_trip->fields.size() == 4 &&
              round_trip->fields.front().name == "x",
          "PointCloudBuffer reads canonical descriptor order");
  }

  auto retained_view = [&]() -> arrow::Result<PointCloudBufferView> {
    std::shared_ptr<const arrow::RecordBatch> owner = *batch;
    return PointCloudBufferView::FromRecordBatch(std::move(owner));
  }();
  (*batch).reset();
  Check(retained_view.ok(), "PointCloudBufferView retains Arrow storage");
  if (!retained_view.ok()) return;

  Check(retained_view->width() == 2 && retained_view->height() == 2 &&
            retained_view->point_stride() == 16 &&
            retained_view->row_stride() == 35,
        "PointCloudBufferView exposes layout metadata");
  Check(retained_view->FindField("ring") != nullptr &&
            retained_view->FindField("missing") == nullptr,
        "PointCloudBufferView descriptor lookup");
  auto point = retained_view->PointBytes(1, 1);
  Check(point.ok() && point->size() == 16,
        "PointCloudBufferView exposes one point record");
  auto x = retained_view->ReadScalar<float>(1, 1, "x");
  auto y = retained_view->ReadScalar<float>(1, 1, "y");
  auto z = retained_view->ReadScalarAt<float>(3, "z");
  auto ring = retained_view->ReadScalar<std::uint16_t>(1, 1, "ring");
  Check(x.ok() && *x == 4.0f && y.ok() && *y == 14.0f && z.ok() &&
            *z == 24.0f && ring.ok() && *ring == 103,
        "PointCloudBufferView reads unaligned padded scalar fields");
  Check(!retained_view->ReadScalar<double>(1, 1, "x").ok(),
        "PointCloudBufferView rejects mismatched requested scalar type");
  Check(!retained_view->ReadScalar<float>(2, 0, "x").ok(),
        "PointCloudBufferView rejects out-of-range coordinates");
}

void TestPointCloudBufferArrayElements() {
  using namespace forge_msgs;

  auto value = MakeFixedArrayPointCloudBuffer();
  Check(value.Validate().ok(),
        "PointCloudBuffer accepts unaligned big-endian fixed array");
  auto view = PointCloudBufferView::FromPointCloudBuffer(value);
  Check(view.ok(), "PointCloudBufferView owns fixed-array buffer");
  if (!view.ok()) return;

  const auto* returns = view->FindField("returns");
  Check(returns != nullptr,
        "PointCloudBufferView finds fixed-array descriptor");
  if (returns == nullptr) return;
  auto first = view->ReadElement<std::uint32_t>(0, 0, "returns", 0);
  auto second = view->ReadElement<std::uint32_t>(0, 0, *returns, 1);
  auto third = view->ReadElementAt<std::uint32_t>(0, "returns", 2);
  Check(first.ok() && *first == 0x01020304U && second.ok() &&
            *second == 0x11223344U && third.ok() && *third == 0xa1b2c3d4U,
        "PointCloudBufferView reads unaligned big-endian array elements");
  Check(!view->ReadScalar<std::uint32_t>(0, 0, "returns").ok(),
        "PointCloudBufferView scalar read rejects fixed array");
  Check(!view->ReadElement<std::uint32_t>(0, 0, "returns", 3).ok(),
        "PointCloudBufferView rejects out-of-range array element");
  Check(!view->ReadElement<std::uint16_t>(0, 0, "returns", 0).ok(),
        "PointCloudBufferView rejects mismatched array element type");

  auto canonical = value.ToRecordBatch();
  Check(canonical.ok(),
        "PointCloudBuffer canonicalizes big-endian fixed-array data");
  if (canonical.ok()) {
    auto canonical_view = PointCloudBufferView::FromRecordBatch(**canonical);
    auto canonical_third =
        canonical_view.ok()
            ? canonical_view->ReadElement<std::uint32_t>(0, 0, "returns", 2)
            : arrow::Result<std::uint32_t>(canonical_view.status());
    Check(canonical_view.ok() &&
              canonical_view->byte_order() == ByteOrder::LittleEndian &&
              canonical_third.ok() && *canonical_third == 0xa1b2c3d4U,
          "fixed-array endian canonicalization preserves elements");
  }
}

void TestPointCloudBufferEndianAndValidation() {
  using namespace forge_msgs;

  auto big_endian = MakePointCloudBuffer(ByteOrder::BigEndian);
  Check(big_endian.Validate().ok(),
        "PointCloudBuffer validates big-endian input");
  auto big_view = PointCloudBufferView::FromPointCloudBuffer(big_endian);
  auto big_x = big_view.ok()
                   ? big_view->ReadScalar<float>(1, 0, "x")
                   : arrow::Result<float>(big_view.status());
  Check(big_x.ok() && *big_x == 3.0f,
        "PointCloudBufferView honors big-endian fields");

  auto canonical = big_endian.ToRecordBatch();
  Check(canonical.ok(), "PointCloudBuffer canonicalizes big-endian data");
  if (canonical.ok()) {
    auto decoded = PointCloudBufferView::FromRecordBatch(**canonical);
    auto x = decoded.ok() ? decoded->ReadScalar<float>(1, 0, "x")
                          : arrow::Result<float>(decoded.status());
    Check(decoded.ok() && decoded->byte_order() == ByteOrder::LittleEndian &&
              x.ok() && *x == 3.0f,
          "PointCloudBuffer endian canonicalization preserves values");
  }

  auto empty = MakePointCloudBuffer();
  empty.width = 0;
  empty.height = 1;
  empty.row_stride = 0;
  empty.data.clear();
  Check(empty.Validate().ok(),
        "PointCloudBuffer accepts canonical empty unorganized shape");
  auto invalid_empty = empty;
  invalid_empty.height = 2;
  Check(!invalid_empty.Validate().ok(),
        "zero-width PointCloudBuffer requires height one");
  invalid_empty = empty;
  invalid_empty.row_stride = 1;
  invalid_empty.data = {0};
  Check(!invalid_empty.Validate().ok(),
        "zero-width PointCloudBuffer requires zero row_stride");
  invalid_empty = empty;
  invalid_empty.data = {0};
  Check(!invalid_empty.Validate().ok(),
        "zero-width PointCloudBuffer requires empty data");

  auto invalid = MakePointCloudBuffer();
  invalid.height = 0;
  Check(!invalid.Validate().ok(), "PointCloudBuffer rejects zero height");
  invalid = MakePointCloudBuffer();
  invalid.point_stride = 0;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects zero point_stride");
  invalid = MakePointCloudBuffer();
  invalid.row_stride = 31;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects short row_stride");
  invalid = MakePointCloudBuffer();
  invalid.data.pop_back();
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects incorrect data length");
  invalid = MakePointCloudBuffer();
  invalid.row_stride = std::numeric_limits<std::uint64_t>::max();
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects row_stride multiplication overflow");
  invalid = MakePointCloudBuffer();
  invalid.fields[0].name.clear();
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects empty descriptor name");
  const std::vector<std::string> invalid_utf8_names = {
      std::string("\x80", 1),
      std::string("\xc0\xaf", 2),
      std::string("\xe2\x82", 2),
      std::string("\xed\xa0\x80", 3),
      std::string("\xf4\x90\x80\x80", 4),
  };
  for (std::size_t index = 0; index < invalid_utf8_names.size(); ++index) {
    invalid = MakePointCloudBuffer();
    invalid.fields[0].name = invalid_utf8_names[index];
    const auto status = invalid.Validate();
    Check(!status.ok() && status.ToString().find("UTF-8") != std::string::npos,
          "PointCloudBuffer rejects invalid UTF-8 descriptor name " +
              std::to_string(index));
    Check(!invalid.ToRecordBatch().ok(),
          "PointCloudBuffer refuses to serialize invalid UTF-8 descriptor name " +
              std::to_string(index));
  }
  invalid = MakePointCloudBuffer();
  invalid.fields[0].name = "温度";
  Check(invalid.Validate().ok(),
        "PointCloudBuffer accepts valid multibyte UTF-8 descriptor name");
  invalid = MakePointCloudBuffer();
  invalid.fields[0].name = "x";
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects duplicate descriptor name");
  invalid = MakePointCloudBuffer();
  invalid.fields[0].count = 0;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects zero descriptor count");
  invalid = MakePointCloudBuffer();
  invalid.fields[0].datatype = static_cast<PointFieldDatatype>(999);
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects unknown descriptor datatype");
  invalid = MakePointCloudBuffer();
  invalid.fields[0].offset = 12;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects overlapping descriptor ranges");
  invalid = MakePointCloudBuffer();
  invalid.fields[0].offset = 15;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects descriptor beyond point_stride");
  invalid = MakePointCloudBuffer();
  invalid.fields.erase(invalid.fields.begin() + 2);
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer requires x, y, and z descriptors");
  invalid = MakePointCloudBuffer();
  invalid.fields[2].count = 2;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer requires scalar XYZ descriptors");
  invalid = MakePointCloudBuffer();
  invalid.fields[2].datatype = PointFieldDatatype::UInt32;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer requires floating XYZ descriptors");
  invalid = MakePointCloudBuffer();
  invalid.fields[2].datatype = PointFieldDatatype::Float64;
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer requires matching XYZ datatypes");
  invalid = MakePointCloudBuffer();
  StoreScalar(invalid.data, 1, std::numeric_limits<float>::quiet_NaN(),
              ByteOrder::LittleEndian);
  Check(!invalid.Validate().ok(),
        "dense PointCloudBuffer rejects non-finite XYZ");
  invalid.is_dense = false;
  Check(invalid.Validate().ok(),
        "non-dense PointCloudBuffer permits non-finite XYZ");
  invalid = MakePointCloudBuffer();
  invalid.byte_order = static_cast<ByteOrder>(999);
  Check(!invalid.Validate().ok(),
        "PointCloudBuffer rejects invalid byte order enum");
}

void TestPointCloudBufferReaderContracts() {
  using namespace forge_msgs;

  auto canonical = MakePointCloudBuffer().ToRecordBatch();
  Check(canonical.ok(), "PointCloudBuffer reader contract source batch");
  if (!canonical.ok()) return;

  auto flexible = WithReorderedColumnsAndExtra(**canonical);
  Check(flexible && PointCloudBuffer::FromRecordBatch(*flexible).ok(),
        "PointCloudBuffer reader accepts reordered fields and extras");
  Check(!PointCloudBuffer::FromRecordBatch(
             *WithoutColumn(**canonical, "point_stride"))
             .ok(),
        "PointCloudBuffer reader rejects missing required field");
  Check(!PointCloudBuffer::FromRecordBatch(
             *WithDuplicateColumn(**canonical, "width"))
             .ok(),
        "PointCloudBuffer reader rejects duplicate required field");

  arrow::Int32Builder wrong_builder;
  Check(wrong_builder.Append(2).ok(),
        "PointCloudBuffer wrong-type array append");
  auto wrong_array = wrong_builder.Finish();
  if (wrong_array.ok()) {
    auto wrong = ReplaceColumn(
        **canonical, "width", arrow::field("width", arrow::int32(), false),
        *wrong_array);
    Check(!PointCloudBuffer::FromRecordBatch(*wrong).ok(),
          "PointCloudBuffer reader rejects wrong physical type");
  }

  arrow::UInt32Builder null_builder;
  Check(null_builder.AppendNull().ok(),
        "PointCloudBuffer null scalar append");
  auto null_array = null_builder.Finish();
  if (null_array.ok()) {
    auto null_width = ReplaceColumn(
        **canonical, "width", arrow::field("width", arrow::uint32(), true),
        *null_array);
    Check(!PointCloudBuffer::FromRecordBatch(*null_width).ok(),
          "PointCloudBuffer reader rejects null required scalar");
  }

  arrow::ListBuilder wrong_fields_builder(
      arrow::default_memory_pool(),
      std::make_shared<arrow::StringBuilder>());
  Check(wrong_fields_builder.Append().ok(),
        "PointCloudBuffer wrong fields list append");
  auto* strings = static_cast<arrow::StringBuilder*>(
      wrong_fields_builder.value_builder());
  Check(strings->Append("not-a-struct").ok(),
        "PointCloudBuffer wrong fields item append");
  auto wrong_fields_array = wrong_fields_builder.Finish();
  if (wrong_fields_array.ok()) {
    auto wrong_fields = ReplaceColumn(
        **canonical, "fields",
        arrow::field("fields", arrow::list(arrow::utf8()), false),
        *wrong_fields_array);
    Check(!PointCloudBuffer::FromRecordBatch(*wrong_fields).ok(),
          "PointCloudBuffer reader rejects wrong descriptor physical type");
  }

  auto invalid_utf8_fields = PointFieldListArray(
      {{"x", 1, PointFieldDatatype::Float32, 1},
       {"y", 5, PointFieldDatatype::Float32, 1},
       {"z", 9, PointFieldDatatype::Float32, 1},
       {std::string("\xed\xa0\x80", 3), 13, PointFieldDatatype::UInt16, 1}});
  Check(invalid_utf8_fields.ok(),
        "construct Arrow descriptor with invalid UTF-8 bytes");
  if (invalid_utf8_fields.ok()) {
    auto malformed = ReplaceColumn(
        **canonical, "fields", PointCloudBufferSchema()->GetFieldByName("fields"),
        *invalid_utf8_fields);
    const auto result = PointCloudBuffer::FromRecordBatch(*malformed);
    Check(!result.ok() &&
              result.status().ToString().find("UTF-8") != std::string::npos,
          "PointCloudBuffer reader rejects invalid UTF-8 descriptor name");
    std::shared_ptr<const arrow::RecordBatch> malformed_owner = malformed;
    const auto view_result = PointCloudBufferView::FromRecordBatch(
        std::move(malformed_owner));
    Check(!view_result.ok() &&
              view_result.status().ToString().find("UTF-8") !=
                  std::string::npos,
          "PointCloudBufferView reader rejects invalid UTF-8 descriptor name");
  }
}

forge_msgs::Imu MakeImu() {
  forge_msgs::Imu value;
  value.orientation = forge_msgs::ImuOrientation{0.0, 0.0, 0.0, 2.0};
  value.angular_velocity = {0.1, -0.2, 0.3};
  value.linear_acceleration = {1.0, 2.0, 9.81};
  value.orientation_covariance = {1.0, 0.0, 0.0, 0.0, 2.0,
                                  0.0, 0.0, 0.0, 3.0};
  value.angular_velocity_covariance = {};
  value.linear_acceleration_covariance = {4.0, 0.0, 0.0, 0.0, 5.0,
                                          0.0, 0.0, 0.0, 6.0};
  value.temperature_celsius = 24.5;
  return value;
}

void TestImuRoundTripAndSchema() {
  using namespace forge_msgs;

  auto value = MakeImu();
  Check(value.Validate().ok(), "Imu validates canonical value");
  auto batch = value.ToRecordBatch();
  Check(batch.ok(), "Imu ToRecordBatch");
  if (!batch.ok()) return;
  Check((*batch)->schema()->Equals(*ImuSchema(), false),
        "Imu exact canonical Arrow schema and nullability");
  Check((*batch)->num_rows() == 1, "Imu emits exactly one row");

  auto round_trip = Imu::FromRecordBatch(**batch);
  Check(round_trip.ok(), "Imu FromRecordBatch");
  Check(round_trip.ok() && round_trip->orientation &&
            round_trip->orientation->qw == 2.0,
        "Imu does not normalize quaternion values");
  Check(round_trip.ok() && round_trip->temperature_celsius == 24.5,
        "Imu preserves optional temperature");

  Imu unavailable;
  unavailable.angular_velocity = {0.0, 0.0, 0.0};
  unavailable.linear_acceleration = {0.0, 0.0, 0.0};
  auto unavailable_batch = unavailable.ToRecordBatch();
  Check(unavailable_batch.ok(), "Imu writes unavailable optional values");
  if (unavailable_batch.ok()) {
    Check((*unavailable_batch)->GetColumnByName("orientation")->IsNull(0),
          "Imu emits null unavailable orientation");
    Check((*unavailable_batch)
              ->GetColumnByName("temperature_celsius")
              ->IsNull(0),
          "Imu emits null unavailable temperature");
    auto back = Imu::FromRecordBatch(**unavailable_batch);
    Check(back.ok() && !back->orientation && !back->temperature_celsius,
          "Imu reads null optional values");
  }
}

void TestImuValidation() {
  using namespace forge_msgs;

  auto invalid = MakeImu();
  invalid.orientation = ImuOrientation{0.0, 0.0, 0.0, 0.0};
  Check(!invalid.Validate().ok(), "Imu rejects zero quaternion");
  invalid = MakeImu();
  invalid.orientation->qx = std::numeric_limits<double>::infinity();
  Check(!invalid.Validate().ok(), "Imu rejects non-finite quaternion");
  invalid = MakeImu();
  invalid.angular_velocity.x = std::numeric_limits<double>::quiet_NaN();
  Check(!invalid.Validate().ok(), "Imu rejects non-finite gyroscope value");
  invalid = MakeImu();
  invalid.linear_acceleration.z =
      std::numeric_limits<double>::quiet_NaN();
  Check(!invalid.Validate().ok(),
        "Imu rejects non-finite acceleration value");
  invalid = MakeImu();
  invalid.orientation_covariance.pop_back();
  Check(!invalid.Validate().ok(), "Imu rejects covariance length other than 9");
  invalid = MakeImu();
  invalid.orientation_covariance[1] =
      std::numeric_limits<double>::quiet_NaN();
  Check(!invalid.Validate().ok(), "Imu rejects non-finite covariance");
  invalid = MakeImu();
  invalid.orientation_covariance[4] = -1.0;
  Check(!invalid.Validate().ok(), "Imu rejects negative covariance diagonal");
  invalid = MakeImu();
  invalid.orientation.reset();
  Check(!invalid.Validate().ok(),
        "Imu requires empty orientation covariance without orientation");
  invalid = MakeImu();
  invalid.temperature_celsius = std::numeric_limits<double>::infinity();
  Check(!invalid.Validate().ok(), "Imu rejects non-finite temperature");
}

void TestImuReaderContracts() {
  using namespace forge_msgs;

  auto canonical = MakeImu().ToRecordBatch();
  Check(canonical.ok(), "Imu reader contract source batch");
  if (!canonical.ok()) return;

  auto flexible = WithReorderedColumnsAndExtra(**canonical);
  Check(flexible && Imu::FromRecordBatch(*flexible).ok(),
        "Imu reader accepts reordered fields and extras");
  Check(!Imu::FromRecordBatch(
             *WithoutColumn(**canonical, "temperature_celsius"))
             .ok(),
        "Imu reader rejects missing nullable field");
  Check(!Imu::FromRecordBatch(
             *WithDuplicateColumn(**canonical, "angular_velocity"))
             .ok(),
        "Imu reader rejects duplicate required field");

  arrow::FloatBuilder wrong_builder;
  Check(wrong_builder.Append(24.5f).ok(), "Imu wrong-type array append");
  auto wrong_array = wrong_builder.Finish();
  if (wrong_array.ok()) {
    auto wrong = ReplaceColumn(
        **canonical, "temperature_celsius",
        arrow::field("temperature_celsius", arrow::float32(), true),
        *wrong_array);
    Check(!Imu::FromRecordBatch(*wrong).ok(),
          "Imu reader rejects wrong physical type");
  }

  auto angular = std::dynamic_pointer_cast<arrow::StructArray>(
      (*canonical)->GetColumnByName("angular_velocity"));
  if (angular) {
    auto bitmap = arrow::AllocateBitmap(1);
    Check(bitmap.ok(), "Imu null struct bitmap allocation");
    if (bitmap.ok()) {
      (*bitmap)->mutable_data()[0] = 0;
      auto null_struct = arrow::StructArray::Make(
          {angular->field(0), angular->field(1), angular->field(2)},
          angular->struct_type()->fields(), *bitmap, 1);
      Check(null_struct.ok(), "Imu null struct construction");
      if (null_struct.ok()) {
        auto malformed = ReplaceColumn(
            **canonical, "angular_velocity",
            arrow::field("angular_velocity", angular->type(), false),
            *null_struct);
        Check(!Imu::FromRecordBatch(*malformed).ok(),
              "Imu reader rejects null required struct");
      }
    }

    arrow::DoubleBuilder null_child_builder;
    Check(null_child_builder.AppendNull().ok(),
          "Imu null child construction");
    auto null_child = null_child_builder.Finish();
    if (null_child.ok()) {
      auto null_child_struct = arrow::StructArray::Make(
          {*null_child, angular->field(1), angular->field(2)},
          angular->struct_type()->fields());
      Check(null_child_struct.ok(), "Imu struct with null child construction");
      if (null_child_struct.ok()) {
        auto malformed = ReplaceColumn(
            **canonical, "angular_velocity",
            arrow::field("angular_velocity", angular->type(), false),
            *null_child_struct);
        Check(!Imu::FromRecordBatch(*malformed).ok(),
              "Imu reader rejects null required struct child");
      }
    }
  }

  std::vector<std::shared_ptr<arrow::Array>> empty_columns;
  for (const auto& column : (*canonical)->columns()) {
    empty_columns.push_back(column->Slice(0, 0));
  }
  auto empty = arrow::RecordBatch::Make((*canonical)->schema(), 0,
                                        std::move(empty_columns));
  Check(!Imu::FromRecordBatch(*empty).ok(),
        "Imu reader rejects non-single-row batch");
}

}  // namespace

int main() {
  using namespace forge_msgs;

  Check(ToString(ByteOrder::LittleEndian) == "little_endian" &&
            ByteOrderFromString("big_endian").ok() &&
            !ByteOrderFromString("native").ok(),
        "ByteOrder string contract");
  Check(ToString(PointFieldDatatype::UInt64) == "uint64" &&
            PointFieldDatatypeFromString("float64").ok() &&
            !PointFieldDatatypeFromString("float16").ok(),
        "PointFieldDatatype closed string contract");

  TestPointCloudBufferRoundTripAndView();
  TestPointCloudBufferArrayElements();
  TestPointCloudBufferEndianAndValidation();
  TestPointCloudBufferReaderContracts();
  TestImuRoundTripAndSchema();
  TestImuValidation();
  TestImuReaderContracts();

  if (failures != 0) {
    std::cerr << failures << " failure(s)\n";
    return 1;
  }
  return 0;
}
