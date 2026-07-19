#include "detail.hpp"

#include <set>
#include <utility>

namespace forge_msgs {

using namespace detail;

namespace {

arrow::Status ValidateScores(const std::string& name, const std::vector<float>& scores) {
  for (float score : scores) {
    if (!std::isfinite(score) || score < 0.0f || score > 1.0f) {
      return arrow::Status::Invalid(name, " values must be finite and in [0, 1]");
    }
  }
  return arrow::Status::OK();
}

arrow::Status ValidateKeypoints(const std::vector<std::string>& instance_id,
                                const std::vector<std::string>& detection_id,
                                const std::vector<std::string>& track_id,
                                const std::vector<std::uint32_t>& keypoint_offset,
                                const std::vector<std::string>& keypoint_id,
                                const std::vector<float>& score) {
  const auto instance_count = instance_id.size();
  ARROW_RETURN_NOT_OK(ValidateUnique("instance_id", instance_id));
  ARROW_RETURN_NOT_OK(ValidateLen("detection_id", detection_id, instance_count));
  ARROW_RETURN_NOT_OK(ValidateLen("track_id", track_id, instance_count));
  if (keypoint_offset.size() != instance_count + 1) {
    return arrow::Status::Invalid("keypoint_offset must have instance count + 1 entries");
  }
  if (keypoint_offset.empty() || keypoint_offset.front() != 0 ||
      keypoint_offset.back() != keypoint_id.size()) {
    return arrow::Status::Invalid("keypoint_offset must start at 0 and end at len(keypoint_id)");
  }
  for (std::size_t i = 1; i < keypoint_offset.size(); ++i) {
    if (keypoint_offset[i] < keypoint_offset[i - 1]) {
      return arrow::Status::Invalid("keypoint_offset must be monotonically non-decreasing");
    }
  }
  ARROW_RETURN_NOT_OK(ValidateLen("score", score, keypoint_id.size()));
  ARROW_RETURN_NOT_OK(ValidateScores("score", score));
  for (std::size_t instance = 0; instance < instance_count; ++instance) {
    std::set<std::string> seen;
    for (std::uint32_t i = keypoint_offset[instance]; i < keypoint_offset[instance + 1]; ++i) {
      if (!seen.insert(keypoint_id[i]).second) {
        return arrow::Status::Invalid("keypoint_id items must be unique within each instance");
      }
    }
  }
  return arrow::Status::OK();
}

}  // namespace

arrow::Status Classification::NormalizeDefaults() { return arrow::Status::OK(); }

arrow::Status Classification::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateUnique("class_id", class_id));
  ARROW_RETURN_NOT_OK(ValidateLen("score", score, class_id.size()));
  return ValidateScores("score", score);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Classification::ToRecordBatch() const {
  auto value = *this;
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  ARROW_ASSIGN_OR_RAISE(auto class_id_array, StringList(value.class_id));
  ARROW_ASSIGN_OR_RAISE(auto score_array, F32List(value.score));
  return MakeBatch({arrow::field("class_id", ListType(arrow::utf8()), false),
                    arrow::field("score", ListType(arrow::float32()), false)},
                   {class_id_array, score_array});
}

arrow::Result<Classification> Classification::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Classification value;
  ARROW_ASSIGN_OR_RAISE(value.class_id, ReadStringList(batch, "class_id"));
  ARROW_ASSIGN_OR_RAISE(value.score, ReadF32List(batch, "score"));
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status Keypoint2DSet::NormalizeDefaults() {
  const auto count = instance_id.size();
  if (count > 0 && detection_id.empty()) detection_id.assign(count, "");
  if (count > 0 && track_id.empty()) track_id.assign(count, "");
  if (keypoint_offset.empty()) keypoint_offset = {0};
  return arrow::Status::OK();
}

