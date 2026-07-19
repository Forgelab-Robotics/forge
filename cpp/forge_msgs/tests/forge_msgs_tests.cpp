#include "forge_msgs/forge_msgs.hpp"

#include <cmath>
#include <iostream>
#include <string>
#include <tuple>
#include <vector>

namespace {

int failures = 0;

void Check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << "\n";
    ++failures;
  }
}

void CheckFieldOrder(const arrow::RecordBatch& batch,
                     const std::vector<std::string>& expected,
                     const std::string& name) {
  Check(batch.num_columns() == static_cast<int>(expected.size()), name + " field count");
  if (batch.num_columns() != static_cast<int>(expected.size())) return;
  for (int i = 0; i < batch.num_columns(); ++i) {
    Check(batch.schema()->field(i)->name() == expected[static_cast<std::size_t>(i)],
          name + " field order at " + std::to_string(i));
  }
}

template <typename Message>
void CheckRoundTrip(const Message& message, const std::string& name) {
  auto batch = message.ToRecordBatch();
  Check(batch.ok(), name + " ToRecordBatch");
  if (!batch.ok()) return;
  auto back = Message::FromRecordBatch(**batch);
  Check(back.ok(), name + " FromRecordBatch");
  if (!back.ok()) return;
  Check((*back).ToRecordBatch().ok(), name + " returned value is valid");
}

}  // namespace

