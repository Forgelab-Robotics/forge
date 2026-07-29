#include "detail.hpp"

#include <arrow/buffer.h>

#include <cmath>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace forge_msgs {

using namespace detail;

namespace {

arrow::Status ValidateFiniteValues(const std::string& name,
                                   const std::vector<double>& values) {
  for (double value : values) {
    if (!std::isfinite(value)) {
      return arrow::Status::Invalid(name, " values must be finite");
    }
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> StructRow(
    const std::shared_ptr<arrow::StructArray>& array, std::int64_t row) {
  if (row < 0 || row >= array->length()) {
    return arrow::Status::Invalid("struct row index is out of range");
  }
  if (array->IsNull(row)) {
    return arrow::Status::Invalid("struct values must not contain nulls");
  }
  std::vector<std::shared_ptr<arrow::Array>> columns;
  columns.reserve(array->num_fields());
  for (int i = 0; i < array->num_fields(); ++i) {
    columns.push_back(array->field(i)->Slice(row, 1));
  }
  return arrow::RecordBatch::Make(arrow::schema(array->struct_type()->fields()), 1,
                                  std::move(columns));
}

}  // namespace

namespace detail {

arrow::Result<std::shared_ptr<arrow::Array>> StructScalar(
    const arrow::RecordBatch& batch, bool valid) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  if (valid) {
    return arrow::StructArray::Make(batch.columns(), batch.schema()->fields());
  }
  ARROW_ASSIGN_OR_RAISE(auto null_bitmap, arrow::AllocateBitmap(1));
  null_bitmap->mutable_data()[0] = 0;
  return arrow::StructArray::Make(batch.columns(), batch.schema()->fields(), null_bitmap, 1);
}

arrow::Result<std::shared_ptr<arrow::Array>> StructList(
    const std::vector<std::shared_ptr<arrow::RecordBatch>>& batches,
    const std::vector<std::shared_ptr<arrow::Field>>& fields) {
  auto struct_type = arrow::struct_(fields);
  ARROW_ASSIGN_OR_RAISE(auto value_builder,
                        arrow::MakeBuilder(struct_type, arrow::default_memory_pool()));
  auto shared_value_builder = std::shared_ptr<arrow::ArrayBuilder>(std::move(value_builder));
  arrow::ListBuilder list_builder(arrow::default_memory_pool(), shared_value_builder);
  auto* struct_builder = static_cast<arrow::StructBuilder*>(list_builder.value_builder());

  ARROW_RETURN_NOT_OK(list_builder.Append());
  for (const auto& batch : batches) {
    ARROW_RETURN_NOT_OK(RequireOneRow(*batch));
    if (!batch->schema()->Equals(*arrow::schema(fields), false)) {
      return arrow::Status::Invalid("nested struct schema does not match expected schema");
    }

    ARROW_RETURN_NOT_OK(struct_builder->Append());
    for (std::size_t field_index = 0; field_index < fields.size(); ++field_index) {
      ARROW_ASSIGN_OR_RAISE(
          auto scalar, batch->column(static_cast<int>(field_index))->GetScalar(0));
      ARROW_RETURN_NOT_OK(
          struct_builder->field_builder(static_cast<int>(field_index))->AppendScalar(*scalar));
    }
  }
  return list_builder.Finish();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> ReadStruct(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array, ColumnAs<arrow::StructArray>(batch, name));
  if (array->length() != 1 || array->IsNull(0)) {
    return arrow::Status::Invalid(name, " must contain one non-null struct row");
  }
  return StructRow(array, 0);
}

arrow::Result<std::optional<std::shared_ptr<arrow::RecordBatch>>> ReadOptionalStruct(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array, ColumnAs<arrow::StructArray>(batch, name));
  if (array->length() != 1) {
    return arrow::Status::Invalid(name, " must contain one row");
  }
  if (array->IsNull(0)) {
    return std::optional<std::shared_ptr<arrow::RecordBatch>>{};
  }
  ARROW_ASSIGN_OR_RAISE(auto row, StructRow(array, 0));
  return std::optional<std::shared_ptr<arrow::RecordBatch>>{std::move(row)};
}

arrow::Result<std::vector<std::shared_ptr<arrow::RecordBatch>>> ReadStructList(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto list, ColumnAs<arrow::ListArray>(batch, name));
  if (list->length() != 1 || list->IsNull(0)) {
    return arrow::Status::Invalid(name, " must contain one non-null list row");
  }
  auto values = std::dynamic_pointer_cast<arrow::StructArray>(list->value_slice(0));
  if (!values) {
    return arrow::Status::Invalid(name, " values must be struct");
  }
  if (values->null_count() != 0) {
    return arrow::Status::Invalid(name, " values must not contain nulls");
  }