arrow::Status Keypoint2DSet::Validate() const {
  ARROW_RETURN_NOT_OK(
      ValidateKeypoints(instance_id, detection_id, track_id, keypoint_offset, keypoint_id, score));
  ARROW_RETURN_NOT_OK(ValidateLen("x", x, keypoint_id.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("y", y, keypoint_id.size()));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("x", x));
  return ValidateFiniteList("y", y);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Keypoint2DSet::ToRecordBatch() const {
  auto value = *this;
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  ARROW_ASSIGN_OR_RAISE(auto instance_id_array, StringList(value.instance_id));
  ARROW_ASSIGN_OR_RAISE(auto detection_id_array, StringList(value.detection_id));
  ARROW_ASSIGN_OR_RAISE(auto track_id_array, StringList(value.track_id));
  ARROW_ASSIGN_OR_RAISE(auto keypoint_offset_array, U32List(value.keypoint_offset));
  ARROW_ASSIGN_OR_RAISE(auto keypoint_id_array, StringList(value.keypoint_id));
  ARROW_ASSIGN_OR_RAISE(auto x_array, F32List(value.x));
  ARROW_ASSIGN_OR_RAISE(auto y_array, F32List(value.y));
  ARROW_ASSIGN_OR_RAISE(auto score_array, F32List(value.score));
  auto string_list = ListType(arrow::utf8());
  auto f32_list = ListType(arrow::float32());
  return MakeBatch({arrow::field("instance_id", string_list, false),
                    arrow::field("detection_id", string_list, false),
                    arrow::field("track_id", string_list, false),
                    arrow::field("keypoint_offset", ListType(arrow::uint32()), false),
                    arrow::field("keypoint_id", string_list, false),
                    arrow::field("x", f32_list, false),
                    arrow::field("y", f32_list, false),
                    arrow::field("score", f32_list, false)},
                   {instance_id_array, detection_id_array, track_id_array, keypoint_offset_array,
                    keypoint_id_array, x_array, y_array, score_array});
}

arrow::Result<Keypoint2DSet> Keypoint2DSet::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Keypoint2DSet value;
  ARROW_ASSIGN_OR_RAISE(value.instance_id, ReadStringList(batch, "instance_id"));
  ARROW_ASSIGN_OR_RAISE(value.detection_id, ReadStringList(batch, "detection_id"));
  ARROW_ASSIGN_OR_RAISE(value.track_id, ReadStringList(batch, "track_id"));
  ARROW_ASSIGN_OR_RAISE(value.keypoint_offset, ReadU32List(batch, "keypoint_offset"));
  ARROW_ASSIGN_OR_RAISE(value.keypoint_id, ReadStringList(batch, "keypoint_id"));
  ARROW_ASSIGN_OR_RAISE(value.x, ReadF32List(batch, "x"));
  ARROW_ASSIGN_OR_RAISE(value.y, ReadF32List(batch, "y"));
  ARROW_ASSIGN_OR_RAISE(value.score, ReadF32List(batch, "score"));
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status Keypoint3DSet::NormalizeDefaults() {
  const auto count = instance_id.size();
  if (count > 0 && detection_id.empty()) detection_id.assign(count, "");
  if (count > 0 && track_id.empty()) track_id.assign(count, "");
  if (keypoint_offset.empty()) keypoint_offset = {0};
  return arrow::Status::OK();
}

arrow::Status Keypoint3DSet::Validate() const {
  ARROW_RETURN_NOT_OK(
      ValidateKeypoints(instance_id, detection_id, track_id, keypoint_offset, keypoint_id, score));
  ARROW_RETURN_NOT_OK(ValidateLen("x", x, keypoint_id.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("y", y, keypoint_id.size()));
  ARROW_RETURN_NOT_OK(ValidateLen("z", z, keypoint_id.size()));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("x", x));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("y", y));
  return ValidateFiniteList("z", z);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Keypoint3DSet::ToRecordBatch() const {
  auto value = *this;
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  ARROW_ASSIGN_OR_RAISE(auto instance_id_array, StringList(value.instance_id));
  ARROW_ASSIGN_OR_RAISE(auto detection_id_array, StringList(value.detection_id));
  ARROW_ASSIGN_OR_RAISE(auto track_id_array, StringList(value.track_id));
  ARROW_ASSIGN_OR_RAISE(auto keypoint_offset_array, U32List(value.keypoint_offset));
  ARROW_ASSIGN_OR_RAISE(auto keypoint_id_array, StringList(value.keypoint_id));
  ARROW_ASSIGN_OR_RAISE(auto x_array, F32List(value.x));
  ARROW_ASSIGN_OR_RAISE(auto y_array, F32List(value.y));
  ARROW_ASSIGN_OR_RAISE(auto z_array, F32List(value.z));
  ARROW_ASSIGN_OR_RAISE(auto score_array, F32List(value.score));
  auto string_list = ListType(arrow::utf8());
  auto f32_list = ListType(arrow::float32());
  return MakeBatch({arrow::field("instance_id", string_list, false),
                    arrow::field("detection_id", string_list, false),
                    arrow::field("track_id", string_list, false),
                    arrow::field("keypoint_offset", ListType(arrow::uint32()), false),
                    arrow::field("keypoint_id", string_list, false),
                    arrow::field("x", f32_list, false),
                    arrow::field("y", f32_list, false),
                    arrow::field("z", f32_list, false),
                    arrow::field("score", f32_list, false)},
                   {instance_id_array, detection_id_array, track_id_array, keypoint_offset_array,
                    keypoint_id_array, x_array, y_array, z_array, score_array});
}

arrow::Result<Keypoint3DSet> Keypoint3DSet::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Keypoint3DSet value;
  ARROW_ASSIGN_OR_RAISE(value.instance_id, ReadStringList(batch, "instance_id"));
  ARROW_ASSIGN_OR_RAISE(value.detection_id, ReadStringList(batch, "detection_id"));
  ARROW_ASSIGN_OR_RAISE(value.track_id, ReadStringList(batch, "track_id"));
  ARROW_ASSIGN_OR_RAISE(value.keypoint_offset, ReadU32List(batch, "keypoint_offset"));
  ARROW_ASSIGN_OR_RAISE(value.keypoint_id, ReadStringList(batch, "keypoint_id"));
  ARROW_ASSIGN_OR_RAISE(value.x, ReadF32List(batch, "x"));
  ARROW_ASSIGN_OR_RAISE(value.y, ReadF32List(batch, "y"));
  ARROW_ASSIGN_OR_RAISE(value.z, ReadF32List(batch, "z"));
  ARROW_ASSIGN_OR_RAISE(value.score, ReadF32List(batch, "score"));
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

Detection2DSet Detection2DSet::Empty() {
  Detection2DSet value;
  value.hypothesis_offset = {0};
  return value;
}

arrow::Status Detection2DSet::NormalizeDefaults() {
  if (rotation.empty() && !detection_id.empty()) rotation.assign(detection_id.size(), 0.0f);
  return arrow::Status::OK();
}

arrow::Status Detection2DSet::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateUnique("detection_id", detection_id));
  auto count = detection_id.size();
  ARROW_RETURN_NOT_OK(ValidateLen("track_id", track_id, count));
  ARROW_RETURN_NOT_OK(ValidateLen("center_x", center_x, count));
  ARROW_RETURN_NOT_OK(ValidateLen("center_y", center_y, count));
  ARROW_RETURN_NOT_OK(ValidateLen("size_x", size_x, count));
  ARROW_RETURN_NOT_OK(ValidateLen("size_y", size_y, count));
  ARROW_RETURN_NOT_OK(ValidateLen("rotation", rotation, count));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("center_x", center_x));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("center_y", center_y));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("rotation", rotation));
  ARROW_RETURN_NOT_OK(ValidateNonNegativeList("size_x", size_x));
  ARROW_RETURN_NOT_OK(ValidateNonNegativeList("size_y", size_y));
  return ValidateHypotheses(count, hypothesis_offset, class_id, score);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Detection2DSet::ToRecordBatch() const {
  auto value = *this;
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  ARROW_ASSIGN_OR_RAISE(auto detection_id_array, StringList(value.detection_id));
  ARROW_ASSIGN_OR_RAISE(auto track_id_array, StringList(value.track_id));
  ARROW_ASSIGN_OR_RAISE(auto center_x_array, F32List(value.center_x));
  ARROW_ASSIGN_OR_RAISE(auto center_y_array, F32List(value.center_y));
  ARROW_ASSIGN_OR_RAISE(auto size_x_array, F32List(value.size_x));
  ARROW_ASSIGN_OR_RAISE(auto size_y_array, F32List(value.size_y));
  ARROW_ASSIGN_OR_RAISE(auto rotation_array, F32List(value.rotation));
  ARROW_ASSIGN_OR_RAISE(auto hypothesis_offset_array, U32List(value.hypothesis_offset));
  ARROW_ASSIGN_OR_RAISE(auto class_id_array, StringList(value.class_id));
  ARROW_ASSIGN_OR_RAISE(auto score_array, F32List(value.score));
  auto string_list = ListType(arrow::utf8());
  auto f32_list = ListType(arrow::float32());
  return MakeBatch({arrow::field("detection_id", string_list, false),
                    arrow::field("track_id", string_list, false),
                    arrow::field("center_x", f32_list, false),
                    arrow::field("center_y", f32_list, false),
                    arrow::field("size_x", f32_list, false),
                    arrow::field("size_y", f32_list, false),
                    arrow::field("rotation", f32_list, false),
                    arrow::field("hypothesis_offset", ListType(arrow::uint32()), false),
                    arrow::field("class_id", string_list, false),
                    arrow::field("score", f32_list, false)},
                   {detection_id_array, track_id_array, center_x_array, center_y_array, size_x_array,
                    size_y_array, rotation_array, hypothesis_offset_array, class_id_array, score_array});
}

