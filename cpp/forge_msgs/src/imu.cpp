#include "detail.hpp"

#include <cmath>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace forge_msgs {

using namespace detail;

namespace {

std::vector<std::shared_ptr<arrow::Field>> OrientationFields() {
  return {arrow::field("qx", arrow::float64(), false),
          arrow::field("qy", arrow::float64(), false),
          arrow::field("qz", arrow::float64(), false),
          arrow::field("qw", arrow::float64(), false)};
}

std::vector<std::shared_ptr<arrow::Field>> Vector3Fields() {
  return {arrow::field("x", arrow::float64(), false),
          arrow::field("y", arrow::float64(), false),
          arrow::field("z", arrow::float64(), false)};
}

arrow::Status ValidateFiniteVector(const std::string& name,
                                   const ImuVector3& value) {
  if (!std::isfinite(value.x) || !std::isfinite(value.y) ||
      !std::isfinite(value.z)) {
    return arrow::Status::Invalid(name, " components must be finite");
  }
  return arrow::Status::OK();
}

arrow::Status ValidateCovariance(const std::string& name,
                                 const std::vector<double>& values) {
  if (!values.empty() && values.size() != 9) {
    return arrow::Status::Invalid(name,
                                  " must be empty or contain exactly 9 values");
  }
  for (double value : values) {
    if (!std::isfinite(value)) {
      return arrow::Status::Invalid(name, " values must be finite");
    }
  }
  if (!values.empty() &&
      (values[0] < 0.0 || values[4] < 0.0 || values[8] < 0.0)) {
    return arrow::Status::Invalid(name,
                                  " diagonal values must be non-negative");
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::Array>> OrientationArray(
    const std::optional<ImuOrientation>& orientation) {
  const ImuOrientation stored = orientation.value_or(ImuOrientation{});
  ARROW_ASSIGN_OR_RAISE(auto qx, ScalarF64(stored.qx));
  ARROW_ASSIGN_OR_RAISE(auto qy, ScalarF64(stored.qy));
  ARROW_ASSIGN_OR_RAISE(auto qz, ScalarF64(stored.qz));
  ARROW_ASSIGN_OR_RAISE(auto qw, ScalarF64(stored.qw));
  ARROW_ASSIGN_OR_RAISE(
      auto batch,
      MakeBatch(OrientationFields(), {qx, qy, qz, qw}));
  return StructScalar(*batch, orientation.has_value());
}

arrow::Result<std::shared_ptr<arrow::Array>> Vector3Array(
    const ImuVector3& value) {
  ARROW_ASSIGN_OR_RAISE(auto x, ScalarF64(value.x));
  ARROW_ASSIGN_OR_RAISE(auto y, ScalarF64(value.y));
  ARROW_ASSIGN_OR_RAISE(auto z, ScalarF64(value.z));
  ARROW_ASSIGN_OR_RAISE(auto batch, MakeBatch(Vector3Fields(), {x, y, z}));
  return StructScalar(*batch);
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
arrow::Result<std::shared_ptr<ArrayType>> UniqueArray(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(const int index, UniqueColumnIndex(batch, name));
  auto array = std::dynamic_pointer_cast<ArrayType>(batch.column(index));
  if (!array) {
    return arrow::Status::Invalid(name, " column has unexpected physical type");
  }
  if (array->length() != 1) {
    return arrow::Status::Invalid(name, " column must contain one row");
  }
  return array;
}

arrow::Status ValidateStructType(
    const std::shared_ptr<arrow::StructArray>& array,
    const std::vector<std::shared_ptr<arrow::Field>>& expected,
    const std::string& name) {
  const auto type = array->struct_type();
  if (type->num_fields() != static_cast<int>(expected.size())) {
    return arrow::Status::Invalid(name,
                                  " struct has an unexpected child count");
  }
  for (int index = 0; index < type->num_fields(); ++index) {
    const auto& expected_field = expected[static_cast<std::size_t>(index)];
    if (type->field(index)->name() != expected_field->name() ||
        !type->field(index)->type()->Equals(*expected_field->type())) {
      return arrow::Status::Invalid(
          name, " struct has unexpected child name, order, or physical type");
    }
  }
  return arrow::Status::OK();
}

arrow::Result<double> ReadStructDouble(
    const std::shared_ptr<arrow::StructArray>& array, int child_index,
    const std::string& name) {
  auto child =
      std::dynamic_pointer_cast<arrow::DoubleArray>(array->field(child_index));
  if (!child) {
    return arrow::Status::Invalid(name, " must be float64");
  }
  if (child->IsNull(0)) {
    return arrow::Status::Invalid(name, " must not be null");
  }
  return child->Value(0);
}

arrow::Result<std::optional<ImuOrientation>> ReadOrientation(
    const arrow::RecordBatch& batch) {
  ARROW_ASSIGN_OR_RAISE(
      auto array,
      UniqueArray<arrow::StructArray>(batch, "orientation"));
  ARROW_RETURN_NOT_OK(
      ValidateStructType(array, OrientationFields(), "orientation"));
  if (array->IsNull(0)) return std::optional<ImuOrientation>{};

  ImuOrientation value;
  ARROW_ASSIGN_OR_RAISE(value.qx,
                        ReadStructDouble(array, 0, "orientation.qx"));
  ARROW_ASSIGN_OR_RAISE(value.qy,
                        ReadStructDouble(array, 1, "orientation.qy"));
  ARROW_ASSIGN_OR_RAISE(value.qz,
                        ReadStructDouble(array, 2, "orientation.qz"));
  ARROW_ASSIGN_OR_RAISE(value.qw,
                        ReadStructDouble(array, 3, "orientation.qw"));
  return std::optional<ImuOrientation>{value};
}

arrow::Result<ImuVector3> ReadVector3(const arrow::RecordBatch& batch,
                                      const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto array,
                        UniqueArray<arrow::StructArray>(batch, name));
  ARROW_RETURN_NOT_OK(ValidateStructType(array, Vector3Fields(), name));
  if (array->IsNull(0)) {
    return arrow::Status::Invalid(name, " must contain one non-null struct row");
  }

  ImuVector3 value;
  ARROW_ASSIGN_OR_RAISE(value.x,
                        ReadStructDouble(array, 0, name + ".x"));
  ARROW_ASSIGN_OR_RAISE(value.y,
                        ReadStructDouble(array, 1, name + ".y"));
  ARROW_ASSIGN_OR_RAISE(value.z,
                        ReadStructDouble(array, 2, name + ".z"));
  return value;
}

arrow::Result<std::vector<double>> ReadCovariance(
    const arrow::RecordBatch& batch, const std::string& name) {
  ARROW_ASSIGN_OR_RAISE(auto list,
                        UniqueArray<arrow::ListArray>(batch, name));
  if (list->IsNull(0)) {
    return arrow::Status::Invalid(name,
                                  " must contain one non-null list row");
  }
  auto values =
      std::dynamic_pointer_cast<arrow::DoubleArray>(list->value_slice(0));
  if (!values) {
    return arrow::Status::Invalid(name, " values must be float64");
  }
  if (values->null_count() != 0) {
    return arrow::Status::Invalid(name, " values must not contain nulls");
  }

  std::vector<double> result;
  result.reserve(static_cast<std::size_t>(values->length()));
  for (std::int64_t index = 0; index < values->length(); ++index) {
    result.push_back(values->Value(index));
  }
  return result;
}

arrow::Result<std::optional<double>> ReadTemperature(
    const arrow::RecordBatch& batch) {
  ARROW_ASSIGN_OR_RAISE(
      auto array,
      UniqueArray<arrow::DoubleArray>(batch, "temperature_celsius"));
  if (array->IsNull(0)) return std::optional<double>{};
  return std::optional<double>{array->Value(0)};
}

}  // namespace

arrow::Status ImuOrientation::Validate() const {
  if (!std::isfinite(qx) || !std::isfinite(qy) || !std::isfinite(qz) ||
      !std::isfinite(qw)) {
    return arrow::Status::Invalid(
        "orientation quaternion components must be finite");
  }
  if (qx == 0.0 && qy == 0.0 && qz == 0.0 && qw == 0.0) {
    return arrow::Status::Invalid(
        "orientation quaternion must not be all zero");
  }
  return arrow::Status::OK();
}

arrow::Status ImuVector3::Validate() const {
  return ValidateFiniteVector("ImuVector3", *this);
}

arrow::Status Imu::Validate() const {
  if (orientation) ARROW_RETURN_NOT_OK(orientation->Validate());
  ARROW_RETURN_NOT_OK(
      ValidateFiniteVector("angular_velocity", angular_velocity));
  ARROW_RETURN_NOT_OK(
      ValidateFiniteVector("linear_acceleration", linear_acceleration));
  ARROW_RETURN_NOT_OK(
      ValidateCovariance("orientation_covariance", orientation_covariance));
  ARROW_RETURN_NOT_OK(ValidateCovariance("angular_velocity_covariance",
                                        angular_velocity_covariance));
  ARROW_RETURN_NOT_OK(ValidateCovariance("linear_acceleration_covariance",
                                        linear_acceleration_covariance));
  if (!orientation && !orientation_covariance.empty()) {
    return arrow::Status::Invalid(
        "orientation_covariance must be empty when orientation is absent");
  }
  if (temperature_celsius && !std::isfinite(*temperature_celsius)) {
    return arrow::Status::Invalid(
        "temperature_celsius must be finite when present");
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Imu::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());

  ARROW_ASSIGN_OR_RAISE(auto orientation_array, OrientationArray(orientation));
  ARROW_ASSIGN_OR_RAISE(auto angular_velocity_array,
                        Vector3Array(angular_velocity));
  ARROW_ASSIGN_OR_RAISE(auto linear_acceleration_array,
                        Vector3Array(linear_acceleration));
  ARROW_ASSIGN_OR_RAISE(auto orientation_covariance_array,
                        F64List(orientation_covariance));
  ARROW_ASSIGN_OR_RAISE(auto angular_velocity_covariance_array,
                        F64List(angular_velocity_covariance));
  ARROW_ASSIGN_OR_RAISE(auto linear_acceleration_covariance_array,
                        F64List(linear_acceleration_covariance));
  ARROW_ASSIGN_OR_RAISE(auto temperature_array,
                        OptionalF64(temperature_celsius));

  const auto orientation_type = arrow::struct_(OrientationFields());
  const auto vector_type = arrow::struct_(Vector3Fields());
  const auto covariance_type = ListType(arrow::float64());
  return MakeBatch(
      {arrow::field("orientation", orientation_type, true),
       arrow::field("angular_velocity", vector_type, false),
       arrow::field("linear_acceleration", vector_type, false),
       arrow::field("orientation_covariance", covariance_type, false),
       arrow::field("angular_velocity_covariance", covariance_type, false),
       arrow::field("linear_acceleration_covariance", covariance_type, false),
       arrow::field("temperature_celsius", arrow::float64(), true)},
      {orientation_array, angular_velocity_array, linear_acceleration_array,
       orientation_covariance_array, angular_velocity_covariance_array,
       linear_acceleration_covariance_array, temperature_array});
}

arrow::Result<Imu> Imu::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Imu value;
  ARROW_ASSIGN_OR_RAISE(value.orientation, ReadOrientation(batch));
  ARROW_ASSIGN_OR_RAISE(value.angular_velocity,
                        ReadVector3(batch, "angular_velocity"));
  ARROW_ASSIGN_OR_RAISE(value.linear_acceleration,
                        ReadVector3(batch, "linear_acceleration"));
  ARROW_ASSIGN_OR_RAISE(value.orientation_covariance,
                        ReadCovariance(batch, "orientation_covariance"));
  ARROW_ASSIGN_OR_RAISE(
      value.angular_velocity_covariance,
      ReadCovariance(batch, "angular_velocity_covariance"));
  ARROW_ASSIGN_OR_RAISE(
      value.linear_acceleration_covariance,
      ReadCovariance(batch, "linear_acceleration_covariance"));
  ARROW_ASSIGN_OR_RAISE(value.temperature_celsius, ReadTemperature(batch));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