  std::vector<std::shared_ptr<arrow::RecordBatch>> rows;
  rows.reserve(static_cast<std::size_t>(values->length()));
  for (std::int64_t i = 0; i < values->length(); ++i) {
    ARROW_ASSIGN_OR_RAISE(auto row, StructRow(values, i));
    rows.push_back(std::move(row));
  }
  return rows;
}

}  // namespace detail

arrow::Status JointTrajectoryPoint::Validate() const {
  if (positions.empty()) {
    return arrow::Status::Invalid("positions must contain at least one value");
  }
  ARROW_RETURN_NOT_OK(ValidateFiniteValues("positions", positions));
  ARROW_RETURN_NOT_OK(ValidateLen("velocities", velocities, positions.size(), true));
  ARROW_RETURN_NOT_OK(ValidateLen("accelerations", accelerations, positions.size(), true));
  ARROW_RETURN_NOT_OK(ValidateLen("effort", effort, positions.size(), true));
  ARROW_RETURN_NOT_OK(ValidateFiniteValues("velocities", velocities));
  ARROW_RETURN_NOT_OK(ValidateFiniteValues("accelerations", accelerations));
  ARROW_RETURN_NOT_OK(ValidateFiniteValues("effort", effort));
  if (time_from_start_ns < 0) {
    return arrow::Status::Invalid("time_from_start_ns must be non-negative");
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> JointTrajectoryPoint::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto positions_array, F64List(positions));
  ARROW_ASSIGN_OR_RAISE(auto velocities_array, F64List(velocities));
  ARROW_ASSIGN_OR_RAISE(auto accelerations_array, F64List(accelerations));
  ARROW_ASSIGN_OR_RAISE(auto effort_array, F64List(effort));
  ARROW_ASSIGN_OR_RAISE(auto time_array, ScalarI64(time_from_start_ns));
  auto f64_list = ListType(arrow::float64());
  return MakeBatch({arrow::field("positions", f64_list, false),
                    arrow::field("velocities", f64_list, false),
                    arrow::field("accelerations", f64_list, false),
                    arrow::field("effort", f64_list, false),
                    arrow::field("time_from_start_ns", arrow::int64(), false)},
                   {positions_array, velocities_array, accelerations_array, effort_array,
                    time_array});
}