arrow::Result<Detection2DSet> Detection2DSet::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Detection2DSet value;
  ARROW_ASSIGN_OR_RAISE(value.detection_id, ReadStringList(batch, "detection_id"));
  ARROW_ASSIGN_OR_RAISE(value.track_id, ReadStringList(batch, "track_id"));
  ARROW_ASSIGN_OR_RAISE(value.center_x, ReadF32List(batch, "center_x"));
  ARROW_ASSIGN_OR_RAISE(value.center_y, ReadF32List(batch, "center_y"));
  ARROW_ASSIGN_OR_RAISE(value.size_x, ReadF32List(batch, "size_x"));
  ARROW_ASSIGN_OR_RAISE(value.size_y, ReadF32List(batch, "size_y"));
  ARROW_ASSIGN_OR_RAISE(value.rotation, ReadF32List(batch, "rotation"));
  ARROW_ASSIGN_OR_RAISE(value.hypothesis_offset, ReadU32List(batch, "hypothesis_offset"));
  ARROW_ASSIGN_OR_RAISE(value.class_id, ReadStringList(batch, "class_id"));
  ARROW_ASSIGN_OR_RAISE(value.score, ReadF32List(batch, "score"));
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status Detection3DSet::NormalizeDefaults() {
  auto count = detection_id.size();
  if (count > 0 && qx.empty() && qy.empty() && qz.empty() && qw.empty()) {
    qx.assign(count, 0.0f);
    qy.assign(count, 0.0f);
    qz.assign(count, 0.0f);
    qw.assign(count, 1.0f);
  }
  return arrow::Status::OK();
}