int main() {
  using namespace forge_msgs;

  CheckRoundTrip(Text{"前进"}, "Text");

  Bytes audio_data;
  for (float value : {0.0f, 0.25f, -0.5f, 1.0f}) {
    auto* bytes = reinterpret_cast<std::uint8_t*>(&value);
    audio_data.insert(audio_data.end(), bytes, bytes + sizeof(float));
  }
  CheckRoundTrip(AudioChunk{16000, 1, "f32le", 4, audio_data}, "AudioChunk");
  Check(!AudioChunk{16000, 2, "s16le", 2, {1, 2, 3}}.Validate().ok(),
        "AudioChunk rejects invalid data length");

  CheckRoundTrip(Image{2, 2, "rgb8", 6, Bytes{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}},
                 "Image");
  CheckRoundTrip(CompressedImage{"jpeg", Bytes{0xff, 0xd8, 0xff, 0xd9}}, "CompressedImage");

  CheckRoundTrip(PointCloud{2, 1, true, {1.0f, 2.0f}, {3.0f, 4.0f}, {5.0f, 6.0f},
                            {}, {255, 0}, {0, 255}, {0, 0}},
                 "PointCloud");
  Check(!PointCloud{1, 1, true, {NAN}, {0.0f}, {0.0f}, {}, {}, {}, {}}.Validate().ok(),
        "PointCloud rejects dense NaN");

  CheckRoundTrip(JointState{{"j1", "j2"}, {1.0, 2.0}, {0.1, 0.2}, {}}, "JointState");
  CheckRoundTrip(JointCommand{{"j1"}, "hybrid", {1.0}, {0.0}, {0.5}, {20.0}, {1.0}},
                 "JointCommand");
  Check(!JointCommand{{"j1"}, "bad", {}, {}, {}, {}, {}}.Validate().ok(),
        "JointCommand rejects invalid mode");

  CheckRoundTrip(LocomotionCommand{0.5, 0.1, 0.2}, "LocomotionCommand");
  Check(!LocomotionCommand{NAN, 0.0, 0.0}.Validate().ok(),
        "LocomotionCommand rejects NaN");

  CheckRoundTrip(PolicyCommand{"default", "start_recording", "rec-001", "{\"path\":\"x\"}"},
                 "PolicyCommand");
  CheckRoundTrip(PolicyCommandStatus{"default", "start_recording", "rec-001",
                                     PolicyCommandStatusValue::Done, "done", "{\"ok\":true}"},
                 "PolicyCommandStatus");
  Check(!PolicyCommand{"default", "Start", "", "{}"}.Validate().ok(),
        "PolicyCommand rejects non snake_case");

  auto pose = Pose::FromXyYaw(1.0, 2.0, 1.5707963267948966, 0.0);
  CheckRoundTrip(pose, "Pose");
  auto [x, y, yaw] = pose.XyYaw();
  Check(x == 1.0 && y == 2.0 && std::abs(yaw - 1.5707963267948966) < 1e-12,
        "Pose XyYaw helper");
  CheckRoundTrip(PoseSet{{"a", "b"}, {1.0, 2.0}, {2.0, 3.0}, {0.0, 0.0},
                         {0.0, 0.0}, {0.0, 0.0}, {0.0, 0.0}, {1.0, 1.0}},
                 "PoseSet");

  CheckRoundTrip(Classification{{"person", "vehicle"}, {0.9f, 0.1f}}, "Classification");
  Check(!Classification{{"person", "person"}, {0.9f, 0.1f}}.Validate().ok(),
        "Classification rejects duplicate class_id");
  Check(!Classification{{"person"}, {NAN}}.Validate().ok(),
        "Classification rejects non-finite score");
  Check(!Classification{{"person"}, {1.1f}}.Validate().ok(),
        "Classification rejects score outside [0, 1]");

  Keypoint2DSet keypoints_2d{{"person-0", "person-1"}, {}, {}, {0, 2, 3},
                            {"left_eye", "right_eye", "left_eye"},
                            {10.0f, 12.0f, 30.0f}, {20.0f, 20.0f, 40.0f},
                            {0.9f, 0.8f, 0.7f}};
  CheckRoundTrip(keypoints_2d, "Keypoint2DSet");
  auto keypoints_2d_batch = keypoints_2d.ToRecordBatch();
  Check(keypoints_2d_batch.ok(), "Keypoint2DSet schema batch");
  if (keypoints_2d_batch.ok()) {
    CheckFieldOrder(**keypoints_2d_batch,
                    {"instance_id", "detection_id", "track_id", "keypoint_offset",
                     "keypoint_id", "x", "y", "score"},
                    "Keypoint2DSet");
  }
  CheckRoundTrip(Keypoint2DSet{}, "Keypoint2DSet empty defaults");
  Check(!Keypoint2DSet{{"a", "a"}, {"", ""}, {"", ""}, {0, 0, 0}, {}, {}, {}, {}}
             .Validate()
             .ok(),
        "Keypoint2DSet rejects duplicate instance_id");
  Check(!Keypoint2DSet{{"a"}, {""}, {""}, {0, 2}, {"nose", "nose"},
                       {1.0f, 2.0f}, {3.0f, 4.0f}, {0.8f, 0.7f}}
             .Validate()
             .ok(),
        "Keypoint2DSet rejects duplicate keypoint_id within an instance");
  Check(Keypoint2DSet{{"a", "b"}, {"", ""}, {"", ""}, {0, 1, 2}, {"nose", "nose"},
                      {1.0f, 2.0f}, {3.0f, 4.0f}, {0.8f, 0.7f}}
            .Validate()
            .ok(),
        "Keypoint2DSet allows keypoint_id reuse across instances");
  Check(!Keypoint2DSet{{"a"}, {""}, {""}, {1, 1}, {}, {}, {}, {}}.Validate().ok(),
        "Keypoint2DSet rejects offset not starting at zero");
  Check(!Keypoint2DSet{{"a"}, {""}, {""}, {0, 1}, {"nose"}, {NAN}, {2.0f}, {0.5f}}
             .Validate()
             .ok(),
        "Keypoint2DSet rejects non-finite coordinates");

  Keypoint3DSet keypoints_3d{{"person-0"}, {"d0"}, {"track-7"}, {0, 2},
                            {"left_hand", "right_hand"}, {1.0f, 2.0f}, {3.0f, 4.0f},
                            {5.0f, 6.0f}, {0.95f, 0.85f}};
  CheckRoundTrip(keypoints_3d, "Keypoint3DSet");
  auto keypoints_3d_batch = keypoints_3d.ToRecordBatch();
  Check(keypoints_3d_batch.ok(), "Keypoint3DSet schema batch");
  if (keypoints_3d_batch.ok()) {
    CheckFieldOrder(**keypoints_3d_batch,
                    {"instance_id", "detection_id", "track_id", "keypoint_offset",
                     "keypoint_id", "x", "y", "z", "score"},
                    "Keypoint3DSet");
  }
  Check(!Keypoint3DSet{{"a"}, {""}, {""}, {0, 1}, {"nose"}, {1.0f}, {2.0f}, {3.0f},
                       {-0.1f}}
             .Validate()
             .ok(),
        "Keypoint3DSet rejects score outside [0, 1]");

  CheckRoundTrip(Detection2DSet{{"d0", "d1"}, {"track-7", ""}, {10.5f, 20.0f},
                                {11.0f, 21.0f}, {4.0f, 8.0f}, {5.0f, 9.0f},
                                {0.0f, 0.25f}, {0, 2, 3}, {"person", "worker", "cup"},
                                {0.9f, 0.1f, 0.8f}},
                 "Detection2DSet");
  CheckRoundTrip(Detection2DSet::Empty(), "Detection2DSet empty");

  CheckRoundTrip(Detection3DSet{{"d0"}, {""}, {1.0f}, {2.0f}, {3.0f}, {0.0f}, {0.0f},
                                {0.0f}, {1.0f}, {0.5f}, {0.6f}, {0.7f}, {0, 1},
                                {"box"}, {0.95f}},
                 "Detection3DSet");
  SegmentationMaskSet masks{{"m0"}, {"d0"}, {""}, {4}, {5}, {2}, {2},
                            "mono8", {Bytes{0, 255, 255, 0}}, {0.98f}};
  CheckRoundTrip(masks, "SegmentationMaskSet");
  auto masks_batch = masks.ToRecordBatch();
  Check(masks_batch.ok(), "SegmentationMaskSet schema batch");
  if (masks_batch.ok()) {
    CheckFieldOrder(**masks_batch,
                    {"mask_id", "detection_id", "track_id", "x_offset", "y_offset", "width",
                     "height", "encoding", "data", "score"},
                    "SegmentationMaskSet");

    std::vector<std::shared_ptr<arrow::Field>> legacy_fields;
    std::vector<std::shared_ptr<arrow::Array>> legacy_columns;
    for (int i = 0; i < (*masks_batch)->num_columns() - 1; ++i) {
      legacy_fields.push_back((*masks_batch)->schema()->field(i));
      legacy_columns.push_back((*masks_batch)->column(i));
    }
    auto legacy_batch = arrow::RecordBatch::Make(arrow::schema(legacy_fields), 1, legacy_columns);
    auto legacy_masks = SegmentationMaskSet::FromRecordBatch(*legacy_batch);
    Check(legacy_masks.ok() && legacy_masks->score.empty(),
          "SegmentationMaskSet reads legacy batch without score");

  }
  auto masks_without_score = SegmentationMaskSet{{"m0"}, {}, {}, {}, {}, {1}, {1},
                                                  "mono8", {Bytes{255}}, {}}
                                 .ToRecordBatch();
  Check(masks_without_score.ok(), "SegmentationMaskSet allows empty score");
  if (masks_without_score.ok()) {
    Check((*masks_without_score)->GetColumnByName("score") != nullptr,
          "SegmentationMaskSet always emits score");
  }
  Check(!SegmentationMaskSet{{"m0"}, {""}, {""}, {0}, {0}, {1}, {1}, "mono8",
                             {Bytes{255}}, {NAN}}
             .Validate()
             .ok(),
        "SegmentationMaskSet rejects non-finite score");
  Check(!SegmentationMaskSet{{"m0"}, {""}, {""}, {0}, {0}, {1}, {1}, "mono8",
                             {Bytes{255}}, {0.5f, 0.6f}}
             .Validate()
             .ok(),
        "SegmentationMaskSet rejects score length mismatch");

  if (failures != 0) {
    std::cerr << failures << " failure(s)\n";
    return 1;
  }
  return 0;
}