arrow::Result<JointTrajectoryPoint> JointTrajectoryPoint::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  JointTrajectoryPoint value;
  ARROW_ASSIGN_OR_RAISE(value.positions, ReadF64List(batch, "positions"));
  ARROW_ASSIGN_OR_RAISE(value.velocities, ReadF64List(batch, "velocities"));
  ARROW_ASSIGN_OR_RAISE(value.accelerations, ReadF64List(batch, "accelerations"));
  ARROW_ASSIGN_OR_RAISE(value.effort, ReadF64List(batch, "effort"));
  ARROW_ASSIGN_OR_RAISE(value.time_from_start_ns, ReadI64(batch, "time_from_start_ns"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status JointTrajectory::Validate() const {
  if (joint_names.empty()) {
    return arrow::Status::Invalid("joint_names must contain at least one joint");
  }
  for (const auto& name : joint_names) {
    ARROW_RETURN_NOT_OK(ValidateRequired("joint_names item", name));
  }
  ARROW_RETURN_NOT_OK(ValidateUnique("joint_names", joint_names));
  if (points.empty()) {
    return arrow::Status::Invalid("points must contain at least one trajectory point");
  }

  std::int64_t previous_time = -1;
  for (const auto& point : points) {
    ARROW_RETURN_NOT_OK(point.Validate());
    ARROW_RETURN_NOT_OK(ValidateLen("point positions", point.positions, joint_names.size()));
    ARROW_RETURN_NOT_OK(
        ValidateLen("point velocities", point.velocities, joint_names.size(), true));
    ARROW_RETURN_NOT_OK(
        ValidateLen("point accelerations", point.accelerations, joint_names.size(), true));
    ARROW_RETURN_NOT_OK(ValidateLen("point effort", point.effort, joint_names.size(), true));
    if (point.time_from_start_ns <= previous_time) {
      return arrow::Status::Invalid("time_from_start_ns values must be strictly increasing");
    }
    previous_time = point.time_from_start_ns;
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> JointTrajectory::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto joint_names_array, StringList(joint_names));

  std::vector<std::shared_ptr<arrow::RecordBatch>> point_batches;
  point_batches.reserve(points.size());
  for (const auto& point : points) {
    ARROW_ASSIGN_OR_RAISE(auto point_batch, point.ToRecordBatch());
    point_batches.push_back(std::move(point_batch));
  }
  const auto point_fields = point_batches.front()->schema()->fields();
  ARROW_ASSIGN_OR_RAISE(auto points_array, StructList(point_batches, point_fields));

  auto point_type = arrow::struct_(point_fields);
  return MakeBatch({arrow::field("joint_names", ListType(arrow::utf8()), false),
                    arrow::field("points", ListType(point_type), false)},
                   {joint_names_array, points_array});
}

arrow::Result<JointTrajectory> JointTrajectory::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  JointTrajectory value;
  ARROW_ASSIGN_OR_RAISE(value.joint_names, ReadStringList(batch, "joint_names"));
  ARROW_ASSIGN_OR_RAISE(auto point_batches, ReadStructList(batch, "points"));
  value.points.reserve(point_batches.size());
  for (const auto& point_batch : point_batches) {
    ARROW_ASSIGN_OR_RAISE(auto point, JointTrajectoryPoint::FromRecordBatch(*point_batch));
    value.points.push_back(std::move(point));
  }
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status JointTolerance::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateRequired("joint_name", joint_name));
  if (!position && !velocity && !acceleration) {
    return arrow::Status::Invalid(
        "at least one of position, velocity, or acceleration must be specified");
  }
  for (const auto& tolerance : {position, velocity, acceleration}) {
    if (tolerance && (!std::isfinite(*tolerance) || *tolerance < 0.0)) {
      return arrow::Status::Invalid("specified tolerances must be finite and non-negative");
    }
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> JointTolerance::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto name_array, ScalarString(joint_name));
  ARROW_ASSIGN_OR_RAISE(auto position_array, OptionalF64(position));
  ARROW_ASSIGN_OR_RAISE(auto velocity_array, OptionalF64(velocity));
  ARROW_ASSIGN_OR_RAISE(auto acceleration_array, OptionalF64(acceleration));
  return MakeBatch({arrow::field("joint_name", arrow::utf8(), false),
                    arrow::field("position", arrow::float64(), true),
                    arrow::field("velocity", arrow::float64(), true),
                    arrow::field("acceleration", arrow::float64(), true)},
                   {name_array, position_array, velocity_array, acceleration_array});
}

arrow::Result<JointTolerance> JointTolerance::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  JointTolerance value;
  ARROW_ASSIGN_OR_RAISE(value.joint_name, ReadString(batch, "joint_name"));
  ARROW_ASSIGN_OR_RAISE(value.position, ReadOptionalF64(batch, "position"));
  ARROW_ASSIGN_OR_RAISE(value.velocity, ReadOptionalF64(batch, "velocity"));
  ARROW_ASSIGN_OR_RAISE(value.acceleration, ReadOptionalF64(batch, "acceleration"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