arrow::Status Detection3DSet::Validate() const {
  ARROW_RETURN_NOT_OK(ValidateUnique("detection_id", detection_id));
  auto count = detection_id.size();
  for (const auto& item : {std::make_pair("track_id", track_id.size()),
                           std::make_pair("center_x", center_x.size()),
                           std::make_pair("center_y", center_y.size()),
                           std::make_pair("center_z", center_z.size()),
                           std::make_pair("qx", qx.size()),
                           std::make_pair("qy", qy.size()),
                           std::make_pair("qz", qz.size()),
                           std::make_pair("qw", qw.size()),
                           std::make_pair("size_x", size_x.size()),
                           std::make_pair("size_y", size_y.size()),
                           std::make_pair("size_z", size_z.size())}) {
    if (item.second != count) return arrow::Status::Invalid(item.first, " must have the expected length");
  }
  for (std::size_t i = 0; i < count; ++i) {
    ARROW_RETURN_NOT_OK(ValidateQuaternion(qx[i], qy[i], qz[i], qw[i]));
  }
  ARROW_RETURN_NOT_OK(ValidateFiniteList("center_x", center_x));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("center_y", center_y));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("center_z", center_z));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("qx", qx));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("qy", qy));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("qz", qz));
  ARROW_RETURN_NOT_OK(ValidateFiniteList("qw", qw));
  ARROW_RETURN_NOT_OK(ValidateNonNegativeList("size_x", size_x));
  ARROW_RETURN_NOT_OK(ValidateNonNegativeList("size_y", size_y));
  ARROW_RETURN_NOT_OK(ValidateNonNegativeList("size_z", size_z));
  return ValidateHypotheses(count, hypothesis_offset, class_id, score);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> Detection3DSet::ToRecordBatch() const {
  auto value = *this;
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  std::vector<std::shared_ptr<arrow::Array>> columns;
  ARROW_ASSIGN_OR_RAISE(auto detection_id_array, StringList(value.detection_id));
  ARROW_ASSIGN_OR_RAISE(auto track_id_array, StringList(value.track_id));
  ARROW_ASSIGN_OR_RAISE(auto center_x_array, F32List(value.center_x));
  ARROW_ASSIGN_OR_RAISE(auto center_y_array, F32List(value.center_y));
  ARROW_ASSIGN_OR_RAISE(auto center_z_array, F32List(value.center_z));
  ARROW_ASSIGN_OR_RAISE(auto qx_array, F32List(value.qx));
  ARROW_ASSIGN_OR_RAISE(auto qy_array, F32List(value.qy));
  ARROW_ASSIGN_OR_RAISE(auto qz_array, F32List(value.qz));
  ARROW_ASSIGN_OR_RAISE(auto qw_array, F32List(value.qw));
  ARROW_ASSIGN_OR_RAISE(auto size_x_array, F32List(value.size_x));
  ARROW_ASSIGN_OR_RAISE(auto size_y_array, F32List(value.size_y));
  ARROW_ASSIGN_OR_RAISE(auto size_z_array, F32List(value.size_z));
  ARROW_ASSIGN_OR_RAISE(auto hypothesis_offset_array, U32List(value.hypothesis_offset));
  ARROW_ASSIGN_OR_RAISE(auto class_id_array, StringList(value.class_id));
  ARROW_ASSIGN_OR_RAISE(auto score_array, F32List(value.score));
  auto string_list = ListType(arrow::utf8());
  auto f32_list = ListType(arrow::float32());
  return MakeBatch({arrow::field("detection_id", string_list, false),
                    arrow::field("track_id", string_list, false),
                    arrow::field("center_x", f32_list, false),
                    arrow::field("center_y", f32_list, false),
                    arrow::field("center_z", f32_list, false),
                    arrow::field("qx", f32_list, false),
                    arrow::field("qy", f32_list, false),
                    arrow::field("qz", f32_list, false),
                    arrow::field("qw", f32_list, false),
                    arrow::field("size_x", f32_list, false),
                    arrow::field("size_y", f32_list, false),
                    arrow::field("size_z", f32_list, false),
                    arrow::field("hypothesis_offset", ListType(arrow::uint32()), false),
                    arrow::field("class_id", string_list, false),
                    arrow::field("score", f32_list, false)},
                   {detection_id_array, track_id_array, center_x_array, center_y_array, center_z_array,
                    qx_array, qy_array, qz_array, qw_array, size_x_array, size_y_array, size_z_array,
                    hypothesis_offset_array, class_id_array, score_array});
}

