#include "detail.hpp"

#include <cmath>
#include <tuple>

namespace forge_msgs {

using namespace detail;

Pose Pose::Identity(double x_value, double y_value, double z_value) {
  return Pose{x_value, y_value, z_value, 0.0, 0.0, 0.0, 1.0};
}

Pose Pose::FromXyYaw(double x_value, double y_value, double yaw, double z_value) {
  auto half = yaw * 0.5;
  return Pose{x_value, y_value, z_value, 0.0, 0.0, std::sin(half), std::cos(half)};
}

std::tuple<double, double, double> Pose::XyYaw() const {
  auto yaw = std::atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz));
  return {x, y, yaw};
}

arrow::Status Pose::Validate() const { return ValidateQuaternion(qx, qy, qz, qw); }

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Pose::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto x_array, ScalarF64(x));
  ARROW_ASSIGN_OR_RAISE(auto y_array, ScalarF64(y));
  ARROW_ASSIGN_OR_RAISE(auto z_array, ScalarF64(z));
  ARROW_ASSIGN_OR_RAISE(auto qx_array, ScalarF64(qx));
  ARROW_ASSIGN_OR_RAISE(auto qy_array, ScalarF64(qy));
  ARROW_ASSIGN_OR_RAISE(auto qz_array, ScalarF64(qz));
  ARROW_ASSIGN_OR_RAISE(auto qw_array, ScalarF64(qw));
  return MakeBatch({arrow::field("x", arrow::float64(), false),
                    arrow::field("y", arrow::float64(), false),
                    arrow::field("z", arrow::float64(), false),
                    arrow::field("qx", arrow::float64(), false),
                    arrow::field("qy", arrow::float64(), false),
                    arrow::field("qz", arrow::float64(), false),
                    arrow::field("qw", arrow::float64(), false)},
                   {x_array, y_array, z_array, qx_array, qy_array, qz_array, qw_array});
}

arrow::Result<Pose> Pose::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Pose value;
  ARROW_ASSIGN_OR_RAISE(value.x, ReadF64(batch, "x"));
  ARROW_ASSIGN_OR_RAISE(value.y, ReadF64(batch, "y"));
  ARROW_ASSIGN_OR_RAISE(value.z, ReadF64(batch, "z"));
  ARROW_ASSIGN_OR_RAISE(value.qx, ReadF64(batch, "qx"));
  ARROW_ASSIGN_OR_RAISE(value.qy, ReadF64(batch, "qy"));
  ARROW_ASSIGN_OR_RAISE(value.qz, ReadF64(batch, "qz"));
  ARROW_ASSIGN_OR_RAISE(value.qw, ReadF64(batch, "qw"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status PoseSet::Validate() const {
  if (name.empty()) return arrow::Status::Invalid("name must contain at least one pose");
  ARROW_RETURN_NOT_OK(ValidateUnique("name", name));
  ARROW_RETURN_NOT_OK(ValidateLen("x", x, name.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("y", y, name.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("z", z, name.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("qx", qx, name.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("qy", qy, name.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("qz", qz, name.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("qw", qw, name.size()));
  for (std::size_t i = 0; i < name.size(); ++i) {
    ARROW_RETURN_NOT_OK(ValidateQuaternion(qx[i], qy[i], qz[i], qw[i]));
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> PoseSet::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto name_array, StringList(name));
  ARROW_ASSIGN_OR_RAISE(auto x_array, F64List(x));
  ARROW_ASSIGN_OR_RAISE(auto y_array, F64List(y));
  ARROW_ASSIGN_OR_RAISE(auto z_array, F64List(z));
  ARROW_ASSIGN_OR_RAISE(auto qx_array, F64List(qx));
  ARROW_ASSIGN_OR_RAISE(auto qy_array, F64List(qy));
  ARROW_ASSIGN_OR_RAISE(auto qz_array, F64List(qz));
  ARROW_ASSIGN_OR_RAISE(auto qw_array, F64List(qw));
  auto f64_list = ListType(arrow::float64());
  return MakeBatch({arrow::field("name", ListType(arrow::utf8()), false),
                    arrow::field("x", f64_list, false),
                    arrow::field("y", f64_list, false),
                    arrow::field("z", f64_list, false),
                    arrow::field("qx", f64_list, false),
                    arrow::field("qy", f64_list, false),
                    arrow::field("qz", f64_list, false),
                    arrow::field("qw", f64_list, false)},
                   {name_array, x_array, y_array, z_array, qx_array, qy_array, qz_array, qw_array});
}

arrow::Result<PoseSet> PoseSet::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  PoseSet value;
  ARROW_ASSIGN_OR_RAISE(value.name, ReadStringList(batch, "name"));
  ARROW_ASSIGN_OR_RAISE(value.x, ReadF64List(batch, "x"));
  ARROW_ASSIGN_OR_RAISE(value.y, ReadF64List(batch, "y"));
  ARROW_ASSIGN_OR_RAISE(value.z, ReadF64List(batch, "z"));
  ARROW_ASSIGN_OR_RAISE(value.qx, ReadF64List(batch, "qx"));
  ARROW_ASSIGN_OR_RAISE(value.qy, ReadF64List(batch, "qy"));
  ARROW_ASSIGN_OR_RAISE(value.qz, ReadF64List(batch, "qz"));
  ARROW_ASSIGN_OR_RAISE(value.qw, ReadF64List(batch, "qw"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
