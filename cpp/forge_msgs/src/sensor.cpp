#include "detail.hpp"

#include <algorithm>
#include <cmath>

namespace forge_msgs {

using namespace detail;

arrow::Status Image::Validate() const {
  auto bytes_per_pixel = BytesPerPixel(encoding);
  if (bytes_per_pixel == 0) return arrow::Status::Invalid("unsupported encoding: ", encoding);
  auto minimum_step = static_cast<std::size_t>(width) * bytes_per_pixel;
  if (step < minimum_step) return arrow::Status::Invalid("step is smaller than width * bytes_per_pixel");
  auto expected = static_cast<std::size_t>(step) * height;
  if (data.size() != expected) return arrow::Status::Invalid("data length must equal step * height");
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Image::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto height_array, ScalarU32(height));
  ARROW_ASSIGN_OR_RAISE(auto width_array, ScalarU32(width));
  ARROW_ASSIGN_OR_RAISE(auto encoding_array, ScalarString(encoding));
  ARROW_ASSIGN_OR_RAISE(auto step_array, ScalarU32(step));
  ARROW_ASSIGN_OR_RAISE(auto data_array, ScalarBinary(data));
  return MakeBatch({arrow::field("height", arrow::uint32(), false),
                    arrow::field("width", arrow::uint32(), false),
                    arrow::field("encoding", arrow::utf8(), false),
                    arrow::field("step", arrow::uint32(), false),
                    arrow::field("data", arrow::large_binary(), false)},
                   {height_array, width_array, encoding_array, step_array, data_array});
}

arrow::Result<Image> Image::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Image value;
  ARROW_ASSIGN_OR_RAISE(value.height, ReadU32(batch, "height"));
  ARROW_ASSIGN_OR_RAISE(value.width, ReadU32(batch, "width"));
  ARROW_ASSIGN_OR_RAISE(value.encoding, ReadString(batch, "encoding"));
  ARROW_ASSIGN_OR_RAISE(value.step, ReadU32(batch, "step"));
  ARROW_ASSIGN_OR_RAISE(value.data, ReadBinary(batch, "data"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status CompressedImage::Validate() const {
  if (format.empty()) return arrow::Status::Invalid("format must be non-empty");
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> CompressedImage::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto format_array, ScalarString(format));
  ARROW_ASSIGN_OR_RAISE(auto data_array, ScalarBinary(data));
  return MakeBatch({arrow::field("format", arrow::utf8(), false),
                    arrow::field("data", arrow::large_binary(), false)},
                   {format_array, data_array});
}

arrow::Result<CompressedImage> CompressedImage::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  CompressedImage value;
  ARROW_ASSIGN_OR_RAISE(value.format, ReadString(batch, "format"));
  ARROW_ASSIGN_OR_RAISE(value.data, ReadBinary(batch, "data"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Result<PointCloud> PointCloud::FromXyz(std::vector<float> x_values,
                                              std::vector<float> y_values,
                                              std::vector<float> z_values) {
  PointCloud value;
  value.width = static_cast<std::uint32_t>(x_values.size());
  value.height = 1;
  value.is_dense = std::all_of(x_values.begin(), x_values.end(), [](float v) { return std::isfinite(v); }) &&
                   std::all_of(y_values.begin(), y_values.end(), [](float v) { return std::isfinite(v); }) &&
                   std::all_of(z_values.begin(), z_values.end(), [](float v) { return std::isfinite(v); });
  value.x = std::move(x_values);
  value.y = std::move(y_values);
  value.z = std::move(z_values);
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status PointCloud::Validate() const {
  auto count = x.size();
  if (y.size() != count || z.size() != count) return arrow::Status::Invalid("x, y, and z must have the same length");
  if (static_cast<std::size_t>(width) * height != count) return arrow::Status::Invalid("width * height must equal point count");
  ARROW_RETURN_NOT_OK(ValidateLen("intensity", intensity, count, true));
  ARROW_RETURN_NOT_OK(ValidateLen("red", red, count, true));
  ARROW_RETURN_NOT_OK(ValidateLen("green", green, count, true));
  ARROW_RETURN_NOT_OK(ValidateLen("blue", blue, count, true));
  bool any_rgb = !red.empty() || !green.empty() || !blue.empty();
  bool all_rgb = !red.empty() && !green.empty() && !blue.empty();
  if (any_rgb && !all_rgb) return arrow::Status::Invalid("red, green, and blue must all be empty or all populated");
  if (is_dense) {
    for (float value : x) if (!std::isfinite(value)) return arrow::Status::Invalid("dense point clouds must contain finite XYZ values");
    for (float value : y) if (!std::isfinite(value)) return arrow::Status::Invalid("dense point clouds must contain finite XYZ values");
    for (float value : z) if (!std::isfinite(value)) return arrow::Status::Invalid("dense point clouds must contain finite XYZ values");
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> PointCloud::ToRecordBatch() const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto width_array, ScalarU32(width));
  ARROW_ASSIGN_OR_RAISE(auto height_array, ScalarU32(height));
  ARROW_ASSIGN_OR_RAISE(auto is_dense_array, ScalarBool(is_dense));
  ARROW_ASSIGN_OR_RAISE(auto x_array, F32List(x));
  ARROW_ASSIGN_OR_RAISE(auto y_array, F32List(y));
  ARROW_ASSIGN_OR_RAISE(auto z_array, F32List(z));
  ARROW_ASSIGN_OR_RAISE(auto intensity_array, F32List(intensity));
  ARROW_ASSIGN_OR_RAISE(auto red_array, U8List(red));
  ARROW_ASSIGN_OR_RAISE(auto green_array, U8List(green));
  ARROW_ASSIGN_OR_RAISE(auto blue_array, U8List(blue));
  auto f32_list = ListType(arrow::float32());
  auto u8_list = ListType(arrow::uint8());
  return MakeBatch({arrow::field("width", arrow::uint32(), false),
                    arrow::field("height", arrow::uint32(), false),
                    arrow::field("is_dense", arrow::boolean(), false),
                    arrow::field("x", f32_list, false),
                    arrow::field("y", f32_list, false),
                    arrow::field("z", f32_list, false),
                    arrow::field("intensity", f32_list, false),
                    arrow::field("red", u8_list, false),
                    arrow::field("green", u8_list, false),
                    arrow::field("blue", u8_list, false)},
                   {width_array, height_array, is_dense_array, x_array, y_array, z_array,
                    intensity_array, red_array, green_array, blue_array});
}

arrow::Result<PointCloud> PointCloud::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  PointCloud value;
  ARROW_ASSIGN_OR_RAISE(value.width, ReadU32(batch, "width"));
  ARROW_ASSIGN_OR_RAISE(value.height, ReadU32(batch, "height"));
  ARROW_ASSIGN_OR_RAISE(value.is_dense, ReadBool(batch, "is_dense"));
  ARROW_ASSIGN_OR_RAISE(value.x, ReadF32List(batch, "x"));
  ARROW_ASSIGN_OR_RAISE(value.y, ReadF32List(batch, "y"));
  ARROW_ASSIGN_OR_RAISE(value.z, ReadF32List(batch, "z"));
  ARROW_ASSIGN_OR_RAISE(value.intensity, ReadF32List(batch, "intensity"));
  ARROW_ASSIGN_OR_RAISE(value.red, ReadU8List(batch, "red"));
  ARROW_ASSIGN_OR_RAISE(value.green, ReadU8List(batch, "green"));
  ARROW_ASSIGN_OR_RAISE(value.blue, ReadU8List(batch, "blue"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