arrow::Result<Detection3DSet> Detection3DSet::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  Detection3DSet value;
  ARROW_ASSIGN_OR_RAISE(value.detection_id, ReadStringList(batch, "detection_id"));
  ARROW_ASSIGN_OR_RAISE(value.track_id, ReadStringList(batch, "track_id"));
  ARROW_ASSIGN_OR_RAISE(value.center_x, ReadF32List(batch, "center_x"));
  ARROW_ASSIGN_OR_RAISE(value.center_y, ReadF32List(batch, "center_y"));
  ARROW_ASSIGN_OR_RAISE(value.center_z, ReadF32List(batch, "center_z"));
  ARROW_ASSIGN_OR_RAISE(value.qx, ReadF32List(batch, "qx"));
  ARROW_ASSIGN_OR_RAISE(value.qy, ReadF32List(batch, "qy"));
  ARROW_ASSIGN_OR_RAISE(value.qz, ReadF32List(batch, "qz"));
  ARROW_ASSIGN_OR_RAISE(value.qw, ReadF32List(batch, "qw"));
  ARROW_ASSIGN_OR_RAISE(value.size_x, ReadF32List(batch, "size_x"));
  ARROW_ASSIGN_OR_RAISE(value.size_y, ReadF32List(batch, "size_y"));
  ARROW_ASSIGN_OR_RAISE(value.size_z, ReadF32List(batch, "size_z"));
  ARROW_ASSIGN_OR_RAISE(value.hypothesis_offset, ReadU32List(batch, "hypothesis_offset"));
  ARROW_ASSIGN_OR_RAISE(value.class_id, ReadStringList(batch, "class_id"));
  ARROW_ASSIGN_OR_RAISE(value.score, ReadF32List(batch, "score"));
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

arrow::Status SegmentationMaskSet::NormalizeDefaults() {
  auto count = mask_id.size();
  if (count > 0 && detection_id.empty()) detection_id.assign(count, "");
  if (count > 0 && track_id.empty()) track_id.assign(count, "");
  if (count > 0 && x_offset.empty()) x_offset.assign(count, 0);
  if (count > 0 && y_offset.empty()) y_offset.assign(count, 0);
  if (encoding.empty()) encoding = "mono8";
  return arrow::Status::OK();
}

arrow::Status SegmentationMaskSet::Validate() const {
  if (encoding != "mono8") return arrow::Status::Invalid("encoding must be mono8");
  ARROW_RETURN_NOT_OK(ValidateUnique("mask_id", mask_id));
  auto count = mask_id.size();
  if (detection_id.size() != count || track_id.size() != count || x_offset.size() != count ||
      y_offset.size() != count || width.size() != count || height.size() != count ||
      data.size() != count) {
    return arrow::Status::Invalid("all per-mask lists must have the same length as mask_id");
  }
  ARROW_RETURN_NOT_OK(ValidateLen("score", score, count, true));
  ARROW_RETURN_NOT_OK(ValidateScores("score", score));
  for (std::size_t i = 0; i < count; ++i) {
    if (data[i].size() != static_cast<std::size_t>(width[i]) * height[i]) {
      return arrow::Status::Invalid("data length must equal width * height");
    }
  }
  return arrow::Status::OK();
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> SegmentationMaskSet::ToRecordBatch() const {
  auto value = *this;
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  ARROW_ASSIGN_OR_RAISE(auto mask_id_array, StringList(value.mask_id));
  ARROW_ASSIGN_OR_RAISE(auto detection_id_array, StringList(value.detection_id));
  ARROW_ASSIGN_OR_RAISE(auto track_id_array, StringList(value.track_id));
  ARROW_ASSIGN_OR_RAISE(auto x_offset_array, U32List(value.x_offset));
  ARROW_ASSIGN_OR_RAISE(auto y_offset_array, U32List(value.y_offset));
  ARROW_ASSIGN_OR_RAISE(auto width_array, U32List(value.width));
  ARROW_ASSIGN_OR_RAISE(auto height_array, U32List(value.height));
  ARROW_ASSIGN_OR_RAISE(auto encoding_array, ScalarString(value.encoding));
  ARROW_ASSIGN_OR_RAISE(auto data_array, BinaryList(value.data));
  ARROW_ASSIGN_OR_RAISE(auto score_array, F32List(value.score));
  auto string_list = ListType(arrow::utf8());
  auto u32_list = ListType(arrow::uint32());
  return MakeBatch({arrow::field("mask_id", string_list, false),
                    arrow::field("detection_id", string_list, false),
                    arrow::field("track_id", string_list, false),
                    arrow::field("x_offset", u32_list, false),
                    arrow::field("y_offset", u32_list, false),
                    arrow::field("width", u32_list, false),
                    arrow::field("height", u32_list, false),
                    arrow::field("encoding", arrow::utf8(), false),
                    arrow::field("data", ListType(arrow::large_binary()), false),
                    arrow::field("score", ListType(arrow::float32()), false)},
                   {mask_id_array, detection_id_array, track_id_array, x_offset_array, y_offset_array,
                    width_array, height_array, encoding_array, data_array, score_array});
}

arrow::Result<SegmentationMaskSet> SegmentationMaskSet::FromRecordBatch(const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  SegmentationMaskSet value;
  ARROW_ASSIGN_OR_RAISE(value.mask_id, ReadStringList(batch, "mask_id"));
  ARROW_ASSIGN_OR_RAISE(value.detection_id, ReadStringList(batch, "detection_id"));
  ARROW_ASSIGN_OR_RAISE(value.track_id, ReadStringList(batch, "track_id"));
  ARROW_ASSIGN_OR_RAISE(value.x_offset, ReadU32List(batch, "x_offset"));
  ARROW_ASSIGN_OR_RAISE(value.y_offset, ReadU32List(batch, "y_offset"));
  ARROW_ASSIGN_OR_RAISE(value.width, ReadU32List(batch, "width"));
  ARROW_ASSIGN_OR_RAISE(value.height, ReadU32List(batch, "height"));
  ARROW_ASSIGN_OR_RAISE(value.encoding, ReadString(batch, "encoding"));
  ARROW_ASSIGN_OR_RAISE(value.data, ReadBinaryList(batch, "data"));
  if (Column(batch, "score")) {
    ARROW_ASSIGN_OR_RAISE(value.score, ReadF32List(batch, "score"));
  }
  ARROW_RETURN_NOT_OK(value.NormalizeDefaults());
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
